"""AD-HS-01..AD-HS-132: GET /api/v1/health/status (owner item R14). Test cases: docs/autodesk/testcases_health_status.md.

TEST DOUBLES throughout: a fake pool, a fake Redis client, fake feed-cache rows, crafted market data in a FrozenMarketView and a
fake Kite-login read. Nothing here is real market data or a real dependency; the real-boot run (AD-HS-140) is in the test report.
The clock is a patched `hs._utcnow` / `hs._mono`, so time-of-day rules are exact. Integration cases run on the throwaway Postgres
(AUTODESK_TEST_PG_URL) and are skipped without it.
"""
from __future__ import annotations

import ast
import asyncio
import collections
import json
import re
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient

from autodesk import APP_NAME, APP_VERSION
from autodesk import contracts as C
from autodesk.accounts import open_account
from autodesk.agents import tech_support
from autodesk.db import create_pool_for
from autodesk.main import build_state, create_app
from autodesk.market import calendar
from autodesk.market import live_quotes as lq
from autodesk.market.view import IST, DataUnavailable, FrozenMarketView
from autodesk.routers import health_status as hs
from autodesk.routers.api import current_user
from tests.autodesk import stubs
from tests.autodesk import test_ai_trader_ts as t
from tests.autodesk import ts_scenarios as ts
from tests.autodesk.conftest import run

SD = ts.SD                                                                      # 2026-11-06, a Friday: the session being prepared
NOW = datetime(2026, 11, 6, 11, 0, tzinfo=IST).astimezone(timezone.utc)         # Friday 11:00 IST: the market is open
PARTS = ["database", "data_api", "redis", "quote_feed", "scheduler", "last_cycle"]
SECRETS = ["secret-host.internal.example", "tok_SECRET_9f8e7d", "tenant-SECRET-77", "WF-SECRET-77", "SECRETSYM", "8443"]
BAD_WORDS = re.compile(r"\b(?:buy|sell|stop loss|SL|target|entry|exit|accumulate|book profit|upside|price target|recommend|pick)"
                       r"(?:s|es|ed|ing)?\b", re.I)


# ── doubles ─────────────────────────────────────────────────────────────────────────────────────────────────────────

class FakeTx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class FakeConn:
    def __init__(self, pool):
        self.pool = pool

    async def _go(self, sql):
        self.pool.log.append(sql)
        if any(m in sql for m in self.pool.hang_on):
            await asyncio.sleep(3600)

    async def fetchval(self, sql, *a):
        await self._go(sql)
        return 1

    async def fetchrow(self, sql, *a):
        await self._go(sql)
        return self.pool.row

    def transaction(self, readonly=False, **kw):
        self.pool.tx.append(readonly)
        return FakeTx()


class FakePool:
    def __init__(self):
        self.log: list[str] = []
        self.tx: list[bool] = []
        self.acquires = 0
        self.error: Exception | None = None
        self.hang_on: set[str] = set()
        self.row: dict | None = None             # what the last-cycle query returns

    def acquire(self):
        pool = self

        class Acq:
            async def __aenter__(self):
                pool.acquires += 1
                if pool.error is not None:
                    raise pool.error
                return FakeConn(pool)

            async def __aexit__(self, *a):
                return False
        return Acq()


class FakeRedis:
    def __init__(self, env):
        self.env = env

    async def ping(self):
        self.env.calls["ping"] += 1
        if self.env.redis == "ping_error":
            raise ConnectionError("redis://:tok_SECRET_9f8e7d@secret-host.internal.example:6379 refused")
        if self.env.redis == "ping_false":
            return False
        if self.env.redis == "ping_hang":
            await asyncio.sleep(3600)
        return True


def feed_row(sym: str, at: datetime) -> dict:
    return {"symbol": sym, "exchange": "NSE", "kind": "INDEX", "ltp": 24000.5,
            "received_at": at.astimezone(IST).isoformat(timespec="milliseconds")}


class Env:
    """A healthy desk at Friday 11:00 IST, with every dependency a double the test can break."""

    def __init__(self, mp):
        from services.kite_live_feed import platform_token, quote_cache
        self.mp, self.t, self.now = mp, 1000.0, NOW
        self.pool, self.calls = FakePool(), collections.Counter()
        self.pool.row = {"state": "COMPLETED", "session_date": date(2026, 11, 5), "created_at": NOW - timedelta(hours=26)}
        self.redis = "ok"                      # ok | none | error | ping_error | ping_false | ping_hang | hang
        self.rows: dict | str | None = {s: feed_row(s, NOW - timedelta(seconds=20)) for s in hs.FEED_INDEX_SYMBOLS}
        self.login: dict | Exception | str = {"stored": True, "expired": False, "valid_until": None}
        self.data = t.data()
        self.data_delay: float | None = None
        self.data_error: Exception | None = None
        self.session = SD
        self.make_view = lambda as_of: self._view(as_of)
        self.st = SimpleNamespace(pool=self.pool, background={}, next_session=self._next_session,
                                  market_factory=lambda as_of: self.make_view(as_of))
        self.mon = hs._Monitor()
        env = self

        class View(FrozenMarketView):
            async def day_snapshot(self, day):
                if env.data_error is not None:
                    raise env.data_error
                if env.data_delay is not None:
                    await asyncio.sleep(env.data_delay)
                return await super().day_snapshot(day)
        self._View = View

        mp.setattr(hs, "_utcnow", lambda: self.now)
        mp.setattr(hs, "_mono", lambda: self.t)
        mp.setattr(tech_support, "MIN_CASH_ROWS", 2)
        mp.setattr(tech_support, "MIN_FNO_UNDERLYINGS", 2)
        mp.setattr(calendar, "_HOLIDAYS", {2026: {}})
        mp.setenv("AUTODESK_SCHEDULER", "0")
        orig = tech_support.data_checks

        async def spy(m, sd):
            env.calls["data_checks"] += 1
            return await orig(m, sd)
        mp.setattr(tech_support, "data_checks", spy)

        async def get_client():
            env.calls["redis_client"] += 1
            if env.redis == "none":
                return None
            if env.redis == "error":
                raise ConnectionError("redis://:tok_SECRET_9f8e7d@secret-host.internal.example:6379 refused")
            if env.redis == "hang":
                await asyncio.sleep(3600)
            return FakeRedis(env)

        async def read_quotes(symbols):
            env.calls["read_quotes"] += 1
            if env.rows == "hang":
                await asyncio.sleep(3600)
            if isinstance(env.rows, Exception):
                raise env.rows
            return env.rows

        async def token_status(db, now=None):
            env.calls["login"] += 1
            if env.login == "hang":
                await asyncio.sleep(3600)
            if isinstance(env.login, Exception):
                raise env.login
            return env.login
        mp.setattr(quote_cache, "get_client", get_client)
        mp.setattr(quote_cache, "read_quotes", read_quotes)
        mp.setattr(platform_token, "token_status", token_status)

    def _view(self, as_of):
        return self._View(as_of, self.data)

    async def _next_session(self, now):
        return self.session

    def get(self) -> dict:
        return run(self.mon.get(self.st))

    def fresh(self) -> dict:
        self.mon = hs._Monitor()
        return self.get()

    def advance(self, seconds: float) -> None:
        self.t += seconds
        self.now += timedelta(seconds=seconds)

    def fast(self, timeout=0.4, wait=0.25) -> None:
        self.mp.setattr(hs, "PROBE_TIMEOUT_S", timeout)
        self.mp.setattr(hs, "DATA_WAIT_S", wait)

    def at(self, *args) -> None:
        self.now = datetime(*args, tzinfo=IST).astimezone(timezone.utc)


