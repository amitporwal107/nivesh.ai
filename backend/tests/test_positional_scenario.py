"""Trade scenario calculator — GET /api/positional/scenario (routes/positional.py, PRD §8.5 and §8.6, desk default D6).

One rule, on the server, beside `_size_position`. Pure: no database, no broker, nothing is stored or sent.

Worked example (LONG, the desk fixture's pick): entry ₹505, stop ₹480, target ₹555, capital ₹5,00,000, risk 1%, max
allocation 25%. Costs are the desk cost card desk-cost-v2 (services/desk_cost_card.py, equity delivery), the model a
paper trade records: ₹20 brokerage a side (a desk assumption), STT 0.1% both sides, NSE exchange 0.00307%, SEBI ₹10 a
crore, stamp 0.015% on the buy, GST 18% of brokerage + exchange + SEBI, slippage 0.05% a side; each component to the
paisa. Sized so the loss at the stop AFTER costs fits the budget (paper_fills_pnl TESTCASES C-2):
    risk per share      505 − 480 = 25            reward per share   555 − 505 = 50        reward : risk  50 / 25 = 2.0
    risk budget         5,00,000 × 1% = 5,000
    qty by risk         the most shares with 25 × q + costs(q) ≤ 5,000 → 186
    qty by allocation   floor(5,00,000 × 25% / 505) = floor(247.52) = 247              → quantity 186 (risk budget binds)
    gross exposure      186 × 505 = 93,930         allocation         93,930 / 5,00,000 = 18.786%
    entry (buy 93,930)  20 + STT 93.93 + exch 2.88 + SEBI 0.09 + stamp 14.09 + GST 4.13 + slippage 46.97 = 182.09
    exit at the stop    sell 89,280: 20 + 89.28 + 2.74 + 0.09 + 0 + 4.11 + 44.64 = 160.86      round trip 342.95
    exit at the target  sell 1,03,230: 20 + 103.23 + 3.17 + 0.10 + 0 + 4.19 + 51.62 = 182.31   round trip 364.40
    loss at the stop    186 × 25 = 4,650 gross     4,992.95 net of costs (≤ 5,000)
    profit at target    186 × 50 = 9,300 gross     8,935.60 net of costs
(Under the flat model, desk-flat-v1, it was 194 shares and a net loss of 4,985.545; on the gross distance, 200.)

Portfolio (§8.6), portfolio ₹10,00,000 holding ₹50,000 of the stock and ₹1,50,000 in its sector, the buy added as new money:
    stock weight        5.0% → (50,000 + 93,930) / 10,93,930
    sector weight       15.0% → (1,50,000 + 93,930) / 10,93,930
    impact at the stop  −4,992.95 / 10,00,000        at the target  +8,935.60 / 10,00,000
"""
from __future__ import annotations

import math

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import routes.positional as route
from services.strategy_engine.backtest import DEFAULT_BROKERAGE_INR, DEFAULT_SLIPPAGE_PCT

BASE = dict(entry=505.0, stop=480.0, target=555.0, capital=500_000.0, risk_pct=1.0, max_alloc_pct=25.0)


def _calc(**kw):
    args = {**BASE, **kw}
    return route._trade_scenario(**args)


def _codes(res, key="problems"):
    return [p["code"] for p in res[key]]


# ── the worked example ───────────────────────────────────────────────────────

def test_long_worked_example():
    r = _calc()
    assert r["valid"] is True and r["problems"] == []
    assert r["side"] == "long" and r["sent_to_broker"] is False
    ps = r["per_share"]
    assert ps == {"risk": 25.0, "reward": 50.0, "reward_to_risk": 2.0}
    s = r["sizing"]
    assert s["risk_budget"] == 5_000.0
    assert s["qty_by_risk"] == 186 and s["qty_by_allocation"] == 247 and s["qty_by_max"] is None
    assert s["quantity"] == 186 and s["binding"] == "risk_budget"
    assert s["gross_exposure"] == 93_930.0
    assert s["allocation_pct"] == pytest.approx(18.786)
    assert "after the entry and stop-exit costs" in s["risk_basis"]
    c = r["costs"]
    assert c["entry"] == 182.09
    assert c["exit_at_stop"] == 160.86 and c["round_trip_at_stop"] == 342.95
    assert c["exit_at_target"] == 182.31 and c["round_trip_at_target"] == 364.4
    assert c["breakdown_at_stop"] == {"brokerage": 40.0, "stt": 183.21, "exchange": 5.62, "sebi": 0.18, "stamp": 14.09,
                                      "gst": 8.24, "slippage": 91.61, "total": 342.95}
    o = r["outcomes"]
    assert o["loss_at_stop"] == pytest.approx(4_650.0) and o["loss_at_stop_net"] == 4_992.95
    assert o["loss_at_stop_net"] <= s["risk_budget"]                       # gate 4: the net loss fits the budget
    assert o["profit_at_target"] == pytest.approx(9_300.0) and o["profit_at_target_net"] == 8_935.6
    assert r["portfolio"] is None


