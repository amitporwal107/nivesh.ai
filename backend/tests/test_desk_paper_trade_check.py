"""POST /api/desk/paper-trades/check — the risk service's decision for a paper trade that is NOT submitted (Strategy Lab ›
Build a trade, the Checks card and the paper gates). Same harness as tests/test_desk_strategy_trades.py (in-memory Mongo,
the clock fixed at 2026-10-12 10:30 IST, the loosest allowed profile, a fake exchange-lot reference).

What must hold: the body is validated exactly as the POST validates it (same 422 detail); the decision is the risk
service's own (`decide`, the code the POST runs), passed through as allow / reduce / block with its reasons and sizes;
NOTHING is written to any collection (no trade, no risk_decisions row, no refusal record, no reservation); an open
duplicate is reported, not refused. MOCK — not real data: FIXU / FIXA and every price are made up.
"""
from __future__ import annotations

from typing import Dict, Tuple

from routes import desk_trading as route
from services.risk_gate import service as risk_service
from tests.test_desk_strategy_trades import (  # noqa: F401  (`sworld`, `world` and `api` are fixtures)
    A, TRADES_URL, api, call, open_strategy, strategy_body, sworld, trade_body, world,
)

CHECK_URL = f"{TRADES_URL}/check"


def _state(w) -> Dict[str, Tuple[int, int]]:
    """Every collection's document count and write count: the check must leave both unchanged."""
    return {name: (len(col.docs), col.writes) for name, col in w.db.cols.items()}


def test_needs_a_signed_in_user(api, sworld):
    assert api.post(CHECK_URL, json=strategy_body()).status_code == 401


def test_allow_for_a_structure_passes_the_decision_through_and_writes_nothing(api, sworld):
    before = _state(sworld)
    r = api.post(CHECK_URL, json=strategy_body(), headers=A)
    assert r.status_code == 200, r.text
    b = r.json()
    assert (b["checked"], b["recorded"], b["sent_to_broker"]) == (True, False, False)
    assert b["outcome"] == "allow"
    assert b["requested_lots"] == 1 and b["approved_lots"] == 1
    assert b["estimated_risk_rs"]["total"] > 0 and b["policy_version"] == risk_service.POLICY_VERSION
    assert isinstance(b["reasons"], list) and b["duplicate"] is None
    assert "nothing was recorded or reserved" in b["basis"]
    assert _state(sworld) == before
    # The POST, deciding on the same book, agrees: the structure is recorded.
    assert api.post(TRADES_URL, json=strategy_body(), headers=A).status_code == 201


def test_block_passes_the_reasons_through_and_writes_nothing(api, sworld, risk_mock_inputs):
    risk_mock_inputs["market_error"] = "MOCK: the market state could not be read"     # the service fails closed
    before = _state(sworld)
    b = api.post(CHECK_URL, json=strategy_body(), headers=A).json()
    assert b["outcome"] == "block"
    blocking = [x for x in b["reasons"] if x["severity"] in risk_service.BLOCKING]
    assert blocking and all(x["code"] and x["message"] for x in blocking)
    assert _state(sworld) == before
    # The POST refuses the same body with the same blocking codes.
    r = api.post(TRADES_URL, json=strategy_body(), headers=A)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "risk_blocked"
    assert {x["code"] for x in r.json()["detail"]["reasons"] if x["severity"] in risk_service.BLOCKING} == \
        {x["code"] for x in blocking}


def test_reduce_passes_the_approved_size_through(api, sworld, monkeypatch):
    """A reduce is the service's own answer; here `decide` is replaced to return one, so the test proves the route
    passes the sizes and reasons through untouched. MOCK decision."""
    seen = {}

    def fake_decide(req, snap):
        seen["req"] = req
        return {"outcome": "reduce", "requested_lots": 3, "approved_lots": 1, "requested_qty": None, "approved_qty": None,
                "reasons": [{"code": "per_trade_risk", "check": "per_trade", "severity": "reduce",
                             "message": "MOCK: at most 1 lot per leg fits the per-trade budget."}],
                "estimated_risk_rs": {"total": 1234.0}, "budget": {"per_trade_budget_rs": 1500.0},
                "limits_version": "mock-1", "freshness": {}}
    monkeypatch.setattr(risk_service, "decide", fake_decide)
    before = _state(sworld)
    legs = [call("buy", 1300, 40, lots=3), call("sell", 1360, 15, lots=3)]
    b = api.post(CHECK_URL, json=strategy_body(legs=legs), headers=A).json()
    assert (b["outcome"], b["requested_lots"], b["approved_lots"]) == ("reduce", 3, 1)
    assert b["reasons"][0]["code"] == "per_trade_risk" and b["estimated_risk_rs"] == {"total": 1234.0}
    assert seen["req"].instrument == "structure" and seen["req"].symbol == "FIXU" and len(seen["req"].legs) == 2
    assert _state(sworld) == before


def test_a_bad_body_is_the_posts_422_and_writes_nothing(api, sworld):
    before = _state(sworld)
    r = api.post(CHECK_URL, json=strategy_body(direction="sideways"), headers=A)
    assert (r.status_code, r.json()["detail"]) == (422, "invalid_direction")
    assert api.post(TRADES_URL, json=strategy_body(direction="sideways"), headers=A).json()["detail"] == "invalid_direction"
    r = api.post(CHECK_URL, content=b"not json", headers={**A, "Content-Type": "application/json"})
    assert (r.status_code, r.json()["detail"]) == (422, "invalid_body")
    r = api.post(CHECK_URL, json={**trade_body(), "kind": "bond"}, headers=A)
    assert (r.status_code, r.json()["detail"]) == (422, "invalid_kind")
    # The exchange lot is checked as the POST checks it (fails closed on a made-up lot size).
    legs = [call("buy", 1300, 40, lot_size=1), call("sell", 1360, 15, lot_size=1)]
    r = api.post(CHECK_URL, json=strategy_body(legs=legs), headers=A)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "lot_size_mismatch"
    # The POST's refusals are recorded; the check's are not: only the two POSTs above wrote anything.
    after = _state(sworld)
    assert after[route.svc.TRADES] == before[route.svc.TRADES]
    assert all(after[k] == before[k] for k in before if k != route.rc.DECISIONS)


def test_an_open_duplicate_is_reported(api, sworld):
    t = open_strategy(api)
    b = api.post(CHECK_URL, json=strategy_body(), headers=A).json()
    assert b["duplicate"]["existing_trade_id"] == t["id"] and "already have this structure open" in b["duplicate"]["message"]
    assert b["recorded"] is False


def test_a_cash_body_is_checked_too(api, sworld):
    before = _state(sworld)
    b = api.post(CHECK_URL, json=trade_body(), headers=A).json()
    assert b["outcome"] in ("allow", "reduce", "block") and b["requested_qty"] == 10
    assert _state(sworld) == before
