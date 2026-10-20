"""Strategy payoff engine (services/strategy_plan) and POST /api/desk/strategy/payoff: PRD §16.6, §17.4.

All fixtures are labelled MOCK — not real data: they are round numbers chosen so the arithmetic can be done by hand.
Expected values are worked in the comments, and Black-76 is checked against an independent closed form written in
this file (math.erf), not against the module under test.

Cost model (services/strategy_engine/backtest.py defaults): slippage 0.05% of traded value + ₹20 flat, each side, each leg.
"""
from __future__ import annotations

import math
from datetime import date

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import routes.strategy_plan as route
from services.option_pricing import RISK_FREE_RATE
from services.strategy_engine.backtest import DEFAULT_BROKERAGE_INR, DEFAULT_SLIPPAGE_PCT
from services.strategy_plan import compute_payoff
from services.strategy_plan import payoff as po
from services.strategy_plan import templates as tp

TODAY = date(2026, 10, 19)
EXP = "2026-11-26"          # 38 calendar days after TODAY


def leg(kind="option", side="buy", qty=1, lot=250, entry=40.0, strike=None, ot=None, expiry=EXP, **kw):
    if kind == "cash":
        lot, expiry = 1, None
    return {"kind": kind, "side": side, "quantity": qty, "lot_size": lot, "entry_price": entry, "expiry": expiry,
            "strike": strike, "option_type": ot, **kw}


def req(legs, grid=None, **kw):
    return {"underlying": "RELIANCE", "reference_price": 1215.0, "legs": legs,
            "grid": grid or {"min": 1000, "max": 1500, "points": 101}, **kw}


def run(legs, **kw):
    return compute_payoff(req(legs, **kw), TODAY)


def codes(r):
    return [p["code"] for p in r["problems"]]


def at(r, price, key="gross"):
    e = r["expiry"]
    return e[key][e["grid"].index(price)]


# ── linear instruments ───────────────────────────────────────────────────────

def test_cash_long_and_short():
    # 100 shares bought at 1215: +85 per share at 1300 = 8,500; at 1100 = -115 × 100 = -11,500.
    r = run([leg("cash", qty=100, entry=1215.0)], grid={"min": 1000, "max": 1500, "points": 101})
    assert r["valid"] and at(r, 1300.0) == 8500.0 and at(r, 1100.0) == -11500.0
    e = r["expiry"]
    assert e["profit_unbounded"] is True and e["loss_unbounded"] is False
    assert e["max_loss"] == -121500.0          # price 0: 1215 × 100
    assert e["breakevens"] == [1215.0] and e["net_premium"] == 0.0
    s = run([leg("cash", side="sell", qty=100, entry=1215.0)])
    assert at(s, 1300.0) == -8500.0
    assert s["expiry"]["loss_unbounded"] is True and s["expiry"]["profit_unbounded"] is False
    assert s["expiry"]["max_loss"] is None and s["expiry"]["max_profit"] == 121500.0
    assert s["capital_at_risk"] is None


def test_cash_cost_arithmetic():
    # entry 1215 × 100 = 121,500 × 0.0005 = 60.75 + 20 = 80.75 ; exit at 1300: 130,000 × 0.0005 = 65 + 20 = 85
    # round trip 165.75 ; net at 1300 = 8,500 − 165.75 = 8,334.25
    r = run([leg("cash", qty=100, entry=1215.0)])
    c = r["costs"]
    assert (DEFAULT_SLIPPAGE_PCT, DEFAULT_BROKERAGE_INR) == (0.0005, 20.0)
    assert c["entry"] == 80.75 and c["excluded"] and "STT" in c["excluded"]
    assert at(r, 1300.0, "net") == 8334.25


def test_long_future_with_lot_size_and_costs():
    # 2 lots × 250 = 500 units at 1215. At 1250: 35 × 500 = 17,500.
    # entry 1215 × 500 = 607,500 × .0005 = 303.75 + 20 = 323.75 ; exit 1250 × 500 = 625,000 × .0005 = 312.5 + 20 = 332.5
    # net = 17,500 − 656.25 = 16,843.75
    r = run([leg("future", qty=2, lot=250, entry=1215.0)])
    assert at(r, 1250.0) == 17500.0 and at(r, 1250.0, "net") == 16843.75
    e = r["expiry"]
    assert e["profit_unbounded"] and not e["loss_unbounded"]
    assert e["max_loss"] == -607500.0                   # bounded only by the price reaching 0
    assert r["loss_can_exceed_margin"] is True and r["margin"] is None and r["margin_reason"]
    assert any("exceed the initial margin" in c for c in r["caveats"]) and any("Margin is not the maximum loss" in c for c in r["caveats"])
    assert r["costs"]["entry"] == 323.75 and r["sent_to_broker"] is False


