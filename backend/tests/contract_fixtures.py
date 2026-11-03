"""The shared browser/route contract fixtures, built from the backend's own routes. They are written by pytest, so the
suite's autouse stubs apply exactly as in the tests (tests/conftest.py risk_mock_inputs: a MOCK sector and market
state for the universal risk service):

    CONTRACT_FIXTURES_OUT=<dir> python -m pytest tests/test_decision_card_contract.py -q
        writes <dir>/contract-trade-plan-paper.json and <dir>/contract-decision-card.json; copy them into
        frontend-v5/e2e/fixtures/

Each answer is what the REAL route returns in the MOCK world of tests/test_strategy_plan.py (cash) or for the REAL
2026-10-21 staging capture of POST /api/desk/strategy/top (F&O), on one in-memory Mongo (tests/test_desk_trading.FakeDb).
tests/test_trade_plan_contract.py and tests/test_decision_card_contract.py rebuild the same answers and compare them
with the files, so a fixture that drifts from the backend fails a test instead of passing a mocked UI.
"""
from __future__ import annotations

import asyncio
import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import pytest

FIXTURES = Path(__file__).resolve().parents[2] / "frontend-v5" / "e2e" / "fixtures"
A = {"X-Test-User": "user_a"}
LIST_DATE = "2026-10-19"                       # the MOCK world's scan day: the stored AI watchlist day of the decision card
BUILT_AT = datetime(2026, 10, 19, 17, 15, tzinfo=timezone.utc)       # 22:45 IST, the job's slot
SIZED = {"limit": 1, "capital": 1000000, "risk_pct": 0.5}             # a sized cash idea: quantity, rupee risk and % of capital


def _surfaces(mp: pytest.MonkeyPatch):
    from tests.test_trade_plan_contract import make_surfaces
    return make_surfaces(mp)


def _fno_top() -> Dict[str, Any]:
    from services.strategy_plan import regime_fit
    from tests.test_fno_idea_paper_trade_contract import TOP
    top = copy.deepcopy(TOP)
    regime_fit.flag_cash_conflicts(top)          # the /top route's own order: conflicts first, then the plans
    regime_fit.attach_trade_plans(top)
    return top


def _fno_idea(top: Dict[str, Any], underlying: str = "BANKNIFTY") -> Dict[str, Any]:
    return next(i for i in top["classes"]["index_options"]["ideas"] if i["underlying"] == underlying)


async def _user_from_header(request):
    from fastapi import HTTPException
    uid = request.headers.get("X-Test-User")
    if not uid:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return {"user_id": uid}


def plan_ref(tp: Dict[str, Any]) -> Dict[str, Any]:
    """What the browser sends (frontend strategy/trade-plan.ts planRefOf)."""
    return {"plan_id": tp["plan_id"], "candidate_id": tp["strategy"]["candidate_id"], "rules_version": tp["rules_version"]}


def cash_body(idea: Dict[str, Any], scan_date: str, quantity: int) -> Dict[str, Any]:
    """The share paper-trade body a row sends at its plan's levels (frontend PlanPaperTrade.tsx planCashBody)."""
    tp = idea["trade_plan"]
    prim = next(t for t in tp["targets"] if t["primary"])
    body = {"symbol": idea["symbol"], "quantity": quantity, "entry_price": tp["entry"]["price"], "stop_price": tp["stop"]["price"],
            "target_price": prim["price"] if prim["price"] > tp["entry"]["price"] else None,
            "source": {"kind": "scanner", "bucket": idea["scanner"]["bucket"], "signal_date": scan_date},
            "entry_rule": tp["entry"]["desk_entry_rule"]}
    if (tp.get("exit_plan") or {}).get("time", {}).get("max_sessions"):
        body["max_hold_sessions"] = tp["exit_plan"]["time"]["max_sessions"]
    body["plan_ref"] = plan_ref(tp)
    return body