@pytest.fixture
def env(monkeypatch):
    return Env(monkeypatch)


def part(body: dict, name: str) -> dict:
    return body["parts"][name]


def texts(body: dict) -> str:
    return json.dumps(body)


# ── shape, worst part (AD-HS-01, 80) ────────────────────────────────────────────────────────────────────────────────

def test_hs01_shape(env):
    b = env.get()
    assert set(b) == {"status", "as_of", "parts"} and list(b["parts"]) == PARTS
    datetime.fromisoformat(b["as_of"])
    for name, p in b["parts"].items():
        assert set(p) == {"status", "detail", "as_of"}, name
        assert p["status"] in ("OK", "DEGRADED", "BLOCKED") and isinstance(p["detail"], str) and p["detail"], name
        assert p["as_of"] is None or datetime.fromisoformat(p["as_of"])
    assert [part(b, n)["status"] for n in ("database", "data_api", "redis", "quote_feed", "last_cycle")] == ["OK"] * 5
    assert b["status"] == "DEGRADED"                        # the scheduler is off: see AD-HS-60


def test_hs80_worst_part_wins(env):
    ok = lambda s: {"status": s}                                                       # noqa: E731
    assert hs.worst({"a": ok("OK"), "b": ok("OK")}) == "OK"
    assert hs.worst({"a": ok("OK"), "b": ok("DEGRADED")}) == "DEGRADED"
    assert hs.worst({"a": ok("DEGRADED"), "b": ok("BLOCKED"), "c": ok("OK")}) == "BLOCKED"

    async def sched_ok(self):
        return hs._part(hs.OK, "The scheduler runs.", None)
    env.mp.setattr(hs._Monitor, "_scheduler", sched_ok)
    assert env.fresh()["status"] == "OK"                                              # all six parts OK
    env.redis = "none"
    assert env.fresh()["status"] == "DEGRADED"
    env.pool.error = RuntimeError("x")
    b = env.fresh()
    assert b["status"] == "BLOCKED" and part(b, "database")["status"] == "BLOCKED" and part(b, "redis")["status"] == "DEGRADED"


# ── database (10..12) ───────────────────────────────────────────────────────────────────────────────────────────────

def test_hs10_database_ok(env):
    p = part(env.get(), "database")
    assert p["status"] == "OK" and p["detail"] == "The desk database answers." and p["as_of"] == NOW.isoformat()


def test_hs11_database_error(env):
    env.pool.error = ConnectionRefusedError("postgresql://u:p@secret-host.internal.example:5432/desk refused")
    p = part(env.get(), "database")
    assert p["status"] == "BLOCKED" and "ConnectionRefusedError" in p["detail"]
    assert "secret-host" not in p["detail"] and "5432" not in p["detail"]


def test_hs12_database_hangs(env):
    env.fast()
    env.pool.hang_on = {"SELECT 1"}
    t0 = time.monotonic()
    b = env.get()
    assert time.monotonic() - t0 < 1.2
    assert part(b, "database")["status"] == "BLOCKED" and "did not answer within 0.4 seconds" in part(b, "database")["detail"]
    assert part(b, "redis")["status"] == "OK" and part(b, "last_cycle")["status"] == "OK"     # the rest is still reported


# ── data_api (20..28) ───────────────────────────────────────────────────────────────────────────────────────────────

def test_hs20_data_api_ok(env):
    p = part(env.get(), "data_api")
    assert p["status"] == "OK"
    assert p["detail"] == ("For the 2026-11-06 session: 6 cash rows for 2026-11-05 (need 2); "
                           "6 F&O underlyings for 2026-11-05 (need 2); India VIX 13.5.")
    assert p["as_of"] == NOW.isoformat() and env.calls["data_checks"] == 1


def test_hs21_fno_stale_or_few_is_degraded(env):
    env.data = t.data(fno={})
    p = part(env.get(), "data_api")
    assert p["status"] == "DEGRADED" and "0 F&O underlyings for 2026-11-05 (need 2)" in p["detail"]
    assert "6 cash rows for 2026-11-05" in p["detail"]
    env2 = t.data()
    env2["fno"] = {k: ts.on_day(v, date(2026, 11, 4)) for k, v in env2["fno"].items()}
    env.data = env2
    env.now = ts.at(ts.D, "20:00")                                                     # F&O is two sessions old
    p = part(env.fresh(), "data_api")
    assert p["status"] == "DEGRADED" and "F&O data is for 2026-11-04; the 2026-11-06 session needs 2026-11-05" in p["detail"]