def test_short_future_unbounded_loss():
    r = run([leg("future", side="sell", qty=1, lot=250, entry=1215.0)])
    e = r["expiry"]
    assert e["loss_unbounded"] is True and e["profit_unbounded"] is False
    assert e["max_loss"] is None and e["max_profit"] == 303750.0
    assert at(r, 1100.0) == 28750.0 and at(r, 1300.0) == -21250.0
    assert r["capital_at_risk"] is None and any("no upper limit" in c for c in r["caveats"])


# ── options ──────────────────────────────────────────────────────────────────

def test_long_call_below_at_above():
    # Buy 1 lot (250) 1300 call at 40: cost 10,000. Below/at 1300: -10,000. 1340 = breakeven. 1400: (100−40) × 250 = 15,000.
    r = run([leg(side="buy", strike=1300.0, ot="call", entry=40.0)])
    assert at(r, 1000.0) == -10000.0 and at(r, 1300.0) == -10000.0 and at(r, 1400.0) == 15000.0
    e = r["expiry"]
    assert e["max_loss"] == -10000.0 and e["max_profit"] is None and e["profit_unbounded"] and not e["loss_unbounded"]
    assert e["breakevens"] == [1340.0] and e["net_premium"] == -10000.0
    # worthless at 1200: only the entry cost (40 × 250 = 10,000 × .0005 = 5 + 20 = 25), no exit cost
    assert at(r, 1200.0, "net") == -10025.0
    # capital at risk: 10,000 + entry 25 + conservative exit brokerage 20 at S where the exit value is 0 = 10,045
    assert r["capital_at_risk"] == 10045.0


def test_long_put():
    # Buy 1300 put at 30, lot 250: max loss 7,500 ; breakeven 1270 ; at 1100: (200 − 30) × 250 = 42,500
    r = run([leg(strike=1300.0, ot="put", entry=30.0)])
    e = r["expiry"]
    assert at(r, 1500.0) == -7500.0 and at(r, 1100.0) == 42500.0
    assert e["breakevens"] == [1270.0] and e["max_loss"] == -7500.0
    assert e["max_profit"] == (1300.0 - 30.0) * 250 and not e["profit_unbounded"]    # price 0


def test_bull_call_spread_worked():
    # Buy 1300C at 40, sell 1350C at 18. Net debit 22 × 250 = 5,500. Width 50: max profit (50 − 22) × 250 = 7,000.
    # Breakeven 1322. Entry costs: 40×250×.0005 + 20 = 25 ; 18×250×.0005 + 20 = 22.25 ; total 47.25
    # At 1400: exits 100×250×.0005+20 = 32.5 and 50×250×.0005+20 = 26.25 → 58.75 ; net = 7,000 − 47.25 − 58.75 = 6,894.00
    r = run([leg(side="buy", strike=1300.0, ot="call", entry=40.0), leg(side="sell", strike=1350.0, ot="call", entry=18.0)])
    e = r["expiry"]
    assert (e["max_loss"], e["max_profit"]) == (-5500.0, 7000.0)
    assert e["breakevens"] == [1322.0] and e["net_premium"] == -5500.0
    assert not e["profit_unbounded"] and not e["loss_unbounded"]
    assert at(r, 1000.0) == -5500.0 and at(r, 1300.0) == -5500.0 and at(r, 1350.0) == 7000.0 and at(r, 1500.0) == 7000.0
    assert at(r, 1400.0, "net") == 6894.0
    assert at(r, 1200.0, "net") == -5547.25
    assert r["costs"]["entry"] == 47.25
    assert [p["label"] for p in e["per_leg"]] == ["Buy 1 lot call 1300", "Sell 1 lot call 1350"]
    assert at(r, 1400.0) == sum(p["gross"][e["grid"].index(1400.0)] for p in e["per_leg"])