def trade_plan_paper() -> Dict[str, Any]:
    """contract-trade-plan-paper.json (Phase 2.1): the cash idea and its body, the F&O board and its body."""
    from tests.test_fno_idea_paper_trade_contract import CONTRACT
    old = json.loads((FIXTURES / "contract-trade-plan-paper.json").read_text(encoding="utf-8"))
    with pytest.MonkeyPatch.context() as mp:
        c = _surfaces(mp)
        ideas = c.post("/api/desk/strategy/ideas", json={"limit": 1}, headers=A).json()
    idea = ideas["ideas"][0]
    top = _fno_top()
    ftp = _fno_idea(top)["trade_plan"]
    return {
        "about": old["about"],
        "cash": {"ideas_response": ideas, "trade_plan": idea["trade_plan"],
                 "body": cash_body(idea, ideas["selection"]["scan_date"], old["cash"]["body"]["quantity"]), "bar": old["cash"]["bar"]},
        "fno": {"idea_underlying": "BANKNIFTY", "trade_plan": ftp,
                "body": {**copy.deepcopy(CONTRACT["body_with_levels"]), "plan_ref": plan_ref(ftp)}, "top_response": top},
    }


def decision_card() -> Dict[str, Any]:
    """contract-decision-card.json (Phase 3): ONE sized cash plan as the Top 10 (POST /ideas), the Strategy Builder (POST
    /plan with the idea's own plan_inputs), the stored AI watchlist day (the job's shape_day and the read route's
    annotation) and GET /api/desk/trade-plans/{id} answer it; the F&O board with its plans and one plan's GET answer; a
    futures plan from the Builder; and the paper account the % of equity is worked out against."""
    from routes import ai_watchlist as aiw_route
    from services import ai_watchlist_build as awb
    from services.strategy_plan import trade_plan as tpm

    from fastapi.testclient import TestClient

    import routes.risk_controls as risk_route
    from services import risk_controls as rc
    from tests.test_desk_trading import bar

    top = _fno_top()
    with pytest.MonkeyPatch.context() as mp:
        c = _surfaces(mp)
        ideas = c.post("/api/desk/strategy/ideas", json=SIZED, headers=A).json()
        idea = ideas["ideas"][0]
        sym = idea["symbol"]
        # MOCK: the session the entry traded in (the risk service reads the last close and traded value from it)
        c.rows[sym] = [dict(bar("2026-10-19", 1215.0, 1185.0, 1200.0), symbol=sym)]
        builder = c.post("/api/desk/strategy/plan", json=idea["plan_inputs"], headers=A).json()
        futures = c.post("/api/desk/strategy/plan", json={**idea["plan_inputs"], "instrument": "futures"}, headers=A).json()
        ftp = _fno_idea(top)["trade_plan"]
        asyncio.run(tpm.store(c.db, copy.deepcopy(ftp), "system:ai-watchlist"))
        pid = idea["trade_plan"]["plan_id"]
        cash_get = c.get(f"/api/desk/trade-plans/{pid}", headers=A).json()
        fno_get = c.get(f"/api/desk/trade-plans/{ftp['plan_id']}", headers=A).json()
        account = c.get("/api/desk/paper-account", headers=A).json()
        # GET /api/risk/profile for the same user (Phase 1): the equity basis the card's "% of equity" uses
        mp.setattr(risk_route, "db", c.db)
        mp.setattr(risk_route, "get_current_user", _user_from_header)
        app = c.app
        app.include_router(risk_route.router)
        profile = TestClient(app).get("/api/risk/profile", headers=A).json()
        # Real risk-service decisions on the same plan (the card's approval badge reads only these):
        #   user_a, the loosest profile (tests/risk_helpers.py), the CARD's size (account_size): ALLOW, the trade is written;
        #   user_c, the owner's default profile (0.5% a trade), the plan's OWN size: REDUCE to the card's size, nothing written;
        #   user_d, the loosest profile with its kill switch on, the card's size: BLOCK, nothing written.
        scan = ideas["selection"]["scan_date"]
        body = cash_body(idea, scan, cash_get["account_size"]["quantity"])
        own_body = cash_body(idea, scan, idea["trade_plan"]["size"]["quantity"])
        from tests.risk_helpers import loose_profile_doc
        c.db.cols["risk_profiles"].docs.append(loose_profile_doc("user_d"))
        asyncio.run(rc.set_control(c.db, "user_d", field="kill_switch", value=True, reason="MOCK: decision-card fixture", actor="user_d"))
        answers = {}
        for user, sent in (("user_a", body), ("user_c", own_body), ("user_d", body)):
            h = {"X-Test-User": user}
            assert c.post("/api/desk/strategy/ideas", json=SIZED, headers=h).status_code == 200      # the user's own copy of the plan
            before = c.get(f"/api/desk/trade-plans/{pid}", headers=h).json()
            r = c.post("/api/desk/paper-trades", json=copy.deepcopy(sent), headers=h)
            answers[user] = {"sent": sent, "trade_plan_response_before": before,
                             "paper_status": r.status_code, "paper_detail": r.json().get("detail") if r.status_code >= 400 else None,
                             "trade_plan_response": c.get(f"/api/desk/trade-plans/{pid}", headers=h).json()}
        default_profile = TestClient(app).get("/api/risk/profile", headers={"X-Test-User": "user_c"}).json()
        # The same plan for user_e (the owner's default profile, nothing open) in a BEAR regime: the governor's 0.5 factor
        # (the snapshot's market state as tests/conftest.py stubs it, with the regime BEAR), and the F&O plan for a
        # default-profile user: one lot over the per-trade budget.
        from services.risk_gate import inputs as risk_inputs
        calm = risk_inputs.market_state

        async def bear_market():
            return {**(await calm()), "regime": "BEAR"}
        user_e = {"X-Test-User": "user_e"}
        assert c.post("/api/desk/strategy/ideas", json=SIZED, headers=user_e).status_code == 200
        mp.setattr(risk_inputs, "market_state", bear_market)
        bear_get = c.get(f"/api/desk/trade-plans/{pid}", headers=user_e).json()
        mp.setattr(risk_inputs, "market_state", calm)
        fno_default_get = c.get(f"/api/desk/trade-plans/{ftp['plan_id']}", headers=user_e).json()
    top_fno = copy.deepcopy(top)
    top_fno.pop("classes", None)
    top_fno["classes"] = {k: v for k, v in top["classes"].items() if k != "cash"}
    day = awb.shape_day(LIST_DATE, ideas, top_fno, BUILT_AT)
    day = json.loads(json.dumps(day, default=str))
    aiw_route.annotate(day, {"cash": {}, "fno": {}}, [LIST_DATE])
    day_response = {**day, "available_dates": [{"list_date": LIST_DATE, "built_at": day["built_at"], "cash": len(day["cash"]),
                                                "fno": len(day["fno"])}], "read_only": True}
    return {
        "about": ("Phase 3 decision cards: ONE plan_id per instrument across the Top 10, the AI watchlist, the Strategy Builder and "
                  "GET /api/desk/trade-plans/{id}, generated from the backend's own routes by tests/contract_fixtures.py and "
                  "checked against them by tests/test_decision_card_contract.py. cash: MOCK — not real data (the "
                  "RELIANCE-like world of backend/tests/test_strategy_plan.py), its plan sized by its inputs (capital 10,00,000, risk 0.5%); every "
                  "account_size is the risk service's own sizing for that user (services/risk_gate/plan_sizing.py). fno: the "
                  "REAL 2026-10-21 staging capture desk-strategy-top.json with the plans the board builds for it."),
        "cash": {"ideas_request": SIZED, "ideas_response": ideas, "builder_response": builder, "trade_plan_response": cash_get,
                 "body": body, "allowed": answers["user_a"], "reduced": answers["user_c"], "blocked": answers["user_d"],
                 "bear_default_response": bear_get},
        "risk_profile": profile,
        "risk_profile_default": default_profile,
        "futures": {"builder_response": futures},
        "fno": {"idea_underlying": "BANKNIFTY", "top_response": top_fno, "trade_plan_response": fno_get,
                "trade_plan_response_default": fno_default_get},
        "ai_watchlist_day": day_response,
        "paper_account": account,
    }


def dump(obj: Any) -> str:
    return json.dumps(obj, indent=1, ensure_ascii=True) + "\n"