def test_hs22_vix_missing_is_noted_not_blocking(env):
    env.data = t.data(vix={})
    p = part(env.get(), "data_api")
    assert p["status"] == "OK" and "no India VIX for the session" in p["detail"]


def test_hs23_cash_stale_or_few_is_blocked(env):
    env.now = ts.at(ts.D, "18:50")                                                     # cash for 5 Nov is not published yet
    p = part(env.get(), "data_api")
    assert p["status"] == "BLOCKED" and "Cash data is for 2026-11-04; the 2026-11-06 session needs 2026-11-05" in p["detail"]
    env.now = NOW
    env.mp.setattr(tech_support, "MIN_CASH_ROWS", 500)
    p = part(env.fresh(), "data_api")
    assert p["status"] == "BLOCKED" and "6 cash rows for 2026-11-05 (need 500)" in p["detail"]


def test_hs24_unreadable_data_api_shows_no_host(env):
    env.make_view = lambda as_of: ts.UnreadableView(as_of, t.data())
    p = part(env.get(), "data_api")
    assert p["status"] == "BLOCKED"
    assert "cash end-of-day data could not be read" in p["detail"] and "India VIX could not be read" in p["detail"]
    for bad in ("example-internal", "8443", "https", "refused"):
        assert bad not in p["detail"], bad


def _agent_status(s) -> str:
    result, _ = ts.run_agent(s)
    return result["output"]["status"]


def test_hs25_route_and_pre_market_check_agree(env):
    """The same market inputs through TechSupport.run and through the route give the same verdict (READY = OK)."""
    seen = set()
    for s in ts.scenarios():
        if not s.db_ok:
            continue
        agent = _agent_status(s)
        assert agent == s.expect, s.name
        env.mp.setattr(tech_support, "MIN_CASH_ROWS", s.min_cash)
        env.mp.setattr(tech_support, "MIN_FNO_UNDERLYINGS", s.min_fno)
        env.make_view, env.session = (lambda as_of, s=s: s.make()), s.session
        env.now = datetime(2026, 11, 6, 11, 0, tzinfo=IST).astimezone(timezone.utc)
        got = part(env.fresh(), "data_api")["status"]
        assert got == {"READY": "OK", "DEGRADED": "DEGRADED", "BLOCKED": "BLOCKED"}[agent], (s.name, agent, got)
        seen.add(agent)
        env.st.background.clear()
        env.mon = hs._Monitor()
    assert seen == {"READY", "DEGRADED", "BLOCKED"}


def test_hs26_slow_data_check_runs_in_the_background(env):
    env.fast(timeout=0.4, wait=0.2)
    env.data_delay = 0.7
    t0 = time.monotonic()
    b = env.get()
    assert time.monotonic() - t0 < 0.9                                               # never waits for the slow check
    p = part(b, "data_api")
    assert p["status"] == "DEGRADED" and p["detail"] == "The first data check is still running; ask again in a few seconds."
    assert p["as_of"] is None
    run(asyncio.sleep(0.9))                                                          # the background run finishes
    env.advance(hs.CACHE_TTL_S + 1)
    p = part(env.get(), "data_api")
    assert p["status"] == "OK" and p["detail"].startswith("For the 2026-11-06 session: 6 cash rows")
    assert p["as_of"] == NOW.isoformat()                                             # the time the check ran, not now
    assert env.calls["data_checks"] == 1                                             # not started again inside DATA_REFRESH_S


def test_hs27_old_result_is_not_reported_as_current(env):
    env.fast(timeout=0.4, wait=0.2)
    assert part(env.get(), "data_api")["status"] == "OK"
    env.data_delay = 3600                                                            # the data API stops answering
    env.advance(400)                                                                 # past DATA_REFRESH_S and DATA_MAX_AGE_S
    p = part(env.get(), "data_api")
    assert p["status"] == "DEGRADED" and "7 minutes old" in p["detail"] and "has not finished" in p["detail"]
    assert p["as_of"] == NOW.isoformat()
    env.st.background[hs.BACKGROUND_KEY].cancel()


def test_hs28_data_check_that_never_finishes_is_blocked(env):
    env.fast(timeout=0.4, wait=0.15)
    env.mp.setattr(hs, "DATA_RUN_DEADLINE_S", 0.3)
    env.data_delay = 3600
    assert part(env.get(), "data_api")["status"] == "DEGRADED"
    run(asyncio.sleep(0.4))
    env.advance(hs.CACHE_TTL_S + 1)
    p = part(env.get(), "data_api")
    assert p["status"] == "BLOCKED" and p["detail"] == "The data check did not finish within 0.3 seconds."


def test_hs29_after_the_close_the_route_says_what_the_pre_market_check_would(env):
    """Friday 16:00 IST: the session being prepared is Monday, which needs Friday's end-of-day file, and that is published at
    19:30 IST. The pre-market check run now would say BLOCKED, so the route does too (it never disagrees with the check)."""
    fri, mon = date(2026, 11, 6), date(2026, 11, 9)
    sess = t.data()["sessions"] + [mon]
    env.data, env.session = t.data(sessions=sess), mon
    env.at(2026, 11, 6, 16, 0)
    p = part(env.get(), "data_api")
    s = ts.Scenario("after_close", lambda: FrozenMarketView(ts.at(fri, "16:00"), t.data(sessions=sess)), session=mon)
    agent = ts.run_agent(s)[0]["output"]
    cash = next(c for c in agent["checks"] if c["name"] == "cash_eod")
    assert agent["status"] == "BLOCKED" and p["status"] == "BLOCKED"
    assert cash["detail"] == "Cash data is for 2026-11-05; the 2026-11-09 session needs 2026-11-06"
    assert cash["detail"] in p["detail"]