def test_bear_put_spread_and_bull_put_credit_spread():
    # Buy 1250P at 30, sell 1200P at 12: debit 18 × 250 = 4,500 ; max profit (50 − 18) × 250 = 8,000 ; breakeven 1232
    r = run([leg(strike=1250.0, ot="put", entry=30.0), leg(side="sell", strike=1200.0, ot="put", entry=12.0)])
    e = r["expiry"]
    assert (e["max_loss"], e["max_profit"], e["breakevens"]) == (-4500.0, 8000.0, [1232.0])
    # Credit: sell 1250P at 30, buy 1200P at 12: credit 18 × 250 = 4,500 ; max loss 8,000 ; same breakeven
    c = run([leg(side="sell", strike=1250.0, ot="put", entry=30.0), leg(strike=1200.0, ot="put", entry=12.0)])
    e = c["expiry"]
    assert c["valid"] and (e["max_loss"], e["max_profit"], e["breakevens"]) == (-8000.0, 4500.0, [1232.0])
    assert e["net_premium"] == 4500.0


def test_iron_condor():
    # lot 50: buy 1100P at 5, sell 1150P at 15, sell 1250C at 14, buy 1300C at 4: credit 20 × 50 = 1,000.
    # max loss (50 − 20) × 50 = 1,500 ; breakevens 1130 and 1270
    legs = [leg(lot=50, strike=1100.0, ot="put", entry=5.0), leg(lot=50, side="sell", strike=1150.0, ot="put", entry=15.0),
            leg(lot=50, side="sell", strike=1250.0, ot="call", entry=14.0), leg(lot=50, strike=1300.0, ot="call", entry=4.0)]
    r = run(legs)
    e = r["expiry"]
    assert (e["max_profit"], e["max_loss"]) == (1000.0, -1500.0) and e["breakevens"] == [1130.0, 1270.0]
    assert e["net_premium"] == 1000.0
    for price, want in [(1000.0, -1500.0), (1100.0, -1500.0), (1150.0, 1000.0), (1200.0, 1000.0), (1250.0, 1000.0), (1300.0, -1500.0), (1500.0, -1500.0)]:
        assert at(r, price) == want, price
    assert r["capital_at_risk"] >= 1500.0


def test_options_plus_cash_and_future_are_summed():
    # long 100 shares at 1215 + long 1300 put at 30 on 250: protective-put style; just check the sum rule at 1100
    r = run([leg("cash", qty=100, entry=1215.0), leg(strike=1300.0, ot="put", entry=30.0)])
    assert at(r, 1100.0) == (1100 - 1215) * 100 + (200 - 30) * 250


def test_covered_structures_are_accepted():
    # short call covered by a long future of equal units: upside slope 0
    r = run([leg("future", entry=1215.0), leg(side="sell", strike=1300.0, ot="call", entry=20.0)])
    assert r["valid"] and not r["expiry"]["loss_unbounded"]


def test_breakeven_exact_vs_grid_spacing():
    # Grid step 5 does not hit 1322: breakeven is still exact by interpolation of the linear segment.
    r = run([leg(strike=1300.0, ot="call", entry=40.0), leg(side="sell", strike=1350.0, ot="call", entry=18.0)],
            grid={"min": 1000, "max": 1500, "points": 101})
    assert r["expiry"]["breakevens"] == [1322.0]
    r2 = run([leg(strike=1300.0, ot="call", entry=40.0), leg(side="sell", strike=1350.0, ot="call", entry=18.0)],
             grid={"min": 1001, "max": 1499, "points": 7})
    assert r2["expiry"]["breakevens"] == [1322.0]


def test_zeros_touch_and_flat():
    xs = [0.0, 5.0, 10.0]
    assert po.zeros(xs, lambda x: abs(x - 5.0)) == ([5.0], False)             # touches zero, never crosses
    z, flat = po.zeros([0.0, 5.0, 10.0, 15.0], lambda x: 0.0 if x <= 10 else x - 10)
    assert flat is True and z == []                                           # flat stretch has no single breakeven
    assert po.zeros([0.0, 10.0], lambda x: x - 4.0)[0] == [4.0]


def test_scenarios():
    r = run([leg(strike=1300.0, ot="call", entry=40.0), leg(side="sell", strike=1350.0, ot="call", entry=18.0)],
            scenarios=[{"name": "conservative", "underlying_price": 1400}, {"name": "worthless", "underlying_price": 1200}])
    s = r["expiry"]["scenarios"]
    assert s[0] == {"name": "conservative", "underlying_price": 1400.0, "gross": 7000.0, "net": 6894.0}
    assert s[1]["gross"] == -5500.0 and s[1]["net"] == -5547.25