def test_cost_model_is_the_strategy_engine_default():
    r = _calc()
    cm = r["cost_model"]
    assert cm["slippage_pct_per_side"] == pytest.approx(DEFAULT_SLIPPAGE_PCT * 100)      # 0.05 (percent units)
    assert cm["brokerage_inr_per_side"] == pytest.approx(DEFAULT_BROKERAGE_INR)          # ₹20
    assert cm["version"] == "desk-cost-v2" and "desk_cost_card" in cm["source"]
    assert "desk assumption" in cm["brokerage_basis"] and "spread" in cm["slippage_basis"]
    # The PRD's gap caveat travels with every answer.
    assert any("does not guarantee" in c for c in r["caveats"])


# ── direction and division by zero ───────────────────────────────────────────

def test_wrong_direction_is_reported_not_computed():
    r = _calc(stop=510.0)                                # stop above the entry
    assert r["valid"] is False and "stop_not_below_entry" in _codes(r)
    assert r["per_share"] is None and r["sizing"] is None and r["outcomes"] is None
    r = _calc(target=500.0)                              # target below the entry
    assert r["valid"] is False and "target_not_above_entry" in _codes(r)
    r = _calc(stop=510.0, target=500.0)                  # both at once: both problems, each on its own field
    assert set(_codes(r)) >= {"stop_not_below_entry", "target_not_above_entry"}
    assert {p["field"] for p in r["problems"]} >= {"stop", "target"}


def test_zero_risk_never_divides_by_zero():
    r = _calc(stop=505.0)                                # entry == stop: no risk per share
    assert r["valid"] is False and "stop_not_below_entry" in _codes(r)
    assert r["per_share"] is None


def test_target_is_optional():
    r = _calc(target=None)
    assert r["valid"] is True
    assert r["per_share"]["reward"] is None and r["per_share"]["reward_to_risk"] is None
    assert r["outcomes"]["profit_at_target"] is None and r["outcomes"]["profit_at_target_net"] is None
    assert r["costs"]["exit_at_target"] is None
    assert r["outcomes"]["loss_at_stop"] == pytest.approx(4_650.0)


# ── costs are inputs ─────────────────────────────────────────────────────────

def test_zero_slippage_and_brokerage_leave_only_the_statutory_charges():
    # Renamed from test_zero_costs_make_net_equal_gross: slippage and brokerage are inputs, the statutory charges (STT,
    # exchange, SEBI, stamp, GST) are not, so net never equals gross any more.
    r = _calc(slippage_pct=0.0, brokerage_per_side=0.0)
    b = r["costs"]["breakdown_at_stop"]
    assert (b["brokerage"], b["slippage"]) == (0.0, 0.0) and b["stt"] > 0 and b["stamp"] > 0
    assert r["sizing"]["quantity"] == 191 and r["costs"]["round_trip_at_stop"] == b["total"]
    assert r["outcomes"]["loss_at_stop_net"] == round(r["outcomes"]["loss_at_stop"] + b["total"], 2) <= 5_000


def test_custom_costs():
    r = _calc(slippage_pct=0.1, brokerage_per_side=0.0)
    # The custom slippage and brokerage size too (the statutory charges stay): 184 shares.
    # entry buy 184 × 505 = 92,920: 0 + STT 92.92 + exch 2.85 + SEBI 0.09 + stamp 13.94 + GST 0.53 + slippage 92.92 = 203.25
    assert r["sizing"]["quantity"] == 184
    assert r["costs"]["entry"] == 203.25
    assert r["costs"]["round_trip_at_stop"] == 383.19
    assert r["outcomes"]["loss_at_stop_net"] == round(184 * 25 + 383.19, 2) and r["outcomes"]["loss_at_stop_net"] <= 5_000
    assert r["outcomes"]["profit_at_target_net"] == round(184 * 50 - 411.31, 2)
    assert r["cost_model"]["slippage_pct_per_side"] == pytest.approx(0.1)


# ── position constraints ─────────────────────────────────────────────────────

def test_max_allocation_binds():
    r = _calc(max_alloc_pct=10.0)                        # floor(50,000 / 505) = 99
    assert r["sizing"]["qty_by_allocation"] == 99
    assert r["sizing"]["quantity"] == 99 and r["sizing"]["binding"] == "max_allocation"
    assert r["outcomes"]["loss_at_stop"] == pytest.approx(99 * 25)


def test_max_quantity_binds():
    r = _calc(max_qty=50)
    assert r["sizing"]["quantity"] == 50 and r["sizing"]["binding"] == "max_qty"