# ── redis (40..43) ──────────────────────────────────────────────────────────────────────────────────────────────────

def test_hs40_redis_ok(env):
    p = part(env.get(), "redis")
    assert p["status"] == "OK" and p["detail"] == "Redis answers." and env.calls["ping"] == 1


@pytest.mark.parametrize("mode", ["none", "error", "ping_error", "ping_false"])
def test_hs41_42_redis_down_is_degraded(env, mode):
    env.redis = mode
    p = part(env.get(), "redis")
    assert p["status"] == "DEGRADED"
    assert "secret-host" not in p["detail"] and "tok_SECRET" not in p["detail"]
    if mode.endswith("error"):
        assert "ConnectionError" in p["detail"]


@pytest.mark.parametrize("mode", ["hang", "ping_hang"])
def test_hs43_redis_hangs(env, mode):
    env.fast()
    env.redis = mode
    t0 = time.monotonic()
    p = part(env.get(), "redis")
    assert time.monotonic() - t0 < 1.2 and p["status"] == "DEGRADED" and "did not answer within 0.4 seconds" in p["detail"]


# ── quote_feed (50..57) ─────────────────────────────────────────────────────────────────────────────────────────────

def test_hs50_fresh_tick_in_market_hours(env):
    p = part(env.get(), "quote_feed")
    assert p["status"] == "OK" and p["detail"].startswith("The market is open and the newest index tick is 20 seconds old")
    assert p["detail"].endswith("a Kite login is stored and has not expired.")
    assert p["as_of"] == (NOW - timedelta(seconds=20)).isoformat()


def test_hs51_old_tick_is_degraded(env):
    env.rows = {s: feed_row(s, NOW - timedelta(seconds=300)) for s in hs.FEED_INDEX_SYMBOLS}
    p = part(env.get(), "quote_feed")
    assert p["status"] == "DEGRADED" and "300 seconds old (limit 120 seconds)" in p["detail"]
    env.rows = {s: feed_row(s, NOW - timedelta(days=1)) for s in hs.FEED_INDEX_SYMBOLS}
    p = part(env.fresh(), "quote_feed")
    assert p["status"] == "DEGRADED" and "not from today" in p["detail"]


def test_hs52_no_index_rows_is_degraded(env):
    env.rows = {}
    p = part(env.get(), "quote_feed")
    assert p["status"] == "DEGRADED" and "holds no index ticks" in p["detail"]


def test_hs53_cache_unavailable_is_degraded(env):
    env.rows = None
    p = part(env.get(), "quote_feed")
    assert p["status"] == "DEGRADED" and "quote cache is not available" in p["detail"]


@pytest.mark.parametrize("when", [(2026, 11, 6, 16, 0), (2026, 11, 7, 11, 0), (2026, 11, 6, 8, 0)])
def test_hs54_market_closed_is_ok_without_reading_the_cache(env, when):
    env.at(*when)                                                     # evening, Saturday, before the open
    env.rows = None
    p = part(env.get(), "quote_feed")
    assert p["status"] == "OK" and "The market is closed" in p["detail"] and env.calls["read_quotes"] == 0


def test_hs54_holiday(env):
    env.mp.setattr(calendar, "_HOLIDAYS", {2026: {date(2026, 11, 6): "test holiday"}})
    p = part(env.get(), "quote_feed")
    assert p["status"] == "OK" and "The market is closed" in p["detail"] and env.calls["read_quotes"] == 0


def test_hs55_unknown_calendar_and_the_desks_own_function(env):
    env.mp.setattr(calendar, "_HOLIDAYS", {})                          # no holiday list on a weekday
    p = part(env.get(), "quote_feed")
    assert p["status"] == "DEGRADED" and "Cannot tell whether the market is open" in p["detail"]
    from autodesk.execution import settle
    asked = []
    env.mp.setattr(calendar, "_HOLIDAYS", {2026: {}})
    env.mp.setattr(settle, "_market_open", lambda now: asked.append(now) or False)
    p = part(env.fresh(), "quote_feed")
    assert asked == [NOW] and "The market is closed" in p["detail"]       # the route follows the desk's own function
    assert "def _market_open" not in Path(hs.__file__).read_text() and "time(9, 15)" not in Path(hs.__file__).read_text()


@pytest.mark.parametrize("login,phrase", [
    ({"stored": True, "expired": False}, "a Kite login is stored and has not expired"),
    ({"stored": False, "expired": False}, "no unexpired Kite login is stored"),
    ({"stored": True, "expired": True}, "no unexpired Kite login is stored"),
    (RuntimeError("mongodb://u:tok_SECRET_9f8e7d@secret-host.internal.example:27017"), "could not be read (RuntimeError)")])
def test_hs56_kite_login_sentence(env, login, phrase):
    env.login = login
    p = part(env.get(), "quote_feed")
    assert p["status"] == "OK" and phrase in p["detail"] and "secret-host" not in p["detail"]


def test_hs56_a_hanging_mongo_does_not_delay_the_answer(env):
    env.mp.setattr(hs, "LOGIN_READ_S", 0.2)
    env.at(2026, 11, 6, 16, 0)
    env.login = "hang"
    t0 = time.monotonic()
    p = part(env.get(), "quote_feed")
    assert time.monotonic() - t0 < 1.0 and p["status"] == "OK" and "could not be read in time" in p["detail"]


def test_hs57_no_kite_call_of_any_kind(env):
    from services.kite_live_feed import gateway
    boom = []

    async def spy_async(*a, **k):
        boom.append("async")
        raise AssertionError("a Kite path was used")

    def spy(*a, **k):
        boom.append("sync")
        raise AssertionError("a Kite path was used")
    env.mp.setattr(lq, "_platform_kite", spy_async)
    env.mp.setattr(lq.KiteQuoteSource, "quotes", spy_async)
    env.mp.setattr(lq.KiteQuoteSource, "__init__", spy)
    env.mp.setattr(gateway, "default_kite_factory", spy)
    try:
        import kiteconnect
        env.mp.setattr(kiteconnect, "KiteConnect", spy)
    except ImportError:
        pass
    for rows in ({s: feed_row(s, NOW - timedelta(seconds=5)) for s in hs.FEED_INDEX_SYMBOLS}, {}, None):
        env.rows = rows
        env.fresh()
    env.at(2026, 11, 6, 16, 0)
    env.fresh()
    assert boom == []


