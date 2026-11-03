"""Backtest reproducibility (Phase 4.2): every run records what reproduces it, and every stored run, old ones included,
reads through one normaliser (TC-RP-1 … TC-RP-4 of test_reports/p4_research_hardening_TESTCASES.md).

Fixtures are MOCK — not real data. TC-RP-4's "old run" rows copy the SHAPE of the three strategy_runs rows stored on staging
before this change (C_research_and_data.md Q5: metrics with price_basis / universe_basis, no code_version, no cost_model,
snapshot_as_of NULL); their values are made up.
"""
from __future__ import annotations

import asyncio
import json
from datetime import date

from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.strategy_engine import backtest as bt
from tests.test_backtest_exit_rules import D1, D2, D3, D4, Provider, _Pool, cand, ob, run, spec


def _run(monkeypatch, **kw):
    p = Provider([D1, D2, D3, D4], {D1: [cand("A", 100.0)]},
                 {D2: {"A": ob(100, 101, 99, 100)}, D3: {"A": ob(100, 101, 99, 100)}, D4: {"A": ob(100, 101, 99, 100)}})
    return run(monkeypatch, p, **kw)


# ── TC-RP-1 ──────────────────────────────────────────────────────────────────

def test_tc_rp1_a_run_records_everything_that_reproduces_it(monkeypatch):
    res = _run(monkeypatch, cost=bt.COST_CARD, brokerage=20.0)
    pv = res.metrics["provenance"]
    assert pv["schema"] == "provenance-v1"
    assert pv["data_watermark"] == res.metrics["data_watermark"] and pv["data_watermark"]["latest_session_available"] == "2026-01-08"
    cv = pv["code_version"]
    assert cv == res.metrics["code_version"] and len(cv["engine_sha256"]) == 64 and cv["exit_rules_version"] == "exit-rules-v1"
    rv = pv["rule_version"]
    assert rv["dsl_version"] == "1" and rv["spec_sha256"] == bt.spec_sha256(spec()) and rv["exit_rules_version"] == "exit-rules-v1"
    assert rv["strategy_version_id"] is None                              # written by persist_run, which knows it
    assert pv["cost_model"] == {"version": "desk-cost-v2", "slippage_pct_per_side": 0.0, "slippage_basis": "in the fill prices",
                                "brokerage_rs_per_side": 20.0,
                                "statutory": "STT, exchange transaction charge, SEBI fee, stamp duty and GST, equity delivery",
                                "source": "services/desk_cost_card.py"}
    assert pv["universe"]["type"] == "index" and pv["universe"]["basis"] == res.metrics["universe_basis"]
    assert pv["entry_timing"] == "signal_close"


def test_tc_rp1_the_flat_cost_model_is_recorded_as_such(monkeypatch):
    pv = _run(monkeypatch, cost=bt.COST_FLAT, brokerage=20.0).metrics["provenance"]
    assert pv["cost_model"]["version"] == "desk-flat-v1" and pv["cost_model"]["statutory"] is None


def test_tc_rp1_the_spec_hash_ignores_key_order_and_sees_any_rule_change():
    a = spec()
    b = json.loads(json.dumps(a, sort_keys=True))
    b = {k: b[k] for k in reversed(list(b))}                             # same rules, keys in another order
    assert bt.spec_sha256(a) == bt.spec_sha256(b)
    c = spec()
    c["exit"]["stoploss_pct"] = c["exit"]["stoploss_pct"] + 1
    assert bt.spec_sha256(c) != bt.spec_sha256(a)


def test_tc_rp1_the_engine_hash_covers_the_universe_and_dsl_code():
    assert {"strategy_engine/liquid_universe.py", "strategy_engine/dsl.py", "strategy_engine/compiler_stock.py",
            "strategy_engine/evaluator.py", "desk_cost_card.py", "exit_rules.py"} <= set(bt._ENGINE_FILES)


# ── TC-RP-2 ──────────────────────────────────────────────────────────────────

def test_tc_rp2_persist_run_stores_the_watermark_and_the_strategy_version(monkeypatch):
    res = _run(monkeypatch)
    pool = _Pool()
    asyncio.run(bt.persist_run(pool, strategy_id="s", version_id="ver-1", spec=spec(), result=res, from_date=D1, to_date=D4,
                               triggered_by=None))
    sql, args = pool.conn.calls[0]
    assert "snapshot_as_of" in sql and args[-1] == D4
    stored = json.loads(args[5])
    assert stored["provenance"]["rule_version"]["strategy_version_id"] == "ver-1"
    pv = bt.run_provenance({"metrics": args[5], "snapshot_as_of": args[-1], "version_id": "ver-1"})
    assert pv["complete"] is True and pv["not_recorded"] == [] and pv["data"]["snapshot_as_of"] == "2026-01-08"