def test_costs_from_request_and_reproducible():
    legs = [leg("future", entry=1215.0)]
    a = run(legs, costs={"slippage_pct": 0.1, "brokerage_per_side": 0})
    # entry 1215 × 250 = 303,750 × .001 = 303.75 ; exit at 1250: 312,500 × .001 = 312.5 ; net = 8,750 − 616.25
    assert at(a, 1250.0, "net") == 8133.75
    assert run(legs, costs={"slippage_pct": 0.1, "brokerage_per_side": 0}) == a


# ── undefined-risk guard ─────────────────────────────────────────────────────

@pytest.mark.parametrize("legs", [
    [leg(side="sell", strike=1300.0, ot="call", entry=20.0)],                                              # naked short call
    [leg(side="sell", strike=1300.0, ot="put", entry=20.0)],                                               # naked short put
    [leg(strike=1300.0, ot="call", entry=40.0), leg(side="sell", qty=2, strike=1350.0, ot="call", entry=18.0)],   # ratio: net short call
    [leg(side="sell", strike=1300.0, ot="put", entry=20.0), leg("future", entry=1215.0)],                  # short put, no long put
    [leg("future", side="sell", entry=1215.0), leg(strike=1300.0, ot="put", entry=20.0), leg(side="sell", qty=2, strike=1400.0, ot="call", entry=5.0)],
])
def test_undefined_risk_rejected(legs):
    r = run(legs)
    assert r["valid"] is False and "undefined_risk_not_supported" in codes(r) and r["expiry"] is None


def test_far_upside_numeric_matches_the_analytic_flags():
    for legs, unb in [([leg(strike=1300.0, ot="call", entry=40.0)], "profit"),
                      ([leg("future", side="sell", entry=1215.0)], "loss"),
                      ([leg(strike=1300.0, ot="call", entry=40.0), leg(side="sell", strike=1350.0, ot="call", entry=18.0)], None)]:
        r = run(legs)
        parsed = __import__("services.strategy_plan.model", fromlist=["x"]).parse_request(req(legs), TODAY)["legs"]
        far, farther = po.gross(parsed, 1e7), po.gross(parsed, 2e7)
        e = r["expiry"]
        assert e["profit_unbounded"] == (unb == "profit") == (farther > far)
        assert e["loss_unbounded"] == (unb == "loss") == (farther < far)


# ── validation ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("bad,code", [
    ({"entry_price": 0}, "bad_price"), ({"entry_price": -1}, "bad_price"), ({"entry_price": "10"}, "bad_price"),
    ({"quantity": 1.5}, "bad_quantity"), ({"quantity": 0}, "bad_quantity"), ({"lot_size": 0}, "bad_lot_size"),
    ({"strike": None}, "bad_strike"), ({"option_type": "straddle"}, "bad_option_type"), ({"expiry": None}, "bad_expiry"),
    ({"expiry": "2026-10-01"}, "expiry_in_past"), ({"kind": "swap"}, "bad_kind"), ({"side": "hold"}, "bad_side"),
    ({"iv_pct": -3}, "bad_iv"),
])
def test_leg_problems(bad, code):
    base = leg(strike=1300.0, ot="call", entry=40.0)
    base.update(bad)
    r = run([base])
    assert r["valid"] is False and code in codes(r), r["problems"]
    assert r["expiry"] is None


def test_structure_problems():
    assert "mixed_expiries_not_supported" in codes(run([leg(strike=1300.0, ot="call"), leg(side="sell", strike=1350.0, ot="call", expiry="2026-12-31")]))
    assert "no_legs" in codes(run([]))
    assert "cash_lot_size" in codes(run([{**leg("cash", entry=10.0), "lot_size": 5}]))
    mixed = leg(strike=1300.0, ot="call"); mixed["underlying"] = "TCS"
    assert "mixed_underlyings" in codes(run([mixed]))
    assert "too_many_legs" in codes(run([leg("cash")] * 9))
    r = compute_payoff({"legs": [leg("cash")]}, TODAY)
    assert {"bad_underlying", "bad_price"} <= set(codes(r))


