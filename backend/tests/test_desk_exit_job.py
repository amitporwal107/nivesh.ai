"""The evening exit job as cron runs it: the lease, the session check, the heartbeat and the missed-run reading.

Test cases EJ-1 … EJ-14 in test_reports/paper_exit_job_reconcile_TESTCASES.md. Reuses the desk's in-memory world
(tests/test_desk_trading.py: Mongo stand-in + the data platform's /prices/eod/{symbol}) and the F&O world
(tests/test_desk_strategy_trades.py). Added here: the three reads the session check makes — /holidays, /prices/eod?on=
and /fno/NIFTY?on= — answered from `world.holidays`, `world.sessions_in` and `world.fno_in`.

MOCK — not real data: every symbol, bar, date and holiday below is made up.
"""
from __future__ import annotations

import asyncio
import copy
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from scripts import check_desk_alerts as job
from services import desk_strategy_trades as strat
from services import desk_trading as svc
from services import job_runs
from services import paper_account as acct
from services.copilot_tools import daas_client
from tests.test_desk_strategy_trades import open_strategy, sworld  # noqa: F401  (fixture)
from tests.test_desk_trading import A, B, api, bar, make_alert, open_trade, world  # noqa: F401  (fixtures)

IST = timezone(timedelta(hours=5, minutes=30))
REPO = Path(__file__).resolve().parents[2]


def ist(y, mo, d, h, mi) -> datetime:
    return datetime(y, mo, d, h, mi, tzinfo=IST).astimezone(timezone.utc)


TUE_EVENING = ist(2026, 10, 13, 20, 45)          # the 2026-10-13 cron slot


@pytest.fixture
def ready(world, monkeypatch):
    """The session check's reads on top of whatever `_get` the world installed."""
    world.holidays = set()
    world.sessions_in = {"2026-10-12", "2026-10-13", "2026-10-14", "2026-10-15"}
    world.fno_in = set(world.sessions_in)
    world.readiness_calls = []
    inner = daas_client._get

    async def fake_get(path: str, params=None, timeout: float = 10.0, *, creds=None):
        if path == "/holidays":
            world.readiness_calls.append(path)
            return {"data": [{"holiday_date": d, "segment": "CM", "description": "MOCK holiday"} for d in sorted(world.holidays)]}
        if path == "/prices/eod":
            world.readiness_calls.append(path)
            return {"data": [{"symbol": "MOCK"}] if params["on"] in world.sessions_in else []}
        if path == f"/fno/{job.FNO_REFERENCE}":
            world.readiness_calls.append(path)
            return {"data": [{"ticker_symbol": "NIFTY"}] if params["on"] in world.fno_in else []}
        return await inner(path, params, timeout)

    monkeypatch.setattr(daas_client, "_get", fake_get)
    return world


def seed(api, world):
    """Three trades and one alert over two users; the 2026-10-13 bars stop one trade and hit another's target."""
    ta = open_trade(api, A)                                                                   # FIXA stop 95
    tb = open_trade(api, B, symbol="FIXB", entry_price=500.0, stop_price=480.0, target_price=508.0)
    tc = open_trade(api, B, quantity=3, stop_price=90.0, target_price=130.0)                 # stays open (Phase 1: a target)
    make_alert(api, A, symbol="FIXB", level=507.0)
    world.add("FIXA", bar("2026-10-13", 103, 94.5, 97))
    world.add("FIXB", bar("2026-10-13", 509, 499, 507))
    return ta, tb, tc


def runs(world) -> List[Dict[str, Any]]:
    return sorted(world.db["job_runs"].docs, key=lambda d: d["started_at"])


def releases(world) -> List[Dict[str, Any]]:
    return [r for r in world.db[acct.LEDGER].docs if r["action"] == "release"]


def state(world):
    return (copy.deepcopy(world.db.trades.docs), copy.deepcopy(world.db.alerts.docs),
            copy.deepcopy(world.db[acct.ACCOUNTS].docs), copy.deepcopy(world.db[acct.LEDGER].docs))


def go(world, **kw):
    kw.setdefault("now", TUE_EVENING)
    world.now = kw["now"]                     # the desk's clock (closes, the heartbeat's finish) runs with the job
    return asyncio.run(job.run_job(world.db, **kw))


