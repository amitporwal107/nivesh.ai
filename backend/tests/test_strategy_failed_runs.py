"""A backtest that did not run is stored as FAILED, never OK (Strategy Copilot PRD §19.2 "Failed runs can appear
successful"; Appendix A "Worker fails during run → persist failed status and reason; do not show success metrics").

Before this fix a window with no data was stored with status 'OK' (metrics {"reason": "no_data"}), and an engine
error stored no run row at all.

Covers TC-11 … TC-16 of test_reports/strategy_phase0_runs_20261028_0528.md.

No network, no database. Replaced, and by what:
  * `route.get_current_user`  returns a fixed MOCK user. MOCK — the real one needs Mongo.
  * `pg_client.get_pool`      a fake pool that answers the route's reads from dicts and records every INSERT it is
                              sent, with its parameters. MOCK — not a database.
  * `bt.run_backtest`         returns a scripted result or raises a scripted error. MOCK — no bars are read.

The real `bt.persist_run` / `bt.persist_failed_run` run against the fake pool, so the SQL and parameters asserted
below are the ones postgres would receive. MOCK — not real data: every id here is invented.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from routes import strategy_builder as route
from services import pg_client
from services.strategy_engine import backtest as bt

USER = "user_owner"                                         # MOCK
S_ID = "11111111-1111-4111-8111-111111111111"
V_ID = "22222222-2222-4222-8222-222222222222"
DEFINITION = {"version": "1", "asset_class": "STOCK", "name": "mock", "universe": {"type": "index", "ref": "NIFTY50"},
              "entry": {"all_of": [{"feature": "rsi14", "op": ">", "value": 55}]},
              "exit": {"stoploss_pct": 5, "target_rr": 2, "max_hold_days": 10},
              "ranking": {"by": "score", "limit": 5, "order": "desc"}, "rebalance": "daily"}
D1, D2 = date(2026, 1, 5), date(2026, 3, 31)


class _Tx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class Conn:
    def __init__(self, sink: "Sink"):
        self.sink = sink

    def transaction(self):
        return _Tx()

    async def fetchrow(self, q: str, *args):
        if "FROM strategy_config" in q:
            return None
        if "FROM strategy_versions" in q:
            return {"id": V_ID, "strategy_id": S_ID, "is_active": True, "definition": json.dumps(DEFINITION)}
        if "FROM strategies" in q:
            return {"id": S_ID, "owner_id": USER, "is_public_template": False}
        raise AssertionError(f"unexpected fetchrow: {q}")

    async def execute(self, q: str, *args):
        if "INSERT INTO strategy_runs" in q and self.sink.fail_inserts:
            raise ConnectionError("MOCK: database unavailable")
        self.sink.calls.append((q, args))
        return "INSERT 0 1"


class Sink:
    def __init__(self):
        self.calls: List[Tuple[str, tuple]] = []
        self.fail_inserts = False

    def run_inserts(self) -> List[Tuple[str, tuple]]:
        return [c for c in self.calls if "INSERT INTO strategy_runs" in c[0]]


class Pool:
    def __init__(self, sink: Sink):
        self.sink = sink

    def acquire(self):
        conn = Conn(self.sink)

        class _CM:
            async def __aenter__(self_inner):
                return conn

            async def __aexit__(self_inner, *exc):
                return False
        return _CM()


@pytest.fixture
def sink(monkeypatch) -> Sink:
    s = Sink()

    async def fake_user(request: Request):
        return {"user_id": USER}

    async def get_pool():
        return Pool(s)

    monkeypatch.setattr(route, "get_current_user", fake_user)
    monkeypatch.setattr(pg_client, "get_pool", get_pool)
    return s


@pytest.fixture
def api(sink) -> TestClient:
    app = FastAPI()
    app.include_router(route.router)
    return TestClient(app, raise_server_exceptions=False)


def engine_returns(monkeypatch, result: bt.BacktestResult):
    async def fake_run_backtest(pool, spec, **kw):
        return result
    monkeypatch.setattr(bt, "run_backtest", fake_run_backtest)


def engine_raises(monkeypatch, exc: BaseException):
    async def fake_run_backtest(pool, spec, **kw):
        raise exc
    monkeypatch.setattr(bt, "run_backtest", fake_run_backtest)


def post(api: TestClient):
    return api.post(f"/api/strategy-builder/strategies/{S_ID}/backtest",
                    json={"from_date": D1.isoformat(), "to_date": D2.isoformat()})


# ── persist_run (TC-11, TC-12) ────────────────────────────────────────────────────────────────────────────────────

def test_tc11_a_no_data_result_is_stored_failed_and_the_parameter_positions_hold():
    s = Sink()
    res = bt.BacktestResult(metrics={"reason": "no_data"})
    asyncio.run(bt.persist_run(Pool(s), strategy_id=S_ID, version_id=V_ID, spec=DEFINITION, result=res,
                               from_date=D1, to_date=D2, triggered_by=USER))
    sql, args = s.run_inserts()[0]
    assert "'OK'" not in sql
    assert args[9] == "FAILED" and args[10] == bt.NO_DATA_MESSAGE and args[10].startswith("no_data")
    assert json.loads(args[5]) == {"reason": "no_data"}       # metrics kept, still parameter 6
    assert args[-1] is None                                    # snapshot_as_of still the last parameter
    assert len(s.calls) == 1                                   # no trade rows


def test_tc12_a_normal_result_is_still_stored_ok_with_no_error():
    s = Sink()
    res = bt.BacktestResult(trades=[], equity_curve=[], metrics={"trade_count": 0, "total_return_pct": 0.0})
    asyncio.run(bt.persist_run(Pool(s), strategy_id=S_ID, version_id=V_ID, spec=DEFINITION, result=res,
                               from_date=D1, to_date=D2, triggered_by=USER))
    sql, args = s.run_inserts()[0]
    assert args[9] == "OK" and args[10] is None


# ── the route (TC-13 … TC-16) ─────────────────────────────────────────────────────────────────────────────────────

def test_tc13_the_route_answers_a_no_data_window_with_status_failed_and_keeps_the_reason(api, sink, monkeypatch):
    engine_returns(monkeypatch, bt.BacktestResult(metrics={"reason": "no_data"}))
    r = post(api)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "FAILED" and body["error"].startswith("no_data")
    assert body["metrics"]["reason"] == "no_data"              # what the screens already read
    assert body["run_id"] and body["trade_count"] == 0
    assert sink.run_inserts()[0][1][9] == "FAILED"


def test_tc13b_a_normal_run_answers_status_ok(api, sink, monkeypatch):
    engine_returns(monkeypatch, bt.BacktestResult(trades=[], equity_curve=[], metrics={"trade_count": 0}))
    body = post(api).json()
    assert body["status"] == "OK" and body["error"] is None


def test_tc14_a_refused_window_is_recorded_failed_and_answers_400_as_before(api, sink, monkeypatch):
    exc = ValueError("MOCK: window has no universe")
    engine_raises(monkeypatch, exc)
    r = post(api)
    assert r.status_code == 400 and r.json() == {"detail": str(exc)}     # unchanged answer
    sql, args = sink.run_inserts()[0]
    assert "'FAILED'" in sql and "metrics" not in sql.split("VALUES")[0]  # no metrics on a failed run
    assert args[6] == f"{type(exc).__name__}: {exc}"


def test_tc14b_compile_errors_are_refused_the_same_way(api, sink, monkeypatch):
    engine_raises(monkeypatch, route.CompileError("MOCK: unknown feature"))
    r = post(api)
    assert r.status_code == 400 and r.json() == {"detail": "MOCK: unknown feature"}
    assert sink.run_inserts()[0][1][6] == "CompileError: MOCK: unknown feature"


def test_tc15_an_unexpected_engine_error_is_recorded_failed_and_answers_500_naming_the_run(api, sink, monkeypatch):
    engine_raises(monkeypatch, RuntimeError("MOCK: provider crashed"))
    r = post(api)
    assert r.status_code == 500
    sql, args = sink.run_inserts()[0]
    run_id = args[0]
    assert r.json() == {"detail": f"backtest failed; recorded as FAILED run {run_id}"}
    assert args[6] == "RuntimeError: MOCK: provider crashed"


def test_tc16_if_recording_the_failure_fails_too_the_original_error_still_answers_and_is_logged(
        api, sink, monkeypatch, caplog):
    sink.fail_inserts = True
    engine_raises(monkeypatch, ValueError("MOCK: bad window"))
    with caplog.at_level(logging.ERROR, logger=route.logger.name):
        r = post(api)
    assert r.status_code == 400 and r.json() == {"detail": "MOCK: bad window"}
    assert any("could not record the FAILED backtest run" in rec.getMessage() for rec in caplog.records)
    assert sink.run_inserts() == []