# ── TC-RP-3 / TC-RP-4: old runs ──────────────────────────────────────────────

OLD_METRICS = {"trade_count": 82, "win_rate": 41.46, "profit_factor": 0.53, "max_drawdown_pct": -0.27, "total_return_pct": -0.25,
               "universe_basis": "latest_snapshot", "price_basis": "corp_action_adjusted"}       # MOCK values, staging shape
DEFINITION = {"version": "1", "asset_class": "STOCK", "name": "old", "universe": {"type": "index", "ref": "NIFTY500"},
              "entry": {"all_of": [{"feature": "rsi14", "op": ">", "value": 55}]},
              "exit": {"stoploss_pct": 5, "target_rr": 2, "max_hold_days": 30},
              "ranking": {"by": "score", "limit": 5, "order": "desc"}, "rebalance": "daily"}


def test_tc_rp3_an_old_run_reads_with_its_gaps_named():
    row = {"metrics": json.dumps(OLD_METRICS), "snapshot_as_of": None, "version_id": "ver-old"}
    pv = bt.run_provenance(row)
    assert pv["schema"] is None and pv["complete"] is False
    assert pv["not_recorded"] == ["data_watermark", "code_version", "rule_version.spec_sha256", "rule_version.exit_rules_version",
                                  "cost_model", "entry_timing"]
    assert pv["universe"] == {"basis": "latest_snapshot", "warning": None, "rule": None}
    assert pv["rule_version"]["strategy_version_id"] == "ver-old" and pv["price_basis"] == "corp_action_adjusted"
    # with its (immutable) strategy version the spec hash is derived, and labelled as derived
    pv2 = bt.run_provenance(row, json.dumps(DEFINITION))
    assert pv2["rule_version"]["spec_sha256"] == bt.spec_sha256(DEFINITION)
    assert pv2["rule_version"]["spec_sha256_source"].startswith("derived at read time")
    assert "rule_version.spec_sha256" not in pv2["not_recorded"]


def test_tc_rp3_a_run_from_the_exit_rules_release_reads_its_cost_model_and_watermark():
    # #361 (2026-10-27) wrote cost_model, code_version, data_watermark and snapshot_as_of, but no provenance block.
    m = {**OLD_METRICS, "cost_model": "desk-cost-v2", "slippage_pct_per_side": 0.0005, "entry_timing": "signal_close",
         "exit_rules_version": "exit-rules-v1", "code_version": {"git_sha": None, "engine_sha256": "e" * 64},
         "data_watermark": {"latest_session_available": "2026-10-26", "window_last_session": "2026-10-23"}}
    pv = bt.run_provenance({"metrics": m, "snapshot_as_of": date(2026, 10, 26), "version_id": "v"}, DEFINITION)
    assert pv["cost_model"] == {"version": "desk-cost-v2", "slippage_pct_per_side": 0.05}
    assert pv["data"] == {"snapshot_as_of": "2026-10-26", "window_last_session": "2026-10-23"}
    assert pv["not_recorded"] == [] and pv["complete"] is True


def test_tc_rp3_get_run_returns_provenance_for_an_old_run(monkeypatch):
    import routes.strategy_builder as route

    class Conn:
        async def fetchrow(self, sql, *args):
            if "FROM strategy_runs" in sql:
                return {"id": "run-1", "strategy_id": "s", "version_id": "ver-old", "metrics": json.dumps(OLD_METRICS),
                        "equity_curve": "[]", "snapshot_as_of": None, "strategy_owner": "u", "is_public_template": False}
            if "FROM strategy_versions" in sql:
                assert args == ("ver-old",)
                return {"definition": json.dumps(DEFINITION)}
            raise AssertionError(sql)

        async def fetch(self, sql, *args):
            return []

    class Pool:
        def acquire(self):
            class A:
                async def __aenter__(self):
                    return Conn()

                async def __aexit__(self, *a):
                    return False
            return A()

    async def user(request):
        return {"user_id": "u"}

    async def pool():
        return Pool()
    monkeypatch.setattr(route, "get_current_user", user)
    monkeypatch.setattr(route.pg_client, "get_pool", pool)
    app = FastAPI()
    app.include_router(route.router)
    r = TestClient(app).get("/api/strategy-builder/runs/run-1")
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["run"]["metrics"]["trade_count"] == 82 and b["trades"] == []
    assert b["provenance"]["rule_version"]["spec_sha256"] == bt.spec_sha256(DEFINITION)
    assert b["provenance"]["not_recorded"] == ["data_watermark", "code_version", "rule_version.exit_rules_version",
                                               "cost_model", "entry_timing"]