# ── EJ-5: which session should be in ─────────────────────────────────────────
@pytest.mark.parametrize("now,holidays,expected", [
    (ist(2026, 10, 13, 20, 45), set(), "2026-10-13"),            # Tue evening: today
    (ist(2026, 10, 13, 18, 59), set(), "2026-10-12"),            # before the 19:00 ingest: the previous day
    (ist(2026, 10, 12, 10, 0), set(), "2026-10-09"),             # Monday morning: Friday
    (ist(2026, 10, 21, 9, 0), {"2026-10-20"}, "2026-10-19"),     # the morning after a holiday: the day before it
    (ist(2026, 10, 17, 20, 45), set(), None),                    # Saturday evening: no session
    (ist(2026, 10, 20, 20, 45), {"2026-10-20"}, None),           # a holiday evening: no session
])
def test_ej5_expected_session(now, holidays, expected):
    from datetime import date
    session, why = job.expected_session(now, {date.fromisoformat(d) for d in holidays})
    assert (session.isoformat() if session else None) == expected
    assert (why is None) == (expected is not None)


# ── EJ-6: a good run records its heartbeat and its counts ────────────────────
def test_ej6_a_good_run_records_ok_with_the_counts(api, ready):
    ta, tb, tc = seed(api, ready)
    code, out = go(ready, require_bars=True)
    assert (code, out["status"], out["session"]) == (0, "ok", "2026-10-13")
    [run] = runs(ready)
    assert run["status"] == "ok" and run["exit_code"] == 0 and run["finished_at"] and run["error"] is None
    c = run["counts"]
    assert c["trades_checked"] == 3 and c["closed_by_reason"] == {"stop": 1, "target": 1}
    assert c["alerts_fired"] == 1 and c["errors"] == 0 and c["open_trades_behind"] == 0
    assert run["session"] == "2026-10-13"
    lease = ready.db["job_locks"].docs[0]
    assert lease["run_id"] == run["_id"] and lease["expires_at"] <= TUE_EVENING.isoformat(), "the lease is let go"


# ── EJ-3 / EJ-4: no bars, no session → nothing is written ────────────────────
def test_ej3_no_bars_for_the_session_writes_nothing_and_exits_2(api, ready):
    seed(api, ready)
    ready.sessions_in.discard("2026-10-13")
    before, writes = state(ready), ready.db.trades.writes + ready.db.alerts.writes
    ready.calls.clear()
    code, out = go(ready, require_bars=True)
    assert code == job.EXIT_NO_BARS == 2
    assert state(ready) == before and ready.db.trades.writes + ready.db.alerts.writes == writes
    assert ready.calls == [], "no bar was read for any symbol"
    [run] = runs(ready)
    assert (run["status"], run["exit_code"], run["session"]) == ("skipped_no_bars", 2, "2026-10-13")
    assert "not in the data platform yet" in run["error"]


def test_ej4_an_nse_holiday_writes_nothing_and_exits_3(api, ready):
    seed(api, ready)
    ready.holidays = {"2026-10-13"}
    before = state(ready)
    code, out = go(ready, require_bars=True)
    assert code == job.EXIT_NO_SESSION == 3 and state(ready) == before
    [run] = runs(ready)
    assert run["status"] == "skipped_no_session" and "NSE holiday" in run["error"]


def test_ej4_without_the_holiday_list_a_holiday_reads_as_missing_bars(api, ready, monkeypatch):
    """The calendar is for the message; the bars check is the guard. An unreadable list never lets a run through."""
    seed(api, ready)
    ready.sessions_in.discard("2026-10-13")
    inner = daas_client._get

    async def no_calendar(path, params=None, timeout=10.0, *, creds=None):
        if path == "/holidays":
            raise daas_client.DaasError("unreachable")
        return await inner(path, params, timeout)

    monkeypatch.setattr(daas_client, "_get", no_calendar)
    before = state(ready)
    code, _ = go(ready, require_bars=True)
    assert code == 2 and state(ready) == before
    assert "holiday list could not be read" in runs(ready)[0]["error"]


# ── EJ-7: failures are recorded ──────────────────────────────────────────────
def test_ej7_no_prices_at_all_is_a_recorded_failure(api, ready):
    seed(api, ready)
    ready.fail.update({s: daas_client.DaasError("unreachable") for s in ("FIXA", "FIXB")})
    code, out = go(ready, require_bars=True)
    assert code == 1
    [run] = runs(ready)
    assert run["status"] == "failed" and run["exit_code"] == 1 and "no prices" in run["error"]
    assert {d["status"] for d in ready.db.trades.docs} == {"open"}


def test_ej7_a_database_error_is_a_recorded_failure(api, ready, monkeypatch):
    seed(api, ready)

    async def boom(*_a, **_k):
        raise RuntimeError("mongo went away")

    monkeypatch.setattr(ready.db.trades, "find", lambda q: type("C", (), {"to_list": boom})())
    code, out = go(ready, require_bars=True)
    assert code == 1
    [run] = runs(ready)
    assert run["status"] == "failed" and run["error"].startswith("RuntimeError: mongo went away")


