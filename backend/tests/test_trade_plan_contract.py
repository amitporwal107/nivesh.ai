"""Cross-surface contract (CT-1, CT-2 of test_reports/p2_trade_plan_lifecycle_TESTCASES.md): for ONE plan_id, the ideas,
Top 10, AI watchlist, Strategy Builder and paper-trade responses carry byte-identical entry, stop and targets.

Cash: one world (the MOCK RELIANCE-like sources of tests/test_strategy_plan.py) drives the real routes —
POST /api/desk/strategy/ideas, POST /api/desk/strategy/top {classes: [cash]}, POST /api/desk/strategy/plan (the
Builder, with the idea's own plan_inputs), the AI watchlist job's row shaping (ai_watchlist_build.cash_entry) and
POST /api/desk/paper-trades with the plan_ref — all against one in-memory Mongo (tests/test_desk_trading.FakeDb).

F&O: the REAL 2026-10-21 staging capture of POST /api/desk/strategy/top (frontend-v5/e2e/fixtures/desk-strategy-top.json)
goes through the board's own plan step (regime_fit.attach_trade_plans), the AI watchlist job's day shaping
(ai_watchlist_build.shape_day, whose stored strategy_levels are what a stored row displays) and the paper route.

CT-2: the bodies the browser sends with a plan_ref are pinned in frontend-v5/e2e/fixtures/contract-trade-plan-paper.json
(the Playwright specs assert the browser sends exactly them); here they go through the real route, and the fixture's
plans are asserted to be the ones the backend builds, so the browser and the route cannot drift apart.
"""
from __future__ import annotations

import asyncio
import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

import routes.desk_trading as desk_route
import routes.strategy_plan as route
from services import ai_watchlist_build as awb
from services import desk_trading as svc
from services.strategy_plan import ideas as ideas_mod
from services.strategy_plan import regime_fit
from services.strategy_plan import trade_plan as tpm
from services.strategy_plan.evidence import src_ok
from tests.test_desk_trading import FakeDb, bar
from tests.test_fno_idea_paper_trade_contract import CLOCK, CONTRACT, IDEA, TOP, exchange_lots  # noqa: F401  (fixture)
from tests.test_strategy_ideas import fake_selection
from tests.test_strategy_plan import COSTS, NOW, TODAY, world

FIXTURES = Path(__file__).resolve().parents[2] / "frontend-v5" / "e2e" / "fixtures"
PLAN_FIXTURE = FIXTURES / "contract-trade-plan-paper.json"
A = {"X-Test-User": "user_a"}
DESK_NOW = datetime(2026, 10, 20, 5, 0, tzinfo=timezone.utc)          # 10:30 IST, after the plan's 2026-10-19 data


@pytest.fixture
def surfaces(monkeypatch):
    return make_surfaces(monkeypatch)


def make_surfaces(monkeypatch):
    """The real Strategy and desk routes on one in-memory Mongo with the MOCK world; also used outside pytest by
    tests/contract_fixtures.py, which writes the shared browser/route fixtures from it."""
    db = FakeDb()
    # MOCK: the loosest allowed risk profile (tests/risk_helpers.py): this suite tests the plan's levels end to end,
    # not the Phase 1 limits (tests/test_risk_entry_paths.py).
    from tests.risk_helpers import loose_profile_doc
    db.cols["risk_profiles"].docs.extend(loose_profile_doc(u) for u in ("user_a", "user_b", "u1"))
    monkeypatch.setattr(route, "db", db)
    monkeypatch.setattr(desk_route, "db", db)
    monkeypatch.setattr(route, "utcnow", lambda: NOW)
    monkeypatch.setattr(route, "today", lambda: TODAY)
    monkeypatch.setattr(svc, "_indexes_ready", False)
    monkeypatch.setattr(svc, "utcnow", lambda: DESK_NOW)

    async def fake_select(request, limit, chartink=None, chartink_limit=4):
        return fake_selection(1)

    async def fake_index(user_id, today):
        return {"state": "no_source", "reason": "none", "symbols": {}, "scans": []}

    async def fake_shared(user_id, chartink=None):
        return {"regime": src_ok({}, "x"), "sectors": src_ok({}, "x"), "portfolio": src_ok([], "x"), "sector_lists": {}}

    async def fake_collect(request, user_id, inp, today, shared=None):
        return world()                      # MOCK — the same sources for the ideas route and the Builder

    async def fake_name(symbol):
        return None
    real_build = ideas_mod.build_ideas

    async def pinned(request, user_id, limit, passed, applied, now, today, *a, **k):
        # the /top cash class asks with the wall clock (regime_fit._cash_class); the test's clock is the route's
        return await real_build(request, user_id, limit, passed, applied, NOW, TODAY, *a, **k)
    monkeypatch.setattr(ideas_mod, "build_ideas", pinned)
    for mod in (ideas_mod,):
        monkeypatch.setattr(mod, "select_opportunities", fake_select)
        monkeypatch.setattr(mod, "shared_for_ideas", fake_shared)
        monkeypatch.setattr(mod, "chartink_index", fake_index)
        monkeypatch.setattr(mod, "collect_snapshots", fake_collect)
        monkeypatch.setattr(mod, "company_name", fake_name)
    monkeypatch.setattr(route, "collect_snapshots", fake_collect)

    async def no_regime():
        return {"available": False, "reason": "MOCK: not read in this test"}
    monkeypatch.setattr(regime_fit, "read_regime", no_regime)

    async def fake_user(request: Request):
        uid = request.headers.get("X-Test-User")
        if not uid:
            raise HTTPException(status_code=401, detail="Not authenticated")
        return {"user_id": uid}
    monkeypatch.setattr(route, "get_current_user", fake_user)
    monkeypatch.setattr(desk_route, "get_current_user", fake_user)

    rows: Dict[str, Any] = {}

    async def fake_get(path: str, params=None, timeout: float = 10.0, *, creds=None):
        symbol = path.rsplit("/", 1)[-1]
        data = rows.get(symbol, [])
        return {"data": data, "count": len(data), "pagination": {"limit": params["limit"], "offset": 0, "total": None, "next_offset": None}}
    monkeypatch.setattr(svc.daas_client, "_get", fake_get)
    monkeypatch.setattr(svc.daas_client, "is_configured", lambda: True)

    app = FastAPI()
    app.include_router(route.router)
    app.include_router(desk_route.router)
    c = TestClient(app)
    c.db, c.rows = db, rows
    return c


