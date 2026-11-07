"""AD-HS-xx (docs/autodesk/testcases_health_status.md): GET /api/v1/health/status.

Test doubles are labelled MOCK. No test calls Kite, Slack, the real data API or a shared database. Layers: U = unit with
doubles, I = throwaway Postgres, A = FastAPI app with a faked sign-in. AD-HS-140 (real boot) and AD-HS-141 (staging) are
NOT covered here.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import pathlib
import re
import time
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient

from autodesk import contracts as C
from autodesk import store
from autodesk.agents import tech_support as ts
from autodesk.db import create_pool_for
from autodesk.main import build_state, create_app
from autodesk.market.view import DataUnavailable
from autodesk.routers import health_status as hs
from autodesk.routers.api import current_user
from tests.autodesk import marketdata, stubs
from tests.autodesk.conftest import run
from tests.autodesk.test_safety import ADVICE
from tests.autodesk.test_store import _account

NOW = datetime(2026, 11, 6, 4, 0, tzinfo=timezone.utc)          # 09:30 IST, a Friday
SD, PREV = date(2026, 11, 6), date(2026, 11, 5)
SECRET = "daas.example-internal.test:8443"                           # a planted fake host and port, never real
GOLDEN = json.loads((pathlib.Path(__file__).parent / "golden_tech_support.json").read_text())


class SM:      # MOCK — a market view with the knobs the scenarios need; records its calls like FrozenMarketView does
    def __init__(self, *, cash_latest=PREV, cash_rows=6, fno_latest=PREV, fno_rows=6, vix=Decimal("13.5"),
                 prev=PREV, prev_error=None, read_error=None, delay=0.0):
        self.cash_latest, self.cash_rows, self.fno_latest, self.fno_rows = cash_latest, cash_rows, fno_latest, fno_rows
        self.vix_value, self.prev, self.prev_error, self.read_error, self.delay = vix, prev, prev_error, read_error, delay
        self.calls = []

    def _rec(self, tool, day, rows, ok=True, error=None):
        self.calls.append({"tool": tool, "day": day.isoformat() if day else None, "rows": rows, "ok": ok, "error": error})

    def latest_session(self, kind="cash"):
        return self.cash_latest if kind == "cash" else self.fno_latest

    async def previous_session(self, day):
        if self.prev_error:
            raise DataUnavailable(self.prev_error)
        self._rec("previous_session", day, 1)
        return self.prev

    async def day_snapshot(self, day):
        if self.read_error:
            raise DataUnavailable(self.read_error)
        await asyncio.sleep(self.delay)
        self._rec("day_snapshot", day, self.cash_rows)
        return {f"S{i}": 1 for i in range(self.cash_rows)}

    async def fno_universe(self, day=None):
        if self.read_error:
            raise DataUnavailable(self.read_error)
        self._rec("fno_universe", day, self.fno_rows)
        return [f"U{i}" for i in range(self.fno_rows)]

    async def vix(self, day=None):
        if self.read_error:
            raise DataUnavailable(self.read_error)
        d = day or self.cash_latest
        self._rec("vix", d, 0 if self.vix_value is None else 1)
        return self.vix_value


READ_ERR = f"data API: GET https://{SECRET}/prices/eod refused"
SCENARIOS = {       # name -> (session date, SM kwargs, db_ok, thresholds); the 11 scenarios of golden_tech_support.json
    "ready": (SD, {}, True, 2),
    "vix_missing": (SD, {"vix": None}, True, 2),
    "fno_missing": (SD, {"fno_rows": 0}, True, 2),
    "fno_two_sessions_old": (SD, {"fno_latest": date(2026, 11, 4)}, True, 2),
    "cash_file_missing": (SD, {"cash_rows": 0}, True, 2),
    "cash_old_before_cutoff": (SD, {"cash_latest": date(2026, 11, 4), "fno_latest": date(2026, 11, 4), "vix": None},
                               True, 2),
    "data_unreadable": (SD, {"read_error": READ_ERR}, True, 2),
    "database_down": (SD, {}, False, 2),
    "calendar_unknown": (SD, {"prev_error": "the NSE holiday list for 2026 is not loaded"}, True, 2),
    "few_rows_default_thresholds": (SD, {}, True, None),
    "weekend_monday_needs_friday": (date(2026, 11, 9), {"cash_latest": date(2026, 11, 6), "fno_latest": date(2026, 11, 6),
                                                         "prev": date(2026, 11, 6), "cash_rows": 3, "fno_rows": 3,
                                                         "vix": Decimal("13")}, True, 2),
}
STATUS_OF = {"READY": hs.OK, "DEGRADED": hs.DEGRADED, "BLOCKED": hs.BLOCKED}


def run_agent(name, monkeypatch):
    sd, kw, db_ok, thr = SCENARIOS[name]
    if thr:
        monkeypatch.setattr(ts, "MIN_CASH_ROWS", thr)
        monkeypatch.setattr(ts, "MIN_FNO_UNDERLYINGS", thr)
    m = SM(**kw)
    res = run(ts.TechSupport().run(marketdata.task(C.TaskType.PREMARKET_HEALTH_CHECK),
                                   marketdata.ctx(m, {"session_date": sd.isoformat(), "db_ok": db_ok})))
    return res, m


class Clock:
    def __init__(self):
        self.t = 5000.0

    def mono(self):
        return self.t


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(hs, "_mono", c.mono)
    monkeypatch.setattr(hs, "_utcnow", lambda: NOW)
    return c


class FakeConn:      # MOCK
    def __init__(self, pool):
        self.pool = pool

    async def fetchval(self, sql, *a):
        self.pool.sql.append(sql)
        await self.pool.gate()
        return 1

    async def fetchrow(self, sql, *a):
        self.pool.sql.append(sql)
        await self.pool.gate()
        return self.pool.row

    @asynccontextmanager
    async def transaction(self, readonly=False):
        self.pool.readonly.append(readonly)
        yield


class FakePool:      # MOCK
    def __init__(self, *, error=None, hang=False, row=None):
        self.error, self.hang, self.row, self.sql, self.readonly = error, hang, row, [], []

    async def gate(self):
        if self.hang:
            await asyncio.sleep(60)

    @asynccontextmanager
    async def acquire(self):
        if self.error:
            raise self.error
        await self.gate()
        yield FakeConn(self)


def fake_state(pool=None, market=None):
    async def nxt(at):
        return SD
    return SimpleNamespace(pool=pool or FakePool(), market_factory=lambda at: market or SM(), next_session=nxt,
                           background={})


def cancel(st):
    for t in st.background.values():
        t.cancel()


# ── worst part, database ───────────────────────────────────────────────────────────────────────────────────────────
def test_hs80_worst_part_decides():
    p = lambda s: {"status": s}      # noqa: E731
    assert hs.worst({"a": p("OK"), "b": p("OK")}) == "OK"
    assert hs.worst({"a": p("OK"), "b": p("DEGRADED")}) == "DEGRADED"
    assert hs.worst({"a": p("DEGRADED"), "b": p("BLOCKED")}) == "BLOCKED"


def test_hs10_11_12_database(clock, monkeypatch):
    m = hs._Monitor()
    assert run(hs._Monitor._guard("database", m._database(fake_state(), NOW), NOW))["status"] == "OK"
    bad = run(hs._Monitor._guard("database", m._database(fake_state(FakePool(error=RuntimeError(SECRET))), NOW), NOW))
    assert bad["status"] == "BLOCKED" and "RuntimeError" in bad["detail"] and SECRET not in bad["detail"]
    monkeypatch.setattr(hs, "PROBE_TIMEOUT_S", 0.2)
    slow = run(hs._Monitor._guard("database", m._database(fake_state(FakePool(hang=True)), NOW), NOW))
    assert slow["status"] == "BLOCKED" and "did not answer" in slow["detail"]


# ── data_api ───────────────────────────────────────────────────────────────────────────────────────────────────────
def check(monkeypatch, **kw):
    monkeypatch.setattr(ts, "MIN_CASH_ROWS", 2)
    monkeypatch.setattr(ts, "MIN_FNO_UNDERLYINGS", 2)
    return run(hs._Monitor._data_check(fake_state(market=SM(**kw)), NOW))


def test_hs20_22_ok_and_noted(monkeypatch):
    p = check(monkeypatch)
    assert p["status"] == "OK" and "6 cash rows for 2026-11-05" in p["detail"] and p["as_of"]
    q = check(monkeypatch, vix=None)
    assert q["status"] == "OK" and "no India VIX" in q["detail"]


def test_hs21_degraded_when_fno_is_old_or_short(monkeypatch):
    assert check(monkeypatch, fno_latest=date(2026, 11, 4))["status"] == "DEGRADED"
    assert check(monkeypatch, fno_rows=1)["status"] == "DEGRADED"


def test_hs23_blocked_when_cash_is_old_or_short(monkeypatch):
    assert check(monkeypatch, cash_latest=date(2026, 11, 4))["status"] == "BLOCKED"
    assert check(monkeypatch, cash_rows=1)["status"] == "BLOCKED"


def test_hs24_unreadable_hides_host_and_port(monkeypatch):
    p = check(monkeypatch, read_error=READ_ERR)
    assert p["status"] == "BLOCKED" and "could not be read" in p["detail"]
    assert SECRET not in p["detail"] and "daas" not in p["detail"] and "8443" not in p["detail"] and "://" not in p["detail"]


@pytest.mark.parametrize("name", ["ready", "vix_missing", "fno_two_sessions_old", "fno_missing", "cash_file_missing",
                                  "cash_old_before_cutoff", "data_unreadable", "calendar_unknown"])
def test_hs25_route_and_agent_use_the_same_rules(name, monkeypatch):
    res, _ = run_agent(name, monkeypatch)
    sd, kw, _, _ = SCENARIOS[name]
    part = run(hs._Monitor._data_check(SimpleNamespace(market_factory=lambda at: SM(**kw),
                                                       next_session=_const(sd)), NOW))
    agent = res.output["status"]
    assert part["status"] == STATUS_OF[agent], (name, part, agent)


def _const(v):
    async def f(at):
        return v
    return f


def test_hs26_slow_data_check_answers_in_time_then_reports_result(monkeypatch, clock):
    monkeypatch.setattr(hs, "DATA_WAIT_S", 0.1)
    monkeypatch.setattr(ts, "MIN_CASH_ROWS", 2)
    monkeypatch.setattr(ts, "MIN_FNO_UNDERLYINGS", 2)
    st = fake_state(market=SM(delay=0.4))
    m = hs._Monitor()

    async def go():
        t0 = time.monotonic()
        first = await m._data_api(st)
        quick = time.monotonic() - t0
        await st.background[hs.BACKGROUND_KEY]
        return first, quick, await m._data_api(st)
    first, quick, second = run(go())
    assert first["status"] == "DEGRADED" and "still running" in first["detail"] and quick < 0.3
    assert second["status"] == "OK" and second["as_of"]


def test_hs27_old_result_is_not_reported_as_current(monkeypatch, clock):
    monkeypatch.setattr(hs, "DATA_WAIT_S", 0.1)
    st = fake_state(market=SM(delay=5))
    m = hs._Monitor()
    m._data = (clock.t - 400, hs._part(hs.OK, "old ok", NOW))
    p = run(m._data_api(st))
    cancel(st)
    assert p["status"] == "DEGRADED" and "old" in p["detail"] and p["detail"] != "old ok"


def test_hs28_a_check_that_never_finishes_becomes_blocked(monkeypatch, clock):
    monkeypatch.setattr(hs, "DATA_RUN_DEADLINE_S", 0.1)
    m = hs._Monitor()
    run(m._run_data_check(fake_state(market=SM(delay=5))))
    assert m._data[1]["status"] == "BLOCKED" and "did not finish" in m._data[1]["detail"]


# ── redis ──────────────────────────────────────────────────────────────────────────────────────────────────────────
class Redis:      # MOCK
    def __init__(self, ping=True, exc=None, hang=False):
        self.ping_result, self.exc, self.hang = ping, exc, hang

    async def ping(self):
        if self.hang:
            await asyncio.sleep(60)
        if self.exc:
            raise self.exc
        return self.ping_result


def redis_part(monkeypatch, client, *, hang_get=False):
    from services.kite_live_feed import quote_cache

    async def get_client():
        if hang_get:
            await asyncio.sleep(60)
        return client
    monkeypatch.setattr(quote_cache, "get_client", get_client)
    monkeypatch.setattr(hs, "PROBE_TIMEOUT_S", 0.2)
    return run(hs._Monitor._guard("redis", hs._Monitor()._redis(NOW), NOW))


def test_hs40_43_redis(monkeypatch):
    assert redis_part(monkeypatch, Redis())["status"] == "OK"
    assert redis_part(monkeypatch, None)["status"] == "DEGRADED"
    e = redis_part(monkeypatch, Redis(exc=RuntimeError(SECRET)))
    assert e["status"] == "DEGRADED" and "RuntimeError" in e["detail"] and SECRET not in e["detail"]
    assert redis_part(monkeypatch, Redis(hang=True))["status"] == "DEGRADED"
    assert redis_part(monkeypatch, None, hang_get=True)["status"] == "DEGRADED"


# ── quote_feed ─────────────────────────────────────────────────────────────────────────────────────────────────────
def feed(monkeypatch, *, is_open, rows="unset", login="a Kite login is stored and has not expired", spy=None):
    from services.kite_live_feed import quote_cache
    reads = []

    async def read_quotes(symbols):
        reads.append(symbols)
        if spy is not None:
            spy.append("read")
        return rows
    async def phrase(now):       # noqa: E301
        return login
    monkeypatch.setattr(hs, "_market_state", lambda now: is_open)
    monkeypatch.setattr(quote_cache, "read_quotes", read_quotes)
    monkeypatch.setattr(hs, "_login_phrase", phrase)
    return run(hs._Monitor()._quote_feed(NOW)), reads


def tick(ago_s, day_shift=0):
    t = NOW - timedelta(seconds=ago_s, days=day_shift)
    return {"symbol": "NIFTY 50", "ltp": "24000", "received_at": t.isoformat()}


def test_hs50_51_52_53_open_market(monkeypatch):
    assert feed(monkeypatch, is_open=True, rows={"NIFTY 50": tick(20)})[0]["status"] == "OK"
    assert feed(monkeypatch, is_open=True, rows={"NIFTY 50": tick(300)})[0]["status"] == "DEGRADED"
    assert feed(monkeypatch, is_open=True, rows={"NIFTY 50": tick(20, day_shift=1)})[0]["status"] == "DEGRADED"
    assert feed(monkeypatch, is_open=True, rows={})[0]["status"] == "DEGRADED"
    assert feed(monkeypatch, is_open=True, rows=None)[0]["status"] == "DEGRADED"


def test_hs54_closed_market_is_ok_and_cache_unread(monkeypatch):
    p, reads = feed(monkeypatch, is_open=False, rows=None)
    assert p["status"] == "OK" and "closed" in p["detail"] and reads == []


def test_hs55_unknown_calendar_degraded_and_uses_desks_own_rule(monkeypatch):
    p, _ = feed(monkeypatch, is_open=None)
    assert p["status"] == "DEGRADED" and "cannot tell whether the market is open" in p["detail"].lower()
    assert "def _market_open" not in inspect.getsource(hs)       # no second market-hours function


def test_hs55b_market_state_calls_the_desks_own_function(monkeypatch):
    from autodesk.execution import settle
    seen = []
    monkeypatch.setattr(hs.calendar, "is_session", lambda d: True)
    monkeypatch.setattr(settle, "_market_open", lambda now: seen.append(now) or True)
    assert hs._market_state(NOW) is True and seen == [NOW]

    def no_list(d):
        raise hs.calendar.CalendarUnavailable("not loaded")
    monkeypatch.setattr(hs.calendar, "is_session", no_list)
    assert hs._market_state(NOW) is None


def test_hs56_login_wording_never_changes_status(monkeypatch):
    from services.kite_live_feed import platform_token
    cases = {"fresh": ({"stored": True, "expired": False}, "stored and has not expired"),
             "none": ({"stored": False, "expired": False}, "no unexpired"),
             "expired": ({"stored": True, "expired": True}, "no unexpired")}
    for _, (doc, words) in cases.items():
        async def ts_(db, now, doc=doc):
            return doc
        monkeypatch.setattr(platform_token, "token_status", ts_)
        assert words in run(hs._login_phrase(NOW))

    async def boom(db, now):
        raise RuntimeError(SECRET)
    monkeypatch.setattr(platform_token, "token_status", boom)
    t = run(hs._login_phrase(NOW))
    assert "RuntimeError" in t and SECRET not in t

    async def hang(db, now):
        await asyncio.sleep(60)
    monkeypatch.setattr(platform_token, "token_status", hang)
    monkeypatch.setattr(hs, "LOGIN_READ_S", 0.1)
    t0 = time.monotonic()
    assert "in time" in run(hs._login_phrase(NOW)) and time.monotonic() - t0 < 1


def test_hs57_no_kite_call_of_any_kind(monkeypatch):
    from autodesk.market import live_quotes
    hit = []

    def spy(name):
        def f(*a, **k):
            hit.append(name)
            raise AssertionError(name)
        return f
    monkeypatch.setattr(live_quotes, "KiteQuoteSource", spy("KiteQuoteSource"))
    monkeypatch.setattr(live_quotes, "_platform_kite", spy("_platform_kite"))
    from services.kite_live_feed import gateway
    monkeypatch.setattr(gateway, "default_kite_factory", spy("default_kite_factory"))
    feed(monkeypatch, is_open=True, rows={"NIFTY 50": tick(20)})
    feed(monkeypatch, is_open=True, rows={})
    assert hit == []


# ── scheduler, last_cycle ──────────────────────────────────────────────────────────────────────────────────────────
def test_hs60_61_scheduler(monkeypatch):
    for on, words in ((False, "off: session cycles are started by hand"), (True, "no scheduler")):
        monkeypatch.setattr(hs.cfgmod, "load", lambda on=on: SimpleNamespace(scheduler_enabled=on))
        p = run(hs._Monitor()._scheduler())
        assert p["status"] == "DEGRADED" and words in p["detail"]
        if not on:
            assert p["detail"] == words


T7 = "tenant-hs"


async def _cycle(pool, tenant, sd, state, kind=C.WorkflowKind.SESSION_CYCLE, sim=None, acct=None, age_min=0):
    async with pool.acquire() as c:
        acc = acct or await _account(c, tenant)
        wf, _ = await store.create_workflow(c, tenant_id=tenant, account_id=acc["account_id"], kind=kind,
                                            producer="test", session_date=sd, simulation_id=sim)
        await c.execute("UPDATE autodesk.workflows SET state=$2, created_at=$3 WHERE workflow_id=$1",
                        wf["workflow_id"], state, NOW - timedelta(minutes=age_min))
        return wf


async def _wipe(pool):
    async with pool.acquire() as c:
        await c.execute("TRUNCATE autodesk.events, autodesk.workflows CASCADE")


def last_cycle(pool, market=None):
    return run(hs._Monitor()._last_cycle(fake_state(pool, market), NOW))


def test_hs70_71_72_77_cycle_states(pg_pool, clock):
    run(_wipe(pg_pool))
    assert last_cycle(pg_pool)["status"] == "DEGRADED" and "No session cycle" in last_cycle(pg_pool)["detail"]
    for state, want in (("COMPLETED", "OK"), ("RUNNING", "OK"), ("WAITING_HUMAN", "OK"), ("BLOCKED", "BLOCKED"),
                        ("FAILED", "BLOCKED"), ("CANCELLED", "DEGRADED")):
        run(_wipe(pg_pool))
        run(_cycle(pg_pool, T7, PREV, state))
        assert last_cycle(pg_pool)["status"] == want, state


def test_hs73_76_old_session_and_unknown_calendar(pg_pool, clock):
    run(_wipe(pg_pool))
    run(_cycle(pg_pool, T7, date(2026, 11, 3), "COMPLETED"))
    assert last_cycle(pg_pool)["status"] == "DEGRADED" and "older than the previous session" in last_cycle(pg_pool)["detail"]
    run(_wipe(pg_pool))
    run(_cycle(pg_pool, T7, PREV, "COMPLETED"))
    p = last_cycle(pg_pool, SM(prev_error="calendar not loaded"))
    assert p["status"] == "DEGRADED" and "could not be worked out" in p["detail"]


def test_hs74_ignores_simulations_and_other_kinds_over_all_tenants(pg_pool, clock):
    run(_wipe(pg_pool))
    run(_cycle(pg_pool, T7, PREV, "COMPLETED", age_min=60))
    run(_cycle(pg_pool, "tenant-other", PREV, "COMPLETED", age_min=30))
    run(_cycle(pg_pool, T7, PREV, "FAILED", kind=C.WorkflowKind.PREMARKET_CHECK, age_min=5))
    async def newer_simulation_cycle():
        async with pg_pool.acquire() as c:
            cfg = C.SimulationConfig(name="hs", start_date=date(2026, 11, 2), end_date=date(2026, 11, 3))
            sim = await store.create_simulation(c, tenant_id=T7, cfg=cfg, created_by="test", versions={})
        await _cycle(pg_pool, T7, PREV, "FAILED", sim=sim["simulation_id"], age_min=1)
    run(newer_simulation_cycle())
    p = last_cycle(pg_pool)
    assert p["status"] == "OK" and "started 30 minutes ago" in p["detail"]       # the other tenant's cycle is the newest real SESSION_CYCLE


def test_hs75_detail_holds_no_ids(pg_pool, clock):
    run(_wipe(pg_pool))
    wf = run(_cycle(pg_pool, "tenant-secret-id", PREV, "COMPLETED"))
    p = last_cycle(pg_pool)
    assert "tenant-secret-id" not in p["detail"] and wf["workflow_id"] not in p["detail"] and wf["account_id"] not in p["detail"]


# ── timeout, concurrency, cache ────────────────────────────────────────────────────────────────────────────────────
PROBES = ["_database", "_data_api", "_redis", "_quote_feed", "_scheduler", "_last_cycle"]


def patch_probes(monkeypatch, *, delay=0.0, hang=(), counts=None):
    for name in PROBES:
        async def probe(self, *a, name=name, **k):
            if counts is not None:
                counts[name] = counts.get(name, 0) + 1
            await asyncio.sleep(60 if name in hang else delay)
            return hs._part(hs.OK, f"{name} fine", NOW)
        monkeypatch.setattr(hs._Monitor, name, probe)


def test_hs90_a_hung_probe_does_not_hold_up_the_answer(monkeypatch, clock):
    monkeypatch.setattr(hs, "PROBE_TIMEOUT_S", 0.3)
    for name in PROBES:
        patch_probes(monkeypatch, hang=(name,))
        t0 = time.monotonic()
        body = run(hs._Monitor().get(fake_state()))
        assert time.monotonic() - t0 < 1.0
        bad = body["parts"][name[1:]]
        assert bad["status"] != "OK" and "did not answer" in bad["detail"]
        assert all(p["status"] == "OK" for k, p in body["parts"].items() if k != name[1:])


def test_hs91_probes_run_together(monkeypatch, clock):
    monkeypatch.setattr(hs, "PROBE_TIMEOUT_S", 2.0)
    patch_probes(monkeypatch, delay=0.5)
    t0 = time.monotonic()
    run(hs._Monitor().get(fake_state()))
    assert time.monotonic() - t0 < 1.5          # six probes of 0.5 s one after another would take 3 s


def test_hs100_101_cache_for_15_seconds(monkeypatch, clock):
    counts = {}
    patch_probes(monkeypatch, counts=counts)
    m, st = hs._Monitor(), fake_state()
    a = run(m.get(st))
    clock.t += 14
    assert run(m.get(st)) is a and set(counts.values()) == {1}
    clock.t += 2
    monkeypatch.setattr(hs, "_utcnow", lambda: NOW + timedelta(seconds=16))
    b = run(m.get(st))
    assert b["as_of"] != a["as_of"] and set(counts.values()) == {2}


def test_hs102_ten_calls_share_one_set_of_probes(monkeypatch, clock):
    counts = {}
    patch_probes(monkeypatch, delay=0.2, counts=counts)
    m, st = hs._Monitor(), fake_state()

    async def many():
        return await asyncio.gather(*(m.get(st) for _ in range(10)))
    bodies = run(many())
    assert set(counts.values()) == {1} and all(b is bodies[0] for b in bodies)


# ── nothing private, wording ───────────────────────────────────────────────────────────────────────────────────────
def test_hs111_probe_errors_show_type_only(monkeypatch, clock):
    for name in PROBES:
        async def boom(self, *a, **k):
            raise RuntimeError(SECRET)
        monkeypatch.setattr(hs._Monitor, name, boom)
    body = run(hs._Monitor().get(fake_state()))
    text = json.dumps(body)
    assert SECRET not in text and all("RuntimeError" in p["detail"] for p in body["parts"].values())


def test_hs112_wording_has_no_advice_words(monkeypatch, clock):
    texts = []
    for name in SCENARIOS:
        sd, kw, _, thr = SCENARIOS[name]
        monkeypatch.setattr(ts, "MIN_CASH_ROWS", thr or 500)
        monkeypatch.setattr(ts, "MIN_FNO_UNDERLYINGS", thr or 50)
        texts.append(run(hs._Monitor._data_check(SimpleNamespace(market_factory=lambda at, kw=kw: SM(**kw),
                                                                 next_session=_const(sd)), NOW))["detail"])
    for open_, rows in ((True, {"NIFTY 50": tick(20)}), (True, {"NIFTY 50": tick(300)}), (True, {}), (True, None),
                        (False, None), (None, None)):
        texts.append(feed(monkeypatch, is_open=open_, rows=rows)[0]["detail"])
    texts += [hs._ago(s) for s in (5, 400, 9000, 400000)]
    src = inspect.getsource(hs)
    texts += re.findall(r'f?"([^"\n]{12,})"', src)
    bad = sorted({f"{m.group(0)!r} in {t!r}" for t in texts for m in ADVICE.finditer(t)})
    assert not bad, bad


# ── read only and what must not change ─────────────────────────────────────────────────────────────────────────────
def test_hs131_every_statement_is_a_select_in_a_read_only_transaction(monkeypatch, clock):
    pool = FakePool(row={"state": "COMPLETED", "session_date": PREV, "created_at": NOW})
    st = fake_state(pool)
    m = hs._Monitor()
    run(m._database(st, NOW))
    run(m._last_cycle(st, NOW))
    assert pool.sql and all(s.lstrip().upper().startswith("SELECT") for s in pool.sql)
    assert pool.readonly == [True]           # the cycle read runs in a read-only transaction


def test_hs132_no_broker_or_order_code():
    src = inspect.getsource(hs)
    assert not re.search(r"ReadOnlyKite|kiteconnect|place_order|modify_order|cancel_order|KiteQuoteSource|"
                         r"default_kite_factory|_platform_kite|autodesk\.execution\.gateway|from \.\.execution import gateway",
                         src)


def test_hs31_both_call_the_shared_check(monkeypatch):
    seen = []
    real = ts.data_checks

    async def spy(m, sd):
        seen.append(sd)
        return await real(m, sd)
    monkeypatch.setattr(ts, "data_checks", spy)
    run_agent("ready", monkeypatch)
    run(hs._Monitor._data_check(fake_state(), NOW))
    assert len(seen) == 2


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_hs30_tech_support_output_is_unchanged(name, monkeypatch):
    """Output, summary and the market calls equal the values the code before the change gave (golden from 82e5eedd)."""
    res, m = run_agent(name, monkeypatch)
    g = GOLDEN[name]
    assert res.output == g["result"]["output"]
    assert res.output_schema == g["result"]["output_schema"] and res.summary == g["result"]["summary"]
    assert [{k: c[k] for k in ("tool", "rows", "ok", "error")} | {"args": {"day": c["day"]}} for c in m.calls] == \
           [{k: c[k] for k in ("tool", "rows", "ok", "error")} | {"args": c["args"]} for c in g["calls"]]


# ── API ────────────────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def client(pg_pool, pg_dsn):
    pools = []

    async def factory():
        pool = await create_pool_for(pg_dsn)
        pools.append(pool)

        async def nxt(now):
            return date(2026, 11, 5)
        return build_state(pool, agents=stubs.agents(), market_factory=stubs.market_factory,
                           sessions_provider=stubs.sessions_provider, next_session=nxt, load_book=stubs.stub_load_book,
                           scope_builder=stubs.stub_scope)

    app = create_app(factory)

    async def no_user(request: Request):
        raise HTTPException(401, "Not authenticated")
    app.dependency_overrides[current_user] = no_user
    with TestClient(app) as c:
        yield c
        for t in c.app.state.desk.background.values():
            t.cancel()
        for p in pools:
            c.portal.call(p.close)


def test_hs01_02_answers_without_sign_in_with_every_part(client):
    client.app.state.health_monitor = None
    assert client.get("/api/v1/accounts").status_code == 401          # sign-in is faked to fail
    r = client.get("/api/v1/health/status")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    b = r.json()
    assert set(b) == {"status", "as_of", "parts"} and b["status"] in {"OK", "DEGRADED", "BLOCKED"}
    assert list(b["parts"]) == ["database", "data_api", "redis", "quote_feed", "scheduler", "last_cycle"]
    for p in b["parts"].values():
        assert p["status"] in {"OK", "DEGRADED", "BLOCKED"} and p["detail"].strip() and set(p) == {"status", "detail", "as_of"}
        assert p["as_of"] is None or datetime.fromisoformat(p["as_of"])
    assert b["parts"]["database"]["status"] == "OK"
    assert b["parts"]["scheduler"]["detail"].startswith("off")


def test_hs120_health_route_is_untouched_and_never_probes(client, monkeypatch):
    async def never(self, st):
        raise AssertionError("the status probes ran")
    monkeypatch.setattr(hs._Monitor, "get", never)
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert {"status", "app", "version", "db", "migrations", "agents", "calendar_years", "execution"} <= set(r.json())
    assert r.json()["status"] == "ok" and r.json()["db"] is True


def test_hs81_121_closed_pool(pg_dsn, pg_pool, monkeypatch):
    pools = []

    async def factory():
        pool = await create_pool_for(pg_dsn)
        pools.append(pool)

        async def nxt(now):
            return date(2026, 11, 5)
        return build_state(pool, agents=stubs.agents(), market_factory=stubs.market_factory,
                           sessions_provider=stubs.sessions_provider, next_session=nxt, load_book=stubs.stub_load_book,
                           scope_builder=stubs.stub_scope)
    monkeypatch.setattr(hs, "PROBE_TIMEOUT_S", 1.0)
    with TestClient(create_app(factory)) as c:
        c.portal.call(pools[0].close)
        t0 = time.monotonic()
        r = c.get("/api/v1/health/status")
        assert r.status_code == 200 and time.monotonic() - t0 < 5
        parts = r.json()["parts"]
        assert parts["database"]["status"] == "BLOCKED" and set(parts) == {"database", "data_api", "redis", "quote_feed",
                                                                          "scheduler", "last_cycle"}
        h = c.get("/api/v1/health")
        assert h.status_code == 503 and h.json()["status"] == "degraded" and h.json()["db"] is False
        for t in c.app.state.desk.background.values():
            t.cancel()


def test_hs130_calls_write_nothing(client, pg_pool):
    async def counts():
        async with pg_pool.acquire() as c:
            names = [r["tablename"] for r in await c.fetch("SELECT tablename FROM pg_tables WHERE schemaname='autodesk' ORDER BY 1")]
            return {n: await c.fetchval(f"SELECT count(*) FROM autodesk.{n}") for n in names}
    before = run(counts())
    for _ in range(3):
        client.app.state.health_monitor = None
        assert client.get("/api/v1/health/status").status_code == 200
    assert run(counts()) == before and len(before) > 10
