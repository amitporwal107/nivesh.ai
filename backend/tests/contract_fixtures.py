"""The shared browser/route contract fixtures, written from the backend's own builders (run inside the backend image):

    python -m tests.contract_fixtures trade-plan-paper > frontend-v5/e2e/fixtures/contract-trade-plan-paper.json
    python -m tests.contract_fixtures decision-card    > frontend-v5/e2e/fixtures/contract-decision-card.json

Each answer is what the REAL route returns in the MOCK world of tests/test_strategy_plan.py (cash) or for the REAL
2026-10-21 staging capture of POST /api/desk/strategy/top (F&O), on one in-memory Mongo (tests/test_desk_trading.FakeDb).
tests/test_trade_plan_contract.py and tests/test_decision_card_contract.py rebuild the same answers and compare them
with the files, so a fixture that drifts from the backend fails a test instead of passing a mocked UI.
"""
from __future__ import annotations

import asyncio
import copy
import json
import sys
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

    top = _fno_top()
    with pytest.MonkeyPatch.context() as mp:
        c = _surfaces(mp)
        ideas = c.post("/api/desk/strategy/ideas", json=SIZED, headers=A).json()
        idea = ideas["ideas"][0]
        builder = c.post("/api/desk/strategy/plan", json=idea["plan_inputs"], headers=A).json()
        futures = c.post("/api/desk/strategy/plan", json={**idea["plan_inputs"], "instrument": "futures"}, headers=A).json()
        ftp = _fno_idea(top)["trade_plan"]
        asyncio.run(tpm.store(c.db, copy.deepcopy(ftp), "system:ai-watchlist"))
        cash_get = c.get(f"/api/desk/trade-plans/{idea['trade_plan']['plan_id']}", headers=A).json()
        fno_get = c.get(f"/api/desk/trade-plans/{ftp['plan_id']}", headers=A).json()
        account = c.get("/api/desk/paper-account", headers=A).json()
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
                  "RELIANCE-like world of backend/tests/test_strategy_plan.py), sized with capital 10,00,000 and risk 0.5%. fno: the "
                  "REAL 2026-10-21 staging capture desk-strategy-top.json with the plans the board builds for it."),
        "cash": {"ideas_request": SIZED, "ideas_response": ideas, "builder_response": builder, "trade_plan_response": cash_get,
                 "body": cash_body(idea, ideas["selection"]["scan_date"], idea["trade_plan"]["size"]["quantity"] or 1)},
        "futures": {"builder_response": futures},
        "fno": {"idea_underlying": "BANKNIFTY", "top_response": top_fno, "trade_plan_response": fno_get},
        "ai_watchlist_day": day_response,
        "paper_account": account,
    }


def dump(obj: Any) -> str:
    return json.dumps(obj, indent=1, ensure_ascii=True) + "\n"


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else ""
    builders = {"trade-plan-paper": trade_plan_paper, "decision-card": decision_card}
    if which not in builders:
        sys.exit(f"usage: python -m tests.contract_fixtures {{{'|'.join(builders)}}}")
    sys.stdout.write(dump(builders[which]()))