@pytest.mark.parametrize("grid,code", [
    ({"min": 1000, "max": 1500, "points": 4}, "bad_grid_points"), ({"min": 1000, "max": 1500, "points": 401}, "bad_grid_points"),
    ({"min": 1500, "max": 1000, "points": 50}, "grid_order"), ({"min": 1000, "max": 1000, "points": 50}, "grid_order"),
    ({"min": 0, "max": 1500, "points": 50}, "grid_not_positive"), ({"min": -5, "max": 10, "points": 50}, "grid_not_positive"),
    ({"points": 50}, "bad_grid"), ("wide", "bad_grid"),
])
def test_grid_problems(grid, code):
    assert code in codes(run([leg("cash")], grid=grid))


def test_grid_edges_and_pct():
    ok = run([leg("cash")], grid={"min": 1000, "max": 1500, "points": 5})
    assert ok["valid"] and ok["expiry"]["grid"] == [1000.0, 1125.0, 1250.0, 1375.0, 1500.0]
    assert run([leg("cash")], grid={"min": 1000, "max": 1500, "points": 400})["valid"]
    pct = run([leg("cash")], grid={"from_pct": -10, "to_pct": 10, "points": 5})
    assert pct["expiry"]["grid"][0] == 1093.5 and pct["expiry"]["grid"][-1] == 1336.5
    d = compute_payoff({"underlying": "X", "reference_price": 1000, "legs": [leg("cash")]}, TODAY)
    assert d["valid"] and "grid_defaulted" in [w["code"] for w in d["warnings"]] and len(d["expiry"]["grid"]) == 121


def test_garbage_never_raises():
    for body in [None, [], "x", 5, {}, {"legs": "x"}, {"legs": [None, 3, "a"], "underlying": 5, "grid": 4},
                 {"underlying": "X", "reference_price": float("nan"), "legs": [leg("cash")]},
                 {"underlying": "X", "reference_price": 10, "legs": [leg("cash")], "costs": "free", "scenarios": 5, "pre_expiry": []}]:
        r = compute_payoff(body, TODAY)
        assert r["valid"] is False and r["problems"] and r["sent_to_broker"] is False


def test_breakeven_outside_grid_warns():
    r = run([leg(strike=1300.0, ot="call", entry=40.0)], grid={"min": 1000, "max": 1300, "points": 50})
    assert r["expiry"]["breakevens"] == [] and "breakeven_outside_grid" in [w["code"] for w in r["warnings"]]


# ── pre-expiry (Black-76) ────────────────────────────────────────────────────

def _cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def b76(kind, s, k, days, vol, r=RISK_FREE_RATE):
    """Independent closed form: Black-76 on the carried-spot forward F = S e^{rT}."""
    t = days / 365.0
    f = s * math.exp(r * t)
    d1 = (math.log(f / k) + 0.5 * vol * vol * t) / (vol * math.sqrt(t))
    d2 = d1 - vol * math.sqrt(t)
    df = math.exp(-r * t)
    return df * (f * _cdf(d1) - k * _cdf(d2)) if kind == "call" else df * (k * _cdf(-d2) - f * _cdf(-d1))


PRE = {"date": "2026-10-26", "iv_shift_pct": 0, "rate_pct": 5.75}      # 31 days to 2026-11-26
G5 = {"min": 1000, "max": 1500, "points": 5}                           # 1000, 1125, 1250, 1375, 1500
CALL = dict(strike=1300.0, ot="call", entry=30.0, iv_pct=25.0)


def test_pre_expiry_matches_independent_black76():
    r = run([leg(**CALL)], grid=G5, pre_expiry=PRE)
    p = r["pre_expiry"]
    assert p["model"] == "Black-76" and p["unavailable"] == [] and p["assumptions"]["rate_pct"] == 5.75
    assert p["assumptions"]["legs"][0]["time_to_expiry_days"] == 31
    for i, s in enumerate(p["grid"]):
        want = (b76("call", s, 1300.0, 31, 0.25) - 30.0) * 250
        assert p["gross"][i] == pytest.approx(want, abs=0.01), s
    # not the expiry payoff
    assert p["gross"] != r["expiry"]["gross"]
    # net subtracts entry (30 × 250 = 7,500 × .0005 = 3.75 + 20) and the exit at the modelled value, never less than gross − costs
    s = p["grid"][2]
    px = b76("call", s, 1300.0, 31, 0.25)
    cost = (3.75 + 20) + (px * 250 * 0.0005 + 20)
    assert p["net"][2] == pytest.approx(p["gross"][2] - cost, abs=0.02)