# ── scheduler (60, 61) ──────────────────────────────────────────────────────────────────────────────────────────────

def test_hs60_scheduler_off(env, monkeypatch):
    for value in (None, "0", "false"):
        if value is None:
            monkeypatch.delenv("AUTODESK_SCHEDULER", raising=False)
        else:
            monkeypatch.setenv("AUTODESK_SCHEDULER", value)
        p = part(env.fresh(), "scheduler")
        assert p["status"] == "DEGRADED" and p["detail"] == "off: session cycles are started by hand" and p["as_of"] is None


def test_hs61_scheduler_on_proves_nothing(env, monkeypatch):
    monkeypatch.setenv("AUTODESK_SCHEDULER", "1")
    p = part(env.get(), "scheduler")
    assert p["status"] == "DEGRADED" and "no scheduler that starts session cycles" in p["detail"]


# ── last_cycle on the fake pool (76) ────────────────────────────────────────────────────────────────────────────────

def test_hs76_calendar_cannot_name_the_previous_session(env):
    env.make_view = lambda as_of: ts.NoCalendarView(as_of, t.data())
    p = part(env.get(), "last_cycle")
    assert p["status"] == "DEGRADED" and "could not be worked out" in p["detail"]
    env.pool.row = {"state": "FAILED", "session_date": date(2026, 11, 5), "created_at": NOW - timedelta(hours=2)}
    assert part(env.fresh(), "last_cycle")["status"] == "BLOCKED"                  # a failed cycle needs no calendar


def test_hs70_no_rows_on_the_fake_pool(env):
    env.pool.row = None
    p = part(env.get(), "last_cycle")
    assert p["status"] == "DEGRADED" and p["detail"] == "No session cycle has been recorded yet."


# ── timeouts, concurrency, cache (90..102) ──────────────────────────────────────────────────────────────────────────

def test_hs90_each_probe_hangs_in_turn(env):
    env.fast()
    cases = {"database": lambda: setattr(env.pool, "hang_on", {"SELECT 1"}),
             "redis": lambda: setattr(env, "redis", "hang"),
             "quote_feed": lambda: setattr(env, "rows", "hang"),
             "last_cycle": lambda: setattr(env.pool, "hang_on", {"workflows"}),
             "data_api": lambda: setattr(env, "data_delay", 3600)}
    for name, hang in cases.items():
        env.redis, env.rows, env.data_delay = "ok", {s: feed_row(s, NOW - timedelta(seconds=20)) for s in hs.FEED_INDEX_SYMBOLS}, None
        env.pool.hang_on = set()
        env.st.background.clear()
        hang()
        t0 = time.monotonic()
        b = env.fresh()
        assert time.monotonic() - t0 < 1.2, name
        assert part(b, name)["status"] != "OK", name
        assert ("did not answer" in part(b, name)["detail"] or "still running" in part(b, name)["detail"]), name
        others = [n for n in ("database", "redis", "quote_feed", "last_cycle") if n != name]
        assert all(part(b, n)["status"] == "OK" for n in others), (name, {n: part(b, n) for n in others})
        for task in env.st.background.values():
            task.cancel()


def test_hs91_probes_run_together(env):
    for name in ("_database", "_redis", "_scheduler"):
        async def slow(self, *a, _n=name):
            await asyncio.sleep(0.5)
            return hs._part(hs.OK, "slow", None)
        env.mp.setattr(hs._Monitor, name, slow)

    async def slow_two(self, *a):
        await asyncio.sleep(0.5)
        return hs._part(hs.OK, "slow", None)
    env.mp.setattr(hs._Monitor, "_quote_feed", slow_two)
    env.mp.setattr(hs._Monitor, "_last_cycle", slow_two)
    t0 = time.monotonic()
    env.get()
    assert time.monotonic() - t0 < 1.3                                             # five 0.5 s probes: 2.5 s if one after another


def test_hs100_second_call_makes_no_new_probe(env):
    first = env.get()
    snapshot = (env.pool.acquires, dict(env.calls))
    assert env.pool.acquires == 2 and env.calls["ping"] == 1 and env.calls["read_quotes"] == 1 and env.calls["data_checks"] == 1
    env.advance(14)
    second = env.get()
    assert second == first and second["as_of"] == first["as_of"]
    assert (env.pool.acquires, dict(env.calls)) == snapshot


def test_hs101_after_the_ttl_the_probes_run_again(env):
    first = env.get()
    env.advance(16)
    second = env.get()
    assert env.pool.acquires == 4 and env.calls["ping"] == 2 and second["as_of"] != first["as_of"]
    assert env.calls["data_checks"] == 1                 # the data check has its own, longer refresh (DATA_REFRESH_S)
    env.advance(hs.DATA_REFRESH_S)
    env.get()
    assert env.calls["data_checks"] == 2


def test_hs102_ten_callers_share_one_set_of_probes(env):
    async def many():
        return await asyncio.gather(*(env.mon.get(env.st) for _ in range(10)))
    out = run(many())
    assert all(o == out[0] for o in out)
    assert env.pool.acquires == 2 and env.calls["ping"] == 1 and env.calls["data_checks"] == 1


# ── nothing private, wording (110..112) ─────────────────────────────────────────────────────────────────────────────