def test_ej7_the_data_platform_down_for_the_session_check_is_a_failure_not_a_skip(api, ready, monkeypatch):
    seed(api, ready)
    inner = daas_client._get

    async def down(path, params=None, timeout=10.0, *, creds=None):
        if path == "/prices/eod":
            raise daas_client.DaasError("timed out")
        return await inner(path, params, timeout)

    monkeypatch.setattr(daas_client, "_get", down)
    before = state(ready)
    code, _ = go(ready, require_bars=True)
    assert code == 1 and state(ready) == before and runs(ready)[0]["status"] == "failed"


# ── EJ-8 / EJ-9: a partial run is retried; a done session is skipped ─────────
def test_ej8_a_partial_run_is_caught_up_by_the_retry_and_nothing_closes_twice(api, ready):
    ta, tb, tc = seed(api, ready)
    ready.fail["FIXB"] = daas_client.DaasError("unreachable")
    code, out = go(ready, require_bars=True, skip_if_done=True)
    assert (code, out["status"]) == (0, "partial")
    docs = {d["_id"]: d for d in ready.db.trades.docs}
    assert docs[ta["id"]]["status"] == "closed" and docs[tb["id"]]["status"] == "open"
    assert out["counts"]["open_trades_behind"] == 1 and out["counts"]["behind_trade_ids"] == [tb["id"]]

    ready.fail.clear()
    code, out = go(ready, require_bars=True, skip_if_done=True, now=TUE_EVENING + timedelta(hours=2))
    assert (code, out["status"]) == (0, "ok"), "a partial run is not 'done': the retry evaluates"
    docs = {d["_id"]: d for d in ready.db.trades.docs}
    assert docs[tb["id"]]["exit_reason"] == "target"
    assert sorted(r["trade_id"] for r in releases(ready)) == sorted([ta["id"], tb["id"]]), "one release per trade"

    # EJ-9: the session is done now; a third run reads no bars and writes nothing to the desk.
    ready.calls.clear()
    before = state(ready)
    code, out = go(ready, require_bars=True, skip_if_done=True, now=TUE_EVENING + timedelta(hours=2, minutes=5))
    assert (code, out["status"]) == (0, "skipped_done") and ready.calls == [] and state(ready) == before
    assert [r["status"] for r in runs(ready)] == ["partial", "ok", "skipped_done"]


# ── EJ-1: two runs at once ───────────────────────────────────────────────────
class _Yielding:
    """The world's collections, yielding to the event loop before every call, so two runs interleave."""

    def __init__(self, db):
        self._db = db

    def __getitem__(self, name):
        col = self._db[name]

        class Col:
            def __getattr__(self, attr):
                target = getattr(col, attr)
                if not asyncio.iscoroutinefunction(target):
                    return target

                async def call(*a, **k):
                    await asyncio.sleep(0)
                    return await target(*a, **k)
                return call
        return Col()


def test_ej1_two_runs_at_once_one_runs_one_is_locked_out(api, ready):
    ta, tb, tc = seed(api, ready)
    db = _Yielding(ready.db)

    async def both():
        return await asyncio.gather(job.run_job(db, require_bars=True, now=TUE_EVENING, run_id="run-1"),
                                    job.run_job(db, require_bars=True, now=TUE_EVENING, run_id="run-2"))

    results = asyncio.run(both())
    assert sorted(code for code, _ in results) == [0, 4]
    assert sorted(r["status"] for r in runs(ready)) == ["ok", "skipped_locked"]
    closed = [d for d in ready.db.trades.docs if d["status"] == "closed"]
    assert len(closed) == 2 and sorted(r["trade_id"] for r in releases(ready)) == sorted(d["_id"] for d in closed)


def test_ej1_an_expired_lease_is_taken_over_and_a_live_one_is_not(world):
    db, t0 = world.db, TUE_EVENING
    lease = timedelta(minutes=60)
    assert asyncio.run(job_runs.acquire(db, "j", "r1", now=t0, lease=lease)) is True
    assert asyncio.run(job_runs.acquire(db, "j", "r2", now=t0 + timedelta(minutes=30), lease=lease)) is False
    assert asyncio.run(job_runs.acquire(db, "j", "r3", now=t0 + timedelta(minutes=61), lease=lease)) is True
    asyncio.run(job_runs.release(db, "j", "r1", now=t0 + timedelta(minutes=62)))     # not r1's any more: no effect
    assert db["job_locks"].docs[0]["run_id"] == "r3"
    asyncio.run(job_runs.release(db, "j", "r3", now=t0 + timedelta(minutes=63)))
    assert asyncio.run(job_runs.acquire(db, "j", "r4", now=t0 + timedelta(minutes=64), lease=lease)) is True
    assert len(db["job_locks"].docs) == 1, "the lease document is reused, never deleted"