def levels(tp_or_levels: Dict[str, Any]) -> Dict[str, Any]:
    """The contract: entry, stop and targets, as JSON text (byte-identical, not merely close)."""
    lv = tp_or_levels if "stop_method" in tp_or_levels else tpm.canonical_levels(tp_or_levels)
    return json.dumps({k: lv[k] for k in ("plan_id", "entry", "entry_legs", "order_type", "stop", "stop_method", "targets")}, sort_keys=True)


def test_one_cash_plan_id_carries_identical_levels_on_every_surface(surfaces):
    # The Top 10 stock board (frontend top10-data.ts) and the nightly job ask the ideas route with its DEFAULT inputs,
    # as the /top cash class does (regime_fit._cash_class); the Builder opens an idea with the idea's own plan_inputs.
    ideas = surfaces.post("/api/desk/strategy/ideas", json={"limit": 1}, headers=A)
    assert ideas.status_code == 200, ideas.text
    idea = ideas.json()["ideas"][0]
    tp_ideas = idea["trade_plan"]
    assert idea["trade_plan_id"] == tp_ideas["plan_id"] and tp_ideas["stored"] is True
    assert tp_ideas["eligibility"]["paper_eligible"], tp_ideas["eligibility"]

    top = surfaces.post("/api/desk/strategy/top", json={"limit": 1, "classes": ["cash"]}, headers=A)
    assert top.status_code == 200, top.text
    tp_top = top.json()["classes"]["cash"]["ideas"][0]["trade_plan"]

    builder = surfaces.post("/api/desk/strategy/plan", json=idea["plan_inputs"], headers=A)
    assert builder.status_code == 200, builder.text
    b = builder.json()
    cash = next(c for c in b["candidates"] if c["segment"] == "cash")
    tp_builder = cash["trade_plan"]
    assert b["trade_plans"][cash["id"]] == tp_builder["plan_id"]

    row = awb.cash_entry(idea, 1)                              # what the nightly job stores for this idea
    assert row["trade_plan_id"] == tp_ideas["plan_id"]

    sym = idea["symbol"]
    surfaces.rows[sym] = [dict(bar("2026-10-19", 1215.0, 1185.0, 1200.0), symbol=sym)]   # MOCK: the session the entry traded in
    prim = tpm.primary_target(tp_ideas)
    paper = surfaces.post("/api/desk/paper-trades", headers=A, json={
        "symbol": sym, "quantity": 3, "entry_price": tp_ideas["entry"]["price"], "stop_price": tp_ideas["stop"]["price"],
        "target_price": prim["price"], "entry_rule": tp_ideas["entry"]["desk_entry_rule"],
        "plan_ref": {"plan_id": tp_ideas["plan_id"], "candidate_id": tp_ideas["strategy"]["candidate_id"],
                     "rules_version": tp_ideas["rules_version"]}})
    assert paper.status_code == 201, paper.text
    tp_paper = paper.json()["trade"]["plan_levels"]

    want = levels(tp_ideas)
    assert [levels(x) for x in (tp_top, tp_builder, row["trade_plan"], tp_paper)] == [want] * 4
    assert tp_ideas["plan_id"] in {d["_id"] for d in surfaces.db["trade_plans"].docs}
    assert surfaces.get(f"/api/desk/trade-plans/{tp_ideas['plan_id']}", headers=A).json()["lifecycle"]["status"] == "open"