def test_pre_expiry_greeks_against_finite_differences():
    legs = [leg(**CALL)]
    ref_grid = {"min": 1215, "max": 1300, "points": 5}           # first point is the reference price
    r = run(legs, grid=ref_grid, pre_expiry=PRE)
    g = r["pre_expiry"]["greeks"]
    px = lambda s, d, v=0.25, rr=RISK_FREE_RATE: b76("call", s, 1300.0, d, v, rr) * 250
    h = 0.5
    assert g["delta"] == pytest.approx((px(1215 + h, 31) - px(1215 - h, 31)) / (2 * h), abs=1e-3)
    assert g["gamma"] == pytest.approx((px(1215 + h, 31) - 2 * px(1215, 31) + px(1215 - h, 31)) / h ** 2, abs=1e-3)
    assert g["vega"] == pytest.approx(px(1215, 31, 0.26) - px(1215, 31, 0.25), rel=0.02)
    assert g["theta"] == pytest.approx(px(1215, 30) - px(1215, 31), abs=1e-3) and g["theta"] < 0
    rho_fd = px(1215, 31, rr=0.0575 + 0.0005) - px(1215, 31, rr=0.0575 - 0.0005)      # 0.1 pp wide
    assert g["rho"] == pytest.approx(rho_fd / 0.1, rel=0.01)
    assert g["delta"] > 0 and g["gamma"] > 0 and g["vega"] > 0


def test_pre_expiry_iv_solved_from_premium_roundtrip():
    # premium at as_of 2026-10-19 (38 days), ref 1215, IV 22 %, no iv_pct in the request: engine must recover ~22 %.
    prem = b76("call", 1215.0, 1300.0, 38, 0.22)
    r = run([leg(strike=1300.0, ot="call", entry=prem)], grid=G5, pre_expiry=PRE)
    iv = r["pre_expiry"]["assumptions"]["legs"][0]
    assert iv["iv_pct"] == pytest.approx(22.0, abs=0.01) and "solved from the entry premium" in iv["iv_source"]


def test_pre_expiry_leg_without_valid_iv_is_unavailable_never_defaulted():
    # 1000 call at 0.5 with spot 1215 is below intrinsic: no volatility prices it. The expiry payoff still returns.
    r = run([leg(strike=1000.0, ot="call", entry=0.5)], grid=G5, pre_expiry=PRE)
    p = r["pre_expiry"]
    assert p["grid"] is None and p["net"] is None and p["gross"] is None and p["greeks"] is None
    assert p["unavailable"][0]["leg"] == 0 and "iv_pct" in p["unavailable"][0]["reason"]
    assert r["valid"] and r["expiry"]["gross"][0] is not None
    # a mixed strategy: one priceable leg and one not: all-or-nothing
    mix = run([leg(**CALL), leg(side="sell", strike=1000.0, ot="call", entry=0.5)], grid=G5, pre_expiry=PRE)
    assert mix["pre_expiry"]["grid"] is None and [u["leg"] for u in mix["pre_expiry"]["unavailable"]] == [1]


def test_pre_expiry_monotonic_sanity():
    def mid(shift=0, date_="2026-10-26", **kw):
        r = run([leg(**{**CALL, **kw})], grid={"min": 1215, "max": 1300, "points": 5}, pre_expiry={**PRE, "date": date_, "iv_shift_pct": shift})
        return r["pre_expiry"]["gross"][0]
    assert mid(shift=5) > mid(shift=0) > mid(shift=-5)               # call price rises with IV
    assert mid(date_="2026-10-20") > mid(date_="2026-10-26") > mid(date_="2026-11-20")   # decays with time
    bad = run([leg(**CALL)], grid=G5, pre_expiry={**PRE, "iv_shift_pct": -25})          # vol 25 − 25 = 0
    assert bad["pre_expiry"]["unavailable"]


def test_pre_expiry_on_expiry_day_has_no_greeks_but_prices_intrinsic():
    r = run([leg(**CALL)], grid=G5, pre_expiry={**PRE, "date": EXP})
    p = r["pre_expiry"]
    assert p["greeks"] is None and p["grid"] is not None
    # T = 0: intrinsic only, the same as the expiry payoff
    assert p["gross"] == r["expiry"]["gross"]