# ── EJ-2: the same stale snapshot applied twice ──────────────────────────────
def test_ej2_two_evaluations_of_one_stale_snapshot_close_each_trade_once(api, world):
    seed(api, world)
    snapshot = asyncio.run(world.db.trades.find({"status": "open"}).to_list(None))
    bars, _ = asyncio.run(svc.fetch_bars_many(svc.fetch_starts(snapshot, "opened_at")))
    cash0 = world.db[acct.ACCOUNTS].docs and {a["user_id"]: a["cash_rs"] for a in world.db[acct.ACCOUNTS].docs}
    _, first = asyncio.run(svc.apply_trade_exits(world.db, copy.deepcopy(snapshot), bars))
    cash1 = {a["user_id"]: a["cash_rs"] for a in world.db[acct.ACCOUNTS].docs}
    _, second = asyncio.run(svc.apply_trade_exits(world.db, copy.deepcopy(snapshot), bars))
    assert (first["stop"], first["target"], first["already_closed"]) == (1, 1, 0)
    assert (second["stop"], second["target"], second["already_closed"]) == (0, 0, 2)
    assert len(releases(world)) == 2 and {a["user_id"]: a["cash_rs"] for a in world.db[acct.ACCOUNTS].docs} == cash1
    assert cash1 != cash0


def test_ej2_a_strategy_closed_twice_from_one_snapshot_releases_once(api, sworld):
    open_strategy(api)
    snapshot = asyncio.run(sworld.db.trades.find({"status": "open"}).to_list(None))
    asyncio.run(strat.apply_exits(sworld.db, copy.deepcopy(snapshot)))
    asyncio.run(strat.apply_exits(sworld.db, copy.deepcopy(snapshot)))
    assert [d["status"] for d in sworld.db.trades.docs] == ["closed"]
    assert len(releases(sworld)) == 1


# ── EJ-14: the job covers F&O strategy trades, and waits for their marks ──────
@pytest.fixture
def sready(sworld, ready):
    return sworld


def test_ej14_the_job_closes_a_strategy_once_when_the_fno_marks_are_in(api, sready):
    open_strategy(api)
    now = ist(2026, 10, 15, 20, 45)
    code, out = go(sready, require_bars=True, skip_if_done=True, now=now)
    assert (code, out["status"]) == (0, "ok") and out["counts"]["closed_by_reason"] == {"strategy_target": 1}
    assert len(releases(sready)) == 1
    code, out = go(sready, require_bars=True, skip_if_done=True, now=now + timedelta(hours=2))
    assert out["status"] == "skipped_done" and len(releases(sready)) == 1


def test_ej14_a_strategy_waits_when_the_fno_bhavcopy_is_not_in(api, sready):
    open_strategy(api)
    sready.fno_in.discard("2026-10-15")
    code, out = go(sready, require_bars=True, skip_if_done=True, now=ist(2026, 10, 15, 20, 45))
    assert (code, out["status"]) == (0, "partial")
    assert out["counts"]["strategy_waiting_for_fno"] == 1 and sready.history_calls == []
    assert [d["status"] for d in sready.db.trades.docs] == ["open"], "never closed on the previous session's marks"
    sready.fno_in.add("2026-10-15")
    code, out = go(sready, require_bars=True, skip_if_done=True, now=ist(2026, 10, 15, 22, 45))
    assert out["status"] == "ok" and [d["exit_reason"] for d in sready.db.trades.docs] == ["target"]


# ── EJ-10: a dry run writes nothing at all ───────────────────────────────────
def test_ej10_a_dry_run_takes_no_lease_and_records_no_run(api, ready):
    seed(api, ready)
    before = state(ready)
    code, out = go(ready, dry_run=True, require_bars=True)
    assert code == 0 and out["counts"]["closed_by_reason"] == {"stop": 1, "target": 1}
    assert state(ready) == before and ready.db["job_runs"].docs == [] and ready.db["job_locks"].docs == []


# ── EJ-11: missed, failed, running ───────────────────────────────────────────
def _run(started: datetime, status: str, **extra) -> Dict[str, Any]:
    return {"_id": f"r-{started.isoformat()}", "job": "check_desk_alerts", "started_at": started.isoformat(),
            "finished_at": None if status == "running" else (started + timedelta(minutes=1)).isoformat(),
            "status": status, **extra}