def test_one_fno_plan_id_carries_identical_levels_on_the_board_the_stored_row_and_the_paper_trade(surfaces, monkeypatch):
    top = copy.deepcopy(TOP)
    regime_fit.attach_trade_plans(top)                          # the /top route's own plan step
    idea = top["classes"]["index_options"]["ideas"][0]
    tp = idea["trade_plan"]
    day = awb.shape_day("2026-10-21", {"ideas": []}, top, CLOCK)
    [entry] = [e for e in day["fno"] if e.get("trade_plan_id") == tp["plan_id"]]
    shown = entry["strategy_levels"]["result"]                 # what the stored row displays
    assert (tp["stop"]["price"], tpm.primary_target(tp)["price"]) == (shown["underlying"]["stop"], shown["underlying"]["target"])
    assert tp["exit_plan"]["options"]["planned_stop"] == shown["premium"]["planned_stop"]

    asyncio.run(tpm.store(surfaces.db, copy.deepcopy(tp), "system:ai-watchlist"))
    monkeypatch.setattr(svc, "utcnow", lambda: CLOCK)          # the contract body's clock: after its chain day
    body = {**copy.deepcopy(CONTRACT["body_with_levels"]), "plan_ref": {"plan_id": tp["plan_id"]}}
    r = surfaces.post("/api/desk/paper-trades", json=body, headers=A)
    assert r.status_code == 201, r.text
    assert levels(r.json()["trade"]["plan_levels"]) == levels(tp) == levels(entry["trade_plan"])


# ── CT-2: the browser's bodies, pinned in one shared fixture ─────────────────
def load_fixture() -> Dict[str, Any]:
    # A gate, not a convenience: without the shared fixture the contract is not tested, so fail rather than skip.
    assert PLAN_FIXTURE.exists(), f"{PLAN_FIXTURE} is the shared browser/route contract fixture and must be present"
    return json.loads(PLAN_FIXTURE.read_text(encoding="utf-8"))


def test_the_fixtures_fno_plan_is_the_one_the_board_builds():
    fx = load_fixture()
    top = copy.deepcopy(TOP)
    regime_fit.attach_trade_plans(top)
    built = next(i for i in top["classes"]["index_options"]["ideas"] if i["underlying"] == fx["fno"]["idea_underlying"])["trade_plan"]
    assert fx["fno"]["trade_plan"]["plan_id"] == built["plan_id"] and levels(fx["fno"]["trade_plan"]) == levels(built)


def test_the_fixtures_fno_body_opens_a_trade_through_the_real_route(surfaces, monkeypatch):
    fx = load_fixture()
    asyncio.run(tpm.store(surfaces.db, copy.deepcopy(fx["fno"]["trade_plan"]), "system:ai-watchlist"))
    monkeypatch.setattr(svc, "utcnow", lambda: CLOCK)
    r = surfaces.post("/api/desk/paper-trades", json=copy.deepcopy(fx["fno"]["body"]), headers=A)
    assert r.status_code == 201, r.text
    assert r.json()["trade"]["plan_ref"]["plan_id"] == fx["fno"]["trade_plan"]["plan_id"]


def test_the_fixtures_cash_body_opens_a_trade_through_the_real_route(surfaces):
    fx = load_fixture()
    tp = fx["cash"]["trade_plan"]
    asyncio.run(tpm.store(surfaces.db, copy.deepcopy(tp), "system:ai-watchlist"))
    sym = fx["cash"]["body"]["symbol"]
    surfaces.rows[sym] = [dict(bar(fx["cash"]["bar"]["date"], fx["cash"]["bar"]["high"], fx["cash"]["bar"]["low"],
                                   fx["cash"]["bar"]["close"]), symbol=sym)]
    r = surfaces.post("/api/desk/paper-trades", json=copy.deepcopy(fx["cash"]["body"]), headers=A)
    assert r.status_code == 201, r.text
    t = r.json()["trade"]
    assert levels(t["plan_levels"]) == levels(tp) and t["state"] == "POSITION_OPEN"


def test_the_fixtures_cash_plan_is_the_one_the_ideas_route_builds(surfaces):
    fx = load_fixture()
    idea = surfaces.post("/api/desk/strategy/ideas", json={"limit": 1}, headers=A).json()["ideas"][0]
    assert idea["trade_plan"]["plan_id"] == fx["cash"]["trade_plan"]["plan_id"]
    assert levels(idea["trade_plan"]) == levels(fx["cash"]["trade_plan"])
    assert fx["cash"]["ideas_response"]["ideas"][0]["trade_plan"]["plan_id"] == fx["cash"]["body"]["plan_ref"]["plan_id"]