def test_pre_expiry_aggregate_is_sum_of_legs():
    # A lone short call is rejected as undefined risk, so the short leg is checked as the negative of the same leg bought.
    a, b = leg(**CALL), leg(side="sell", strike=1350.0, ot="call", entry=18.0, iv_pct=24.0)
    b_long = {**b, "side": "buy"}
    spread = run([a, b], grid=G5, pre_expiry=PRE)["pre_expiry"]
    one = run([a], grid=G5, pre_expiry=PRE)["pre_expiry"]
    two = run([b_long], grid=G5, pre_expiry=PRE)["pre_expiry"]
    for i in range(5):
        assert spread["gross"][i] == pytest.approx(one["gross"][i] - two["gross"][i], abs=0.011)
    for k in ("delta", "gamma", "theta", "vega", "rho"):
        assert spread["greeks"][k] == pytest.approx(one["greeks"][k] - two["greeks"][k], abs=0.001)
        assert spread["greeks"][k] == pytest.approx(sum(e["greeks"][k] for e in spread["per_leg_greeks"]), abs=0.001)
    assert spread["per_leg_greeks"][1]["greeks"]["delta"] < 0 and spread["per_leg_greeks"][1]["greeks"]["theta"] > 0


def test_pre_expiry_future_leg_is_linear_delta_only():
    r = run([leg("future", entry=1215.0)], grid=G5, pre_expiry=PRE)
    p = r["pre_expiry"]
    assert p["greeks"] == {"delta": 250.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0, "rho": 0.0}
    assert p["gross"] == r["expiry"]["gross"]


def test_pre_expiry_date_problems():
    assert "pre_expiry_after_expiry" in codes(run([leg(**CALL)], pre_expiry={**PRE, "date": "2026-12-01"}))
    assert "pre_expiry_before_as_of" in codes(run([leg(**CALL)], pre_expiry={**PRE, "date": "2026-10-01"}))
    assert "bad_rate" in codes(run([leg(**CALL)], pre_expiry={**PRE, "rate_pct": 90}))


# ── templates ────────────────────────────────────────────────────────────────

# MOCK — not real data: a hand-made chain in the shape routes/fno.py sends.
CHAIN = {"as_of": "2026-10-19", "strikes": [
    {"strike": 1100.0, "call": {"close": 130.0, "oi": 10, "volume": 1}, "put": {"close": 5.0, "oi": 10, "volume": 1}},
    {"strike": 1150.0, "call": {"close": 85.0, "oi": 10, "volume": 1}, "put": {"close": 15.0, "oi": 10, "volume": 1}},
    {"strike": 1250.0, "call": {"close": 14.0, "oi": 10, "volume": 1}, "put": {"close": 40.0, "oi": 10, "volume": 1}},
    {"strike": 1300.0, "call": {"close": 4.0, "oi": 10, "volume": 1}, "put": {"close": 70.0, "oi": 10, "volume": 1}},
    {"strike": 1350.0, "call": {"close": None, "oi": 0, "volume": 0}, "put": None},
]}
KW = dict(spot=1215.0, lot_size=50, expiry=EXP, underlying="RELIANCE", today=TODAY)


def test_template_bull_call_spread_closed_form():
    t = tp.bull_call_spread(CHAIN, long_strike=1150.0, short_strike=1250.0, lots=2, **KW)
    debit, width, units = 85.0 - 14.0, 100.0, 2 * 50
    assert t["max_loss"] == -debit * units and t["max_profit"] == (width - debit) * units
    assert t["breakevens"] == [1150.0 + debit] and t["net_premium"] == -debit * units
    assert t["legs"][0]["price_source"] == "NSE F&O bhavcopy close, 2026-10-19"