J = "check_desk_alerts"


def test_ej11_health_states():
    tue_2300 = ist(2026, 10, 13, 23, 0)
    assert job_runs.health(J, None, None, tue_2300)["state"] == "never_run"
    good = _run(ist(2026, 10, 13, 20, 45), "ok")
    h = job_runs.health(J, good, good, tue_2300)
    assert (h["state"], h["healthy"]) == ("ok", True)
    # Monday morning with Friday's two runs: the weekend is not a miss.
    fri_retry = _run(ist(2026, 10, 9, 22, 45), "skipped_done")
    assert job_runs.health(J, fri_retry, good, ist(2026, 10, 12, 10, 0))["state"] == "ok"
    # Tuesday 22:00 and the newest run is Friday's: Monday's and Tuesday's slots were missed.
    h = job_runs.health(J, fri_retry, good, ist(2026, 10, 13, 22, 0))
    assert (h["state"], h["healthy"]) == ("missed", False) and "20:45" in h["reason"]
    # Within the grace period the slot is not yet due.
    assert job_runs.health(J, fri_retry, good, ist(2026, 10, 12, 21, 30))["state"] == "ok"
    started = ist(2026, 10, 13, 20, 45)
    assert job_runs.health(J, _run(started, "running"), good, started + timedelta(minutes=10))["state"] == "running"
    died = job_runs.health(J, _run(started, "running"), good, started + timedelta(minutes=61))
    assert (died["state"], died["healthy"]) == ("failed", False) and "never recorded a finish" in died["reason"]
    assert job_runs.health(J, _run(started, "failed", error="RuntimeError: x"), good, tue_2300)["state"] == "failed"
    assert job_runs.health(J, _run(started, "partial"), good, tue_2300)["state"] == "partial"
    assert job_runs.health(J, _run(started, "skipped_no_bars", session="2026-10-13"), good, tue_2300)["state"] == "no_data"
    assert job_runs.health(J, _run(started, "skipped_no_session"), good, tue_2300)["healthy"] is True


# ── EJ-12: the admin read path ───────────────────────────────────────────────
def test_ej12_the_admin_route_reads_the_last_run(world, monkeypatch):
    import deps
    from routes import risk_controls as route

    monkeypatch.setattr(route, "db", world.db)
    monkeypatch.setattr(job_runs, "utcnow", lambda: ist(2026, 10, 13, 23, 0))
    world.db["job_runs"].docs.append(_run(ist(2026, 10, 13, 20, 45), "ok", counts={"trades_checked": 3},
                                          secret_field="never shown"))
    who = {"user": {"user_id": "u1", "role": "user"}}

    async def current(_request):
        return who["user"]

    monkeypatch.setattr(deps, "get_current_user", current)
    app = FastAPI()
    app.include_router(route.admin_router)
    client = TestClient(app)
    assert client.get("/api/admin/risk/jobs/check_desk_alerts").status_code == 403
    who["user"] = {"user_id": "a1", "role": "admin"}
    r = client.get("/api/admin/risk/jobs/check_desk_alerts")
    body = r.json()
    assert r.status_code == 200 and body["state"] == "ok" and body["healthy"] is True
    assert body["last_run"]["counts"] == {"trades_checked": 3} and "secret_field" not in body["last_run"]
    assert body["last_success"]["run_id"] == body["last_run"]["run_id"]
    assert client.get("/api/admin/risk/jobs/no_such_job").status_code == 404
    world.db["job_runs"].docs.clear()
    assert client.get("/api/admin/risk/jobs/check_desk_alerts").json()["state"] == "never_run"


# ── EJ-13: the cron file and the code agree ──────────────────────────────────
def test_ej13_the_cron_lines_match_the_schedule_and_carry_the_guards():
    text = (REPO / job_runs.SCHEDULES[J]["cron_file"]).read_text()
    assert "CRON_TZ=Asia/Kolkata" in text
    lines = [l for l in text.splitlines() if l and not l.startswith("#") and re.match(r"^\d", l)]
    sched = job_runs.SCHEDULES[J]
    assert [(int(l.split()[1]), int(l.split()[0])) for l in lines] == [(t.hour, t.minute) for t in sched["slots"]]
    for line in lines:
        assert line.split()[4] == "1-5" and sched["weekdays"] == (0, 1, 2, 3, 4)
        assert "/usr/bin/flock -n -E 4 " in line
        assert "python -m scripts.check_desk_alerts --require-bars --skip-if-done" in line
        assert "%" not in line, "cron turns % into a newline"
