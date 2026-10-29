"""The trade plan card's payoff, today and at expiry (frontend decision/PlanPayoff.tsx): the request the card sends for an
options plan, through the REAL POST /api/desk/strategy/payoff, pinned in frontend-v5/e2e/fixtures/contract-plan-payoff.json.

The Playwright spec copilot-app-desk-plan-payoff.spec.ts checks that the browser posts exactly `request` and answers with
`response`; this file checks that `response` is what the real route returns for that body, so neither side can drift
silently (a mocked answer once hid a backend 422: the request body is tested against the backend too).

The plan is the F&O plan of contract-decision-card.json (the REAL 2026-10-21 BANKNIFTY capture: a bear put spread
55000/54100, expiry 2026-10-27), sized by the risk service at 1 lot per leg. `today` is fixed: 2026-10-22 (before the
expiry: the estimate is asked for) and 2026-10-27 (the expiry day: it is not).

    CONTRACT_FIXTURES_OUT=<dir> python -m pytest tests/test_plan_payoff_contract.py -q
        writes <dir>/contract-plan-payoff.json; copy it into frontend-v5/e2e/fixtures/
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import routes.strategy_plan as route

FIXTURES = Path(__file__).resolve().parents[2] / "frontend-v5" / "e2e" / "fixtures"
URL = "/api/desk/strategy/payoff"
STEP_PCT = 0.125
TODAY = "2026-10-22"
EXPIRY_DAY = "2026-10-27"


def plan_payoff_request(tp: Dict[str, Any], lots_per_leg: Optional[int], today: str) -> Dict[str, Any]:
    """The body PlanPayoff.tsx planPayoffRequest builds (the spec compares the browser's body with this one)."""
    legs = tp["instrument"]["legs"]
    ref = tp["entry"]["reference_close"]
    prices = [l.get("strike") for l in legs] + [tp["stop"].get("price")] + [t.get("price") for t in tp["targets"]]
    far = max([0.0] + [abs(p / ref - 1) * 100 for p in prices if p is not None])
    rng = min(20, max(3, math.ceil(far * 1.5) + 1))
    expiry = sorted(l["expiry"] for l in legs if l.get("expiry"))[0]
    as_of = (tp.get("data_as_of") or {}).get("chain") or (tp.get("data_as_of") or {}).get("fno")
    same = len({l.get("lots") or 1 for l in legs}) == 1
    lots = lots_per_leg if lots_per_leg and same else None
    body: Dict[str, Any] = {
        "underlying": tp["instrument"]["symbol"], "reference_price": ref, **({"as_of": as_of} if as_of else {}),
        "legs": [{"kind": l["kind"], "side": l["side"], "quantity": lots or l.get("lots") or 1, "lot_size": l["lot_size"],
                  "entry_price": l["entry_price"], "expiry": l["expiry"], "strike": l["strike"], "option_type": l["option_type"],
                  "price_source": l["price_source"]} for l in legs],
        "grid": {"from_pct": -rng, "to_pct": rng, "points": round(2 * rng / STEP_PCT) + 1},
    }
    if today < expiry and (as_of is None or as_of <= today):
        body["pre_expiry"] = {"date": today}
    return body


def _post(monkeypatch, body: Dict[str, Any]) -> Dict[str, Any]:
    async def fake_user(request: Request):
        return {"user_id": "u1", "email": "u1@example.com"}
    monkeypatch.setattr(route, "get_current_user", fake_user)
    app = FastAPI()
    app.include_router(route.router)
    res = TestClient(app).post(URL, json=body)
    assert res.status_code == 200, res.text
    return res.json()


def build(monkeypatch) -> Dict[str, Any]:
    card = json.loads((FIXTURES / "contract-decision-card.json").read_text(encoding="utf-8"))
    got = card["fno"]["trade_plan_response"]
    tp, lots = got["plan"], got["account_size"]["lots"]
    before = plan_payoff_request(tp, lots, TODAY)
    on_expiry = plan_payoff_request(tp, lots, EXPIRY_DAY)
    return {
        "about": ("The trade plan card's payoff today and at expiry (decision/PlanPayoff.tsx) for the F&O plan of "
                  "contract-decision-card.json (REAL 2026-10-21 BANKNIFTY capture), at the risk service's 1 lot per leg. "
                  "request/response: today 2026-10-22 (the estimate is asked for); request_on_expiry/response_on_expiry: "
                  "today 2026-10-27, the expiry day (it is not). Every response is the REAL route's answer "
                  "(backend tests/test_plan_payoff_contract.py builds and checks this file)."),
        "plan_id": tp["plan_id"], "today": TODAY, "expiry_day": EXPIRY_DAY,
        "request": before, "response": _post(monkeypatch, before),
        "request_on_expiry": on_expiry, "response_on_expiry": _post(monkeypatch, on_expiry),
    }


def _moves(rng: float) -> List[float]:
    return [k * rng / 4 for k in range(-4, 5)]


def test_the_fixture_is_what_the_route_returns(monkeypatch):
    built = build(monkeypatch)
    out = os.environ.get("CONTRACT_FIXTURES_OUT")
    if out:
        Path(out, "contract-plan-payoff.json").write_text(json.dumps(built, indent=1, ensure_ascii=True) + "\n", encoding="utf-8")
    saved = json.loads((FIXTURES / "contract-plan-payoff.json").read_text(encoding="utf-8"))
    assert saved == built


def test_before_the_expiry_both_lines_on_one_grid_with_every_table_move_on_it(monkeypatch):
    built = build(monkeypatch)
    req, r = built["request"], built["response"]
    assert r["valid"] is True and r["problems"] == [] and r["sent_to_broker"] is False
    assert req["pre_expiry"] == {"date": TODAY} and req["grid"] == {"from_pct": -4, "to_pct": 4, "points": 65}
    ex, pre = r["expiry"], r["pre_expiry"]
    assert pre is not None and pre["date"] == TODAY and pre["unavailable"] == []
    assert pre["grid"] == ex["grid"] and len(ex["grid"]) == 65 and len(pre["net"]) == 65
    ref = req["reference_price"]
    for m in _moves(4):
        i = round((m + 4) / STEP_PCT)
        assert abs(ex["grid"][i] - ref * (1 + m / 100)) <= 0.02, (m, ex["grid"][i])
    # A bear put spread 55000/54100 at 30 per lot, 292.30 paid per unit: at expiry the most it makes is
    # (900 − 292.30) × 30 = 18,231 and the most it loses 292.30 × 30 = 8,769, before charges.
    assert ex["max_profit"] == 18231.0 and ex["max_loss"] == -8769.0
    # Today the options still hold time value, so the two lines differ.
    assert any(abs(a - b) > 1 for a, b in zip(pre["net"], ex["net"]))


def test_on_the_expiry_day_no_estimate_is_asked_and_none_is_given(monkeypatch):
    built = build(monkeypatch)
    assert "pre_expiry" not in built["request_on_expiry"]
    r = built["response_on_expiry"]
    assert r["valid"] is True and r["pre_expiry"] is None and r["expiry"]["grid"] == built["response"]["expiry"]["grid"]