def _scan(body: dict) -> None:
    s = texts(body)
    for secret in SECRETS:
        assert secret not in s, secret
    assert "://" not in s and "localhost" not in s.lower() and not re.search(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", s)
    assert not re.search(r"\.(?:internal|example|test|local)\b", s)


def test_hs110_nothing_private_when_everything_fails(env, monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://:tok_SECRET_9f8e7d@secret-host.internal.example:6379/0")
    monkeypatch.setenv("AUTODESK_PG_URL", "postgresql://u:tok_SECRET_9f8e7d@secret-host.internal.example:5432/tenant-SECRET-77")
    env.pool.error = ConnectionRefusedError("postgresql://u:tok_SECRET_9f8e7d@secret-host.internal.example:5432 refused")
    env.redis = "error"
    env.make_view = lambda as_of: ts.UnreadableView(as_of, t.data())
    env.rows = {"SECRETSYM": feed_row("SECRETSYM", NOW - timedelta(seconds=5))}
    env.login = RuntimeError("mongodb://u:tok_SECRET_9f8e7d@secret-host.internal.example:27017 tenant-SECRET-77")
    b = env.get()
    _scan(b)
    assert part(b, "database")["status"] == "BLOCKED" and part(b, "data_api")["status"] == "BLOCKED"


def test_hs110_nothing_private_when_everything_works(env):
    env.rows = {"NIFTY 50": feed_row("NIFTY 50", NOW - timedelta(seconds=5)), "SECRETSYM": feed_row("SECRETSYM", NOW)}
    env.pool.row = {"state": "COMPLETED", "session_date": date(2026, 11, 5), "created_at": NOW - timedelta(hours=26),
                    "tenant_id": "tenant-SECRET-77", "workflow_id": "WF-SECRET-77", "account_id": "ACC-SECRET-77"}
    env.login = {"stored": True, "expired": False, "token": "tok_SECRET_9f8e7d", "user_id": "tenant-SECRET-77"}
    _scan(env.get())


def test_hs111_exception_messages_never_shown(env):
    secret = RuntimeError("tenant-SECRET-77 tok_SECRET_9f8e7d https://secret-host.internal.example:8443/x")
    env.pool.error = secret
    env.redis = "error"
    env.rows = secret
    env.data_error = secret
    env.mp.setattr(hs.cfgmod, "load", lambda: (_ for _ in ()).throw(secret))
    b = env.get()
    _scan(b)
    for name in PARTS:
        assert "RuntimeError" in part(b, name)["detail"] or "ConnectionError" in part(b, name)["detail"], (name, part(b, name))


def test_hs112_wording(env, monkeypatch):
    seen: list[str] = []

    def take(b):
        seen.extend(p["detail"] for p in b["parts"].values())

    take(env.get())
    for mutate in (lambda: setattr(env, "redis", "none"), lambda: setattr(env, "rows", {}),
                   lambda: setattr(env, "rows", None), lambda: setattr(env, "login", {"stored": False}),
                   lambda: setattr(env.pool, "row", None),
                   lambda: setattr(env.pool, "row", {"state": "BLOCKED", "session_date": date(2026, 11, 5), "created_at": NOW}),
                   lambda: setattr(env.pool, "row", {"state": "CANCELLED", "session_date": date(2026, 11, 5), "created_at": NOW}),
                   lambda: setattr(env.pool, "row", {"state": "COMPLETED", "session_date": date(2026, 11, 3), "created_at": NOW}),
                   lambda: setattr(env, "data", t.data(fno={}, vix={})),
                   lambda: env.mp.setattr(tech_support, "MIN_CASH_ROWS", 500),
                   lambda: setattr(env, "make_view", lambda as_of: ts.UnreadableView(as_of, t.data())),
                   lambda: setattr(env.pool, "error", ConnectionError("x")),
                   lambda: monkeypatch.setenv("AUTODESK_SCHEDULER", "1"),
                   lambda: env.at(2026, 11, 6, 16, 0), lambda: env.mp.setattr(calendar, "_HOLIDAYS", {})):
        mutate()
        env.st.background.clear()
        take(env.fresh())
    assert len(seen) == 6 * 16
    for text in seen:
        assert not BAD_WORDS.search(text), text


# ── the source: read only, no Kite, no broker (132) ─────────────────────────────────────────────────────────────────

def test_hs132_source_imports_no_broker_or_order_path():
    tree = ast.parse(Path(hs.__file__).read_text())
    names, modules = set(), set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom):
            modules.add(("." * n.level) + (n.module or ""))
            names.update(a.name for a in n.names)
        elif isinstance(n, ast.Import):
            modules.update(a.name for a in n.names)
    assert not names & {"KiteQuoteSource", "_platform_kite", "default_kite_factory", "KiteConnect", "ReadOnlyKite",
                        "ExecutionGateway", "LivePaperAdapter", "orders", "gateway", "broker_hub"}
    assert not [m for m in modules if "broker" in m or "kiteconnect" in m or m.endswith("execution.orders")]


def test_hs131_only_reads_on_the_fake_pool(env):
    env.get()
    assert env.pool.log and all(s.lstrip().upper().startswith("SELECT") for s in env.pool.log), env.pool.log
    assert env.pool.tx == [True]                                                     # the one multi-line query: a read-only transaction
    assert not re.search(r"\b(?:INSERT|UPDATE|DELETE|CREATE|DROP|ALTER|TRUNCATE)\b", " ".join(env.pool.log), re.I)


# ── Tech Support unchanged (30, 31) ─────────────────────────────────────────────────────────────────────────────────

GOLDEN = json.loads((Path(__file__).parent / "golden_tech_support.json").read_text())


@pytest.mark.parametrize("name", [s.name for s in ts.scenarios()])
def test_hs30_tech_support_output_is_byte_for_byte_unchanged(name):
    s = next(x for x in ts.scenarios() if x.name == name)
    assert json.dumps(ts.fingerprint(s), sort_keys=True) == json.dumps(GOLDEN[name], sort_keys=True)


def test_hs30_the_golden_covers_every_scenario():
    assert sorted(GOLDEN) == sorted(s.name for s in ts.scenarios()) and len(GOLDEN) >= 8


def test_hs31_agent_and_route_call_the_same_function(env):
    ts.run_agent(ts.scenarios()[0])
    assert env.calls["data_checks"] == 1
    env.get()
    assert env.calls["data_checks"] == 2
    assert hs.tech_support.data_checks is tech_support.data_checks


# ── API level, on the throwaway Postgres (01, 02, 81, 120, 121, and last_cycle / read-only on real rows) ───────────────

USERS = {"a": {"user_id": "api-a", "role": "user"}}


@pytest.fixture(scope="module")
def client(pg_pool, pg_dsn):
    pools = []
    mp = pytest.MonkeyPatch()
    from services.kite_live_feed import platform_token

    async def token_status(db, now=None):               # no Mongo in the tests
        return {"stored": False, "expired": False}
    mp.setattr(platform_token, "token_status", token_status)

    async def factory():
        pool = await create_pool_for(pg_dsn)
        pools.append(pool)

        async def next_session(now):
            return date(2026, 11, 5)
        st = build_state(pool, agents=stubs.agents(), market_factory=stubs.market_factory,
                         sessions_provider=stubs.sessions_provider, next_session=next_session,
                         load_book=stubs.stub_load_book, scope_builder=stubs.stub_scope)
        await st.orchestrator.register_agents()
        return st

    app = create_app(factory)

    async def fake_user(request: Request):
        who = request.headers.get("X-Test-User")
        if who not in USERS:
            raise HTTPException(401, "Not authenticated")
        return USERS[who]
    app.dependency_overrides[current_user] = fake_user
    with TestClient(app) as c:
        yield c
        for p in pools:
            c.portal.call(p.close)
    mp.undo()


def test_hs01_over_http_without_sign_in(client):
    client.app.state.health_monitor = None
    r = client.get("/api/v1/health/status")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/json")
    assert r.headers["cache-control"] == "no-store"
    b = r.json()
    assert set(b) == {"status", "as_of", "parts"} and list(b["parts"]) == PARTS
    assert b["parts"]["database"]["status"] == "OK"
    assert b["status"] in ("OK", "DEGRADED", "BLOCKED")
    for secret in ("postgresql", "mongodb", "password"):
        assert secret not in r.text.lower()


def test_hs02_does_not_ask_for_sign_in(client):
    assert client.get("/api/v1/accounts").status_code == 401                         # the same app refuses an unsigned call here
    assert client.get("/api/v1/health/status", headers={"Authorization": "Bearer nonsense"}).status_code == 200
    assert client.get("/api/v1/health/status", headers={"Cookie": "session_token=nonsense"}).status_code == 200


def test_hs120_health_route_is_unchanged_and_independent(client):
    client.app.state.health_monitor = None
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    b = r.json()
    assert set(b) == {"status", "app", "version", "db", "migrations", "agents", "calendar_years", "execution"}
    assert b["status"] == "ok" and b["app"] == APP_NAME and b["version"] == APP_VERSION and b["db"] is True
    assert b["migrations"] == sorted(b["migrations"]) and "001_autodesk_core.sql" in b["migrations"]
    assert b["execution"] == "none (Phase 1: no orders, fills or positions)"
    assert client.app.state.health_monitor is None                                    # it never touched the status route's probes


def test_hs121_health_503_with_the_database_down_and_status_still_answers(pg_dsn, client):
    pools = []

    async def factory():
        pool = await create_pool_for(pg_dsn)
        await pool.close()
        pools.append(pool)

        async def ns(now):
            return date(2026, 11, 5)
        return build_state(pool, agents=stubs.agents(), market_factory=stubs.market_factory,
                           sessions_provider=stubs.sessions_provider, next_session=ns)
    app = create_app(factory)
    with TestClient(app) as c:
        h = c.get("/api/v1/health")
        assert h.status_code == 503 and h.json()["status"] == "degraded" and h.json()["db"] is False
        t0 = time.monotonic()
        r = c.get("/api/v1/health/status")                                            # AD-HS-81
        assert r.status_code == 200 and time.monotonic() - t0 < hs.PROBE_TIMEOUT_S + 1.5
        b = r.json()
        assert b["status"] == "BLOCKED" and b["parts"]["database"]["status"] == "BLOCKED"
        assert set(b["parts"]) == set(PARTS) and b["parts"]["scheduler"]["status"] == "DEGRADED"
        assert b["parts"]["last_cycle"]["status"] == "DEGRADED"


def test_hs81_desk_state_missing_still_answers():
    async def nothing():
        return None
    app = create_app(nothing)                           # lifespan sets app.state.desk to None
    with TestClient(app) as c:
        r = c.get("/api/v1/health/status")
        assert r.status_code == 200
        b = r.json()
        assert b["status"] == "BLOCKED" and "AttributeError" in b["parts"]["database"]["detail"]


# ── last_cycle on real rows (70..75, 77) and the read-only proof (130) ─────────────────────────────────────────────

_ACCOUNTS: dict[str, str] = {}


async def _seed(pool, rows: list[dict]) -> dict:
    """Replace the workflows with `rows` (TEST DATA). Each: tenant, kind, state, sd, hours (age), sim (bool), wid."""
    async with pool.acquire() as c:
        await c.execute("DELETE FROM autodesk.workflows")
        await c.execute("DELETE FROM autodesk.simulations")
        for r in rows:
            tenant = r.get("tenant", "tenant-one")
            if tenant not in _ACCOUNTS:
                acc = await open_account(c, tenant_id=tenant, name="desk", kind=C.AccountKind.PAPER,
                                         mode=C.OperatingMode.AUTONOMOUS_PAPER, capital=Decimal("1000000"), created_by="t")
                _ACCOUNTS[tenant] = acc["account_id"]
            sim = None
            if r.get("sim"):
                sim = "SIM-" + C.new_id("X")
                await c.execute("""INSERT INTO autodesk.simulations (simulation_id, tenant_id, name, mode, status, config, created_by)
                                   VALUES ($1,$2,'t','SCENARIO','CREATED',$3,'t')""", sim, tenant, {})
            created = NOW - timedelta(hours=r.get("hours", 26))
            await c.execute("""INSERT INTO autodesk.workflows (workflow_id, tenant_id, account_id, simulation_id, kind, state,
                                   correlation_id, session_date, created_at, updated_at)
                               VALUES ($1,$2,$3,$4,$5,$6,$1,$7,$8,$8)""",
                            r.get("wid") or C.new_id("WF"), tenant, _ACCOUNTS[tenant], sim, r.get("kind", "SESSION_CYCLE"),
                            r["state"], r.get("sd", date(2026, 11, 5)), created)
    return dict(_ACCOUNTS)


def cycle(env, pg_pool, rows):
    run(_seed(pg_pool, rows))
    env.pool = env.st.pool = pg_pool
    return part(env.fresh(), "last_cycle")


def test_hs70_no_rows(env, pg_pool):
    p = cycle(env, pg_pool, [])
    assert p["status"] == "DEGRADED" and p["detail"] == "No session cycle has been recorded yet."


@pytest.mark.parametrize("state,sd,hours", [("COMPLETED", date(2026, 11, 5), 26), ("RUNNING", date(2026, 11, 6), 1),
                                            ("WAITING_HUMAN", date(2026, 11, 6), 1), ("CREATED", date(2026, 11, 6), 1)])
def test_hs71_current_cycle_is_ok(env, pg_pool, state, sd, hours):
    p = cycle(env, pg_pool, [{"state": state, "sd": sd, "hours": hours}])
    assert p["status"] == "OK" and p["detail"].startswith(f"The latest session cycle is {state}, for session {sd}, started ")


@pytest.mark.parametrize("state", ["BLOCKED", "FAILED"])
def test_hs72_blocked_or_failed_is_blocked(env, pg_pool, state):
    p = cycle(env, pg_pool, [{"state": state, "sd": date(2026, 11, 6), "hours": 2}])
    assert p["status"] == "BLOCKED" and f"is {state}" in p["detail"]


def test_hs73_older_than_the_previous_session_is_degraded(env, pg_pool):
    p = cycle(env, pg_pool, [{"state": "COMPLETED", "sd": date(2026, 11, 4), "hours": 50}])
    assert p["status"] == "DEGRADED" and "older than the previous session, 2026-11-05" in p["detail"]
    assert "started 2 days ago" in p["detail"]


def test_hs74_simulations_other_kinds_and_tenants(env, pg_pool):
    rows = [{"tenant": "tenant-one", "state": "COMPLETED", "sd": date(2026, 11, 4), "hours": 50},
            {"tenant": "tenant-two", "state": "COMPLETED", "sd": date(2026, 11, 5), "hours": 26},       # newest real cycle
            {"tenant": "tenant-one", "state": "FAILED", "sd": date(2026, 11, 5), "hours": 1, "sim": True},
            {"tenant": "tenant-one", "state": "BLOCKED", "kind": "PREMARKET_CHECK", "hours": 0.5}]
    p = cycle(env, pg_pool, rows)
    assert p["status"] == "OK" and "COMPLETED, for session 2026-11-05" in p["detail"]
    rows.append({"tenant": "tenant-one", "state": "BLOCKED", "sd": date(2026, 11, 6), "hours": 3})       # now tenant one is newest
    p = cycle(env, pg_pool, rows)
    assert p["status"] == "BLOCKED" and "BLOCKED, for session 2026-11-06" in p["detail"]


def test_hs75_only_state_session_and_age(env, pg_pool):
    accounts = run(_seed(pg_pool, [{"tenant": "tenant-SECRET-77", "state": "COMPLETED", "wid": "WF-SECRET-77"}]))
    env.pool = env.st.pool = pg_pool
    b = env.fresh()
    p = part(b, "last_cycle")
    assert p["detail"] == "The latest session cycle is COMPLETED, for session 2026-11-05, started 26.0 hours ago."
    s = texts(b)
    assert "tenant-SECRET-77" not in s and "WF-SECRET-77" not in s and accounts["tenant-SECRET-77"] not in s
    _scan(b)


def test_hs77_cancelled_is_degraded(env, pg_pool):
    p = cycle(env, pg_pool, [{"state": "CANCELLED", "sd": date(2026, 11, 5), "hours": 3}])
    assert p["status"] == "DEGRADED" and "is CANCELLED" in p["detail"]


def test_hs130_no_write_on_the_real_database(env, pg_pool):
    run(_seed(pg_pool, [{"state": "COMPLETED"}, {"state": "RUNNING", "sd": date(2026, 11, 6), "hours": 1},
                        {"state": "BLOCKED", "tenant": "tenant-two", "hours": 40}]))
    env.pool = env.st.pool = pg_pool

    async def fingerprint():
        async with pg_pool.acquire() as c:
            tables = [r["tablename"] for r in await c.fetch("SELECT tablename FROM pg_tables WHERE schemaname='autodesk' ORDER BY 1")]
            counts = {tb: await c.fetchval(f"SELECT count(*) FROM autodesk.{tb}") for tb in tables}
            hashes = {tb: await c.fetchval(f"SELECT md5(coalesce(string_agg(x::text, ',' ORDER BY x::text), '')) FROM autodesk.{tb} x")
                      for tb in ("workflows", "accounts", "events", "simulations")}
        return counts, hashes
    before = run(fingerprint())
    assert before[0]["workflows"] == 3 and before[0]["accounts"] >= 2
    for _ in range(4):
        env.advance(hs.CACHE_TTL_S + 1)
        assert env.fresh()["parts"]["last_cycle"]["status"] in ("OK", "DEGRADED", "BLOCKED")
    assert run(fingerprint()) == before


def test_hs130_a_write_through_the_route_connection_is_refused(pg_pool):
    """The last-cycle query runs in a read-only transaction: Postgres itself refuses a write there."""
    async def go():
        async with pg_pool.acquire() as c:
            async with c.transaction(readonly=True):
                with pytest.raises(Exception, match="read-only"):
                    await c.execute("DELETE FROM autodesk.workflows")
    run(go())