def test_lot_size_rounds_down():
    r = _calc(lot_size=30)                               # 186 → 180, the largest multiple of 30
    assert r["sizing"]["quantity"] == 180 and r["sizing"]["binding"] == "lot_size"
    r = _calc(lot_size=2)                                # 186 is already a multiple: the risk budget still binds
    assert r["sizing"]["quantity"] == 186 and r["sizing"]["binding"] == "risk_budget"


def test_risk_budget_in_rupees_without_capital():
    r = route._trade_scenario(entry=505.0, stop=480.0, target=555.0, risk_budget=2_000.0)
    assert r["valid"] is True
    # 73 after the card's costs (76 under the flat model, 80 on the gross distance)
    assert r["sizing"]["risk_budget"] == 2_000.0 and r["sizing"]["quantity"] == 73
    assert r["sizing"]["allocation_pct"] is None and r["sizing"]["qty_by_allocation"] is None


def test_needs_a_capital_or_a_risk_budget():
    r = route._trade_scenario(entry=505.0, stop=480.0, target=555.0)
    assert r["valid"] is False and "needs_capital_or_risk_budget" in _codes(r)
    r = route._trade_scenario(entry=505.0, stop=480.0, risk_pct=1.0)
    assert r["valid"] is False and "needs_capital_or_risk_budget" in _codes(r)


def test_budget_smaller_than_one_share():
    r = _calc(capital=2_000.0)                           # 1% = ₹20 < ₹25 a share
    assert r["valid"] is True and r["sizing"]["quantity"] == 0
    assert "no_whole_share" in _codes(r, "warnings")
    assert r["outcomes"] is None and r["costs"] is None


# ── §8.6: the portfolio ──────────────────────────────────────────────────────

def test_portfolio_impact():
    r = _calc(portfolio_value=1_000_000.0, existing_value=50_000.0, sector_value=150_000.0)
    p = r["portfolio"]
    assert p["stock_weight_before_pct"] == pytest.approx(5.0)
    assert p["stock_weight_after_pct"] == pytest.approx(143_930 / 1_093_930 * 100)
    assert p["stock_weight_change_pct"] == pytest.approx(143_930 / 1_093_930 * 100 - 5.0)
    assert p["sector_weight_before_pct"] == pytest.approx(15.0)
    assert p["sector_weight_after_pct"] == pytest.approx(243_930 / 1_093_930 * 100)
    assert p["impact_at_stop_pct"] == pytest.approx(-4_992.95 / 1_000_000 * 100)
    assert p["impact_at_target_pct"] == pytest.approx(8_935.6 / 1_000_000 * 100)
    assert "new money" in p["assumption"]


def test_portfolio_without_sector_figure():
    r = _calc(portfolio_value=1_000_000.0, existing_value=0.0)
    p = r["portfolio"]
    assert p["stock_weight_before_pct"] == 0.0 and p["sector_weight_before_pct"] is None
    assert p["sector_weight_after_pct"] is None


# ── the route ────────────────────────────────────────────────────────────────

def _client(monkeypatch):
    async def fake_user(request: Request):
        return {"user_id": "u1", "email": "u1@example.com"}
    monkeypatch.setattr(route, "get_current_user", fake_user)
    app = FastAPI()
    app.include_router(route.router)
    return TestClient(app)


def test_route_matches_the_function(monkeypatch):
    c = _client(monkeypatch)
    res = c.get("/api/positional/scenario", params={**BASE, "portfolio_value": 1_000_000, "existing_value": 50_000})
    assert res.status_code == 200
    body = res.json()
    want = _calc(portfolio_value=1_000_000.0, existing_value=50_000.0)
    assert body["sizing"] == want["sizing"] and body["outcomes"] == want["outcomes"]
    assert body["portfolio"]["stock_weight_after_pct"] == pytest.approx(want["portfolio"]["stock_weight_after_pct"])


def test_route_wrong_direction_is_200_with_problems(monkeypatch):
    c = _client(monkeypatch)
    res = c.get("/api/positional/scenario", params={**BASE, "stop": 600})
    assert res.status_code == 200 and res.json()["valid"] is False


@pytest.mark.parametrize("bad", [{"entry": 0}, {"entry": -5}, {"stop": "abc"}, {"max_alloc_pct": 150},
                                 {"risk_pct": 0}, {"side": "short"}, {"lot_size": 0}])
def test_route_rejects_malformed_inputs(monkeypatch, bad):
    c = _client(monkeypatch)
    res = c.get("/api/positional/scenario", params={**BASE, **bad})
    assert res.status_code == 422


def test_route_is_read_only(monkeypatch):
    """Nothing but GET is served: a scenario is never stored or sent anywhere."""
    c = _client(monkeypatch)
    assert c.post("/api/positional/scenario", params=BASE).status_code == 405


def test_results_are_finite_numbers():
    r = _calc()
    for block in ("per_share", "sizing", "costs", "outcomes"):
        for k, v in r[block].items():
            if isinstance(v, float):
                assert math.isfinite(v), (block, k)