def test_template_debit_put_spread_and_iron_condor_and_longs():
    b = tp.bear_put_spread(CHAIN, long_strike=1250.0, short_strike=1150.0, **KW)
    assert b["max_loss"] == -(40.0 - 15.0) * 50 and b["max_profit"] == (100.0 - 25.0) * 50 and b["breakevens"] == [1225.0]
    ic = tp.iron_condor(CHAIN, long_put_strike=1100.0, short_put_strike=1150.0, short_call_strike=1250.0, long_call_strike=1300.0, **KW)
    credit = 15.0 + 14.0 - 5.0 - 4.0
    assert ic["max_profit"] == credit * 50 and ic["max_loss"] == -(50.0 - credit) * 50
    assert ic["breakevens"] == [1150.0 - credit, 1250.0 + credit]
    lc = tp.long_call(CHAIN, strike=1250.0, **KW)
    assert lc["max_loss"] == -14.0 * 50 and lc["profit_unbounded"] and lc["breakevens"] == [1264.0]
    lp = tp.long_put(CHAIN, strike=1250.0, **KW)
    assert lp["max_loss"] == -40.0 * 50 and lp["breakevens"] == [1210.0]


def test_template_futures_and_cash():
    lf = tp.long_future(spot=1215.0, lot_size=50, expiry=EXP, entry_price=1220.0, lots=2, today=TODAY, underlying="R")
    assert lf["profit_unbounded"] and not lf["loss_unbounded"] and lf["max_loss"] == -1220.0 * 100 and lf["breakevens"] == [1220.0]
    sf = tp.short_future(spot=1215.0, lot_size=50, expiry=EXP, entry_price=1220.0, today=TODAY, underlying="R")
    assert sf["loss_unbounded"] and not sf["profit_unbounded"] and sf["max_profit"] == 1220.0 * 50
    cl = tp.cash_long(spot=1215.0, shares=10, today=TODAY, underlying="R")
    assert cl["profit_unbounded"] and cl["max_loss"] == -12150.0 and cl["breakevens"] == [1215.0]


def test_template_never_guesses():
    with pytest.raises(tp.TemplateError) as e:
        tp.long_call(CHAIN, strike=1350.0, **KW)
    assert e.value.code == "no_premium"
    with pytest.raises(tp.TemplateError) as e:
        tp.long_call(CHAIN, strike=1200.0, **KW)
    assert e.value.code == "no_strike"
    with pytest.raises(tp.TemplateError) as e:
        tp.bull_call_spread(CHAIN, long_strike=1250.0, short_strike=1150.0, **KW)
    assert e.value.code == "strike_order"
    with pytest.raises(tp.TemplateError):
        tp.iron_condor(CHAIN, long_put_strike=1150.0, short_put_strike=1100.0, short_call_strike=1250.0, long_call_strike=1300.0, **KW)


# ── route ────────────────────────────────────────────────────────────────────

def _client(monkeypatch, signed_in=True):
    if signed_in:
        async def fake_user(request: Request):
            return {"user_id": "u1", "email": "u1@example.com"}
        monkeypatch.setattr(route, "get_current_user", fake_user)
    app = FastAPI()
    app.include_router(route.router)
    return TestClient(app)


URL = "/api/desk/strategy/payoff"


def test_route_valid(monkeypatch):
    legs = [leg("future", qty=1, lot=250, entry=1215.0, expiry="2099-01-28")]
    res = _client(monkeypatch).post(URL, json=req(legs))
    assert res.status_code == 200
    b = res.json()
    assert b["valid"] is True and b["calculation_version"] == "payoff-v1" and b["sent_to_broker"] is False
    assert b["expiry"]["profit_unbounded"] is True and b["margin"] is None


def test_route_problems_are_200(monkeypatch):
    res = _client(monkeypatch).post(URL, json=req([leg(side="sell", strike=1300.0, ot="call", entry=20.0, expiry="2099-01-28")]))
    assert res.status_code == 200
    b = res.json()
    assert b["valid"] is False and "undefined_risk_not_supported" in [p["code"] for p in b["problems"]] and b["expiry"] is None


def test_route_malformed_json_is_422(monkeypatch):
    c = _client(monkeypatch)
    assert c.post(URL, content=b"{not json", headers={"Content-Type": "application/json"}).status_code == 422
    assert c.post(URL, content=b"").status_code == 422
    assert c.post(URL, json=[1, 2]).json()["valid"] is False          # valid JSON of the wrong shape: problems, not a crash


def test_route_requires_sign_in(monkeypatch):
    res = _client(monkeypatch, signed_in=False).post(URL, json=req([leg("cash")]))
    assert res.status_code == 401


def test_route_is_post_only(monkeypatch):
    assert _client(monkeypatch).get(URL).status_code == 405


def test_router_is_registered_in_server():
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[1] / "server.py").read_text()
    assert "app.include_router(strategy_plan_router)" in src
