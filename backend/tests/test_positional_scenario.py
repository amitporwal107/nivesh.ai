"""Trade scenario calculator — GET /api/positional/scenario (routes/positional.py, PRD §8.5 and §8.6, desk default D6).

One rule, on the server, beside `_size_position`. Pure: no database, no broker, nothing is stored or sent.

Worked example (LONG, the desk fixture's pick): entry ₹505, stop ₹480, target ₹555, capital ₹5,00,000, risk 1%, max
allocation 25%, costs from the strategy_engine model (0.05% slippage + ₹20 brokerage per side), the model a paper trade
records. Sized so the loss at the stop AFTER costs fits the budget (paper_fills_pnl TESTCASES C-2; it used to be
floor(5,000 / 25) = 200 shares, whose net loss at the stop was ₹5,138.50, over the ₹5,000 budget):
    risk per share      505 − 480 = 25            reward per share   555 − 505 = 50        reward : risk  50 / 25 = 2.0
    risk budget         5,00,000 × 1% = 5,000
    costs per share     (505 + 480) × 0.05% = 0.4925 at the stop, plus 2 × ₹20 brokerage
    qty by risk         floor((5,000 − 40) / (25 + 0.4925)) = floor(194.57) = 194
    qty by allocation   floor(5,00,000 × 25% / 505) = floor(247.52) = 247              → quantity 194 (risk budget binds)
    gross exposure      194 × 505 = 97,970         allocation         97,970 / 5,00,000 = 19.594%
    entry costs         97,970 × 0.05% + 20 = 48.985 + 20 = 68.985
    exit at the stop    194 × 480 = 93,120 × 0.05% + 20 = 46.56 + 20 = 66.56        round trip 135.545
    exit at the target  194 × 555 = 1,07,670 × 0.05% + 20 = 53.835 + 20 = 73.835   round trip 142.82
    loss at the stop    194 × 25 = 4,850 gross     4,985.545 net of costs (≤ 5,000)
    profit at target    194 × 50 = 9,700 gross     9,557.18 net of costs

Portfolio (§8.6), portfolio ₹10,00,000 holding ₹50,000 of the stock and ₹1,50,000 in its sector, the buy added as new money:
    stock weight        5.0% → (50,000 + 97,970) / 10,97,970 = 13.4767%
    sector weight       15.0% → (1,50,000 + 97,970) / 10,97,970 = 22.5844%
    impact at the stop  −4,985.545 / 10,00,000        at the target  +9,557.18 / 10,00,000
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
    assert s["qty_by_risk"] == 194 and s["qty_by_allocation"] == 247 and s["qty_by_max"] is None
    assert s["quantity"] == 194 and s["binding"] == "risk_budget"
    assert s["gross_exposure"] == 97_970.0
    assert s["allocation_pct"] == pytest.approx(19.594)
    assert "after the entry and stop-exit costs" in s["risk_basis"]
    c = r["costs"]
    assert c["entry"] == pytest.approx(68.985, abs=0.006)           # rounded to the paisa
    assert c["exit_at_stop"] == pytest.approx(66.56) and c["round_trip_at_stop"] == pytest.approx(135.545, abs=0.006)
    assert c["exit_at_target"] == pytest.approx(73.835, abs=0.006) and c["round_trip_at_target"] == pytest.approx(142.82)
    o = r["outcomes"]
    assert o["loss_at_stop"] == pytest.approx(4_850.0) and o["loss_at_stop_net"] == pytest.approx(4_985.545, abs=0.006)
    assert o["loss_at_stop_net"] <= s["risk_budget"]                       # gate 4: the net loss fits the budget
    assert o["profit_at_target"] == pytest.approx(9_700.0) and o["profit_at_target_net"] == pytest.approx(9_557.18)
    assert r["portfolio"] is None


def test_cost_model_is_the_strategy_engine_default():
    r = _calc()
    cm = r["cost_model"]
    assert cm["slippage_pct_per_side"] == pytest.approx(DEFAULT_SLIPPAGE_PCT * 100)      # 0.05 (percent units)
    assert cm["brokerage_inr_per_side"] == pytest.approx(DEFAULT_BROKERAGE_INR)          # ₹20
    assert "strategy_engine" in cm["source"]
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
    assert r["outcomes"]["loss_at_stop"] == pytest.approx(4_850.0)


# ── costs are inputs ─────────────────────────────────────────────────────────

def test_zero_costs_make_net_equal_gross():
    r = _calc(slippage_pct=0.0, brokerage_per_side=0.0)
    assert r["sizing"]["quantity"] == 200                # with no costs, floor(5,000 / 25) as before
    assert r["costs"]["round_trip_at_stop"] == 0 and r["costs"]["round_trip_at_target"] == 0
    assert r["outcomes"]["loss_at_stop_net"] == r["outcomes"]["loss_at_stop"]
    assert r["outcomes"]["profit_at_target_net"] == r["outcomes"]["profit_at_target"]


def test_custom_costs():
    r = _calc(slippage_pct=0.1, brokerage_per_side=0.0)
    # The custom costs size too: floor(5,000 / (25 + 985 × 0.1%)) = floor(192.4) = 192 shares.
    # entry 96,960 × 0.1% = 96.96; stop exit 92,160 × 0.1% = 92.16; target exit 1,06,560 × 0.1% = 106.56
    assert r["sizing"]["quantity"] == 192
    assert r["costs"]["entry"] == pytest.approx(96.96)
    assert r["costs"]["round_trip_at_stop"] == pytest.approx(189.12)
    assert r["outcomes"]["loss_at_stop_net"] == pytest.approx(192 * 25 + 189.12) and r["outcomes"]["loss_at_stop_net"] <= 5_000
    assert r["outcomes"]["profit_at_target_net"] == pytest.approx(192 * 50 - 203.52)
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
    r = _calc(lot_size=30)                               # 194 → 180, the largest multiple of 30
    assert r["sizing"]["quantity"] == 180 and r["sizing"]["binding"] == "lot_size"
    r = _calc(lot_size=2)                                # 194 is already a multiple: the risk budget still binds
    assert r["sizing"]["quantity"] == 194 and r["sizing"]["binding"] == "risk_budget"


def test_risk_budget_in_rupees_without_capital():
    r = route._trade_scenario(entry=505.0, stop=480.0, target=555.0, risk_budget=2_000.0)
    assert r["valid"] is True
    # floor((2,000 − 40) / 25.4925) = 76 (80 on the gross distance before costs were counted)
    assert r["sizing"]["risk_budget"] == 2_000.0 and r["sizing"]["quantity"] == 76
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
    assert p["stock_weight_after_pct"] == pytest.approx(147_970 / 1_097_970 * 100)
    assert p["stock_weight_change_pct"] == pytest.approx(147_970 / 1_097_970 * 100 - 5.0)
    assert p["sector_weight_before_pct"] == pytest.approx(15.0)
    assert p["sector_weight_after_pct"] == pytest.approx(247_970 / 1_097_970 * 100)
    assert p["impact_at_stop_pct"] == pytest.approx(-4_985.55 / 1_000_000 * 100, abs=1e-5)
    assert p["impact_at_target_pct"] == pytest.approx(9_557.18 / 1_000_000 * 100)
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
