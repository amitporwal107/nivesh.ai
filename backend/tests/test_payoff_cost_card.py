"""payoff-v2: the payoff engine prices costs with the desk cost card (services/desk_cost_card.py, desk-cost-v2), the card the
plan's sizing and every paper trade use (test_reports/p4_research_hardening_TESTCASES.md TC-PC-1 … TC-PC-9).

Fixtures are MOCK — not real data: round numbers so each component can be worked by hand. Card rates (desk_cost_card.STATUTORY):
equity delivery STT 0.1% each side, exchange 0.00307%, stamp 0.015% (buy); futures STT 0.05% (sell), exchange 0.00183%, stamp
0.002% (buy); options on the premium STT 0.15% (sell), exchange 0.03553%, stamp 0.003% (buy); SEBI ₹10 per crore; GST 18% of
brokerage + exchange + SEBI; desk assumptions ₹20 brokerage and 0.05% slippage per side. Every component is rounded to the paisa.
"""
from __future__ import annotations

import inspect
import random
from datetime import date

import pytest

from services import desk_cost_card as cost_card
from services import desk_strategy_trades as strat
from services import desk_trading as desk
from services.strategy_plan import CALCULATION_VERSION, compute_payoff
from services.strategy_plan import payoff as po
from services.strategy_plan.model import parse_request

TODAY = date(2026, 10, 19)
EXP = "2026-11-26"


def leg(kind="option", side="buy", qty=1, lot=250, entry=40.0, strike=None, ot=None):
    if kind == "cash":
        lot = 1
    return {"kind": kind, "side": side, "quantity": qty, "lot_size": lot, "entry_price": entry,
            "expiry": None if kind == "cash" else EXP, "strike": strike, "option_type": ot}


def run(legs, **kw):
    body = {"underlying": "RELIANCE", "reference_price": 1215.0, "legs": legs, "grid": {"min": 1000, "max": 1500, "points": 101}, **kw}
    return compute_payoff(body, TODAY)


def at(r, price, key="gross"):
    e = r["expiry"]
    return e[key][e["grid"].index(price)]


SPREAD = [leg(strike=1300.0, ot="call", entry=40.0), leg(side="sell", strike=1350.0, ot="call", entry=18.0)]


# ── TC-PC-5: version and compatibility ───────────────────────────────────────

def test_tc_pc5_version_and_signature_are_compatible():
    assert CALCULATION_VERSION == "payoff-v2"
    # Phase 1 (feat/p1-universal-risk) and every consumer call compute_payoff(body, today): unchanged.
    assert list(inspect.signature(compute_payoff).parameters) == ["body", "today"]
    r = run(SPREAD)
    assert r["calculation_version"] == "payoff-v2" and r["costs"]["version"] == cost_card.VERSION == "desk-cost-v2"
    # every top-level key a v1 consumer reads is still there
    for k in ("valid", "problems", "warnings", "expiry", "pre_expiry", "costs", "margin", "margin_reason", "capital_at_risk",
              "capital_at_risk_basis", "loss_can_exceed_margin", "caveats", "sent_to_broker"):
        assert k in r, k
    for k in ("model", "slippage_pct", "brokerage_per_side", "source", "entry", "exit_at_expiry", "round_trip", "exit_basis", "per_leg", "excluded"):
        assert k in r["costs"], k


def test_tc_pc5_costs_never_move_a_gross_figure():
    # The cost model changes net figures only: gross curve, extremes, breakevens and the pre-expiry gross are cost-free.
    pre = {"date": "2026-10-26", "iv_shift_pct": 0, "rate_pct": 5.75}
    legs = SPREAD + [leg("cash", qty=100, entry=1215.0)]
    a = run(legs, pre_expiry=pre)
    b = run(legs, pre_expiry=pre, costs={"slippage_pct": 0.5, "brokerage_per_side": 100})
    for k in ("grid", "gross", "breakevens", "max_profit", "max_loss", "range_max_profit", "range_max_loss", "net_premium"):
        assert a["expiry"][k] == b["expiry"][k], k
    assert a["pre_expiry"]["gross"] == b["pre_expiry"]["gross"] and a["pre_expiry"]["greeks"] == b["pre_expiry"]["greeks"]
    assert all(x > y for x, y in zip(a["expiry"]["net"], b["expiry"]["net"]))      # dearer costs, lower net everywhere


# ── TC-PC-1 / TC-PC-3: the bull call spread, component by component ──────────

def test_tc_pc1_spread_components_by_hand():
    r = run(SPREAD)
    c = r["costs"]
    # entry BUY 1300C 40 × 250 = 10,000: 20 + exch 3.553 → 3.55 + SEBI 0.01 + stamp 0.30 + GST 18% × 23.56 = 4.2408 → 4.24
    #   + slippage 5.00 = 33.10
    # entry SELL 1350C 18 × 250 = 4,500: 20 + STT 6.75 + exch 1.59885 → 1.60 + SEBI 0.0045 → 0.00 + GST 18% × 21.60 = 3.888 → 3.89
    #   + slippage 2.25 = 34.49
    assert [p["entry"] for p in c["per_leg"]] == [33.1, 34.49] and [p["segment"] for p in c["per_leg"]] == ["options", "options"]
    assert c["components"]["entry"] == {"brokerage": 40.0, "stt": 6.75, "exchange": 5.15, "sebi": 0.01, "stamp": 0.3,
                                        "gst": 8.13, "slippage": 7.25, "total": 67.59}
    # at the reference 1215 both calls expire worthless: no exit order, no exit cost
    assert c["exit_at_expiry"] == 0.0 and c["components"]["exit_at_expiry"] is None and c["round_trip"] == 67.59
    # at 1400 (both in the money): exit SELL 1300C at intrinsic 100 × 250 = 25,000: 20 + STT 37.50 + exch 8.8825 → 8.88
    #   + SEBI 0.025 → 0.03 + GST 18% × 28.91 = 5.2038 → 5.20 + slippage 12.50 = 84.11
    # exit BUY 1350C at 50 × 250 = 12,500: 20 + exch 4.44125 → 4.44 + SEBI 0.0125 → 0.01 + stamp 0.375 → 0.38
    #   + GST 18% × 24.45 = 4.401 → 4.40 + slippage 6.25 = 35.48
    # net = 7,000 − 67.59 − 84.11 − 35.48 = 6,812.82
    assert at(r, 1400.0) == 7000.0 and at(r, 1400.0, "net") == 6812.82
    assert c["excluded"] == ["DP charges", "IPFT and clearing charges", "income tax on gains", "dividends", "funding"]
    assert "desk-cost-v2" in c["model"] and "STT" in c["model"] and c["source"] == "services/desk_cost_card.py (desk-cost-v2)"
    assert any("include brokerage, STT" in x for x in r["caveats"]) and not any("excludes taxes, STT" in x for x in r["caveats"])


# ── TC-PC-2 / TC-PC-9: capital at risk and the worthless-expiry convention ───

def test_tc_pc2_tc_pc9_capital_at_risk_charges_worthless_exits_the_net_curve_does_not():
    r = run(SPREAD)
    # The worst price is any price at or below 1300 (both calls worthless): gross −5,500, the two entry sides 67.59, and for the
    # conservative capital at risk the two exit orders of nothing: (20 brokerage + 3.60 GST) × 2 = 47.20 -> 5,614.79.
    assert r["capital_at_risk"] == 5614.79
    # the net curve at 1200 has no exit order: −5,500 − 67.59
    assert at(r, 1200.0, "net") == -5567.59
    assert r["expiry"]["max_loss"] == -5500.0                       # the gross maximum loss is untouched


# ── TC-PC-8: segments ────────────────────────────────────────────────────────

def test_tc_pc8_cash_is_equity_delivery_and_a_future_is_futures():
    cash = run([leg("cash", qty=100, entry=1215.0)])["costs"]
    fut = run([leg("future", qty=1, lot=250, entry=1215.0)])["costs"]
    assert cash["per_leg"][0]["segment"] == "equity_delivery" and fut["per_leg"][0]["segment"] == "futures"
    # cash pays STT on the BUY (0.1% of 1,21,500 = 121.50) and stamp 0.015% (18.225 → 18.23)
    assert (cash["components"]["entry"]["stt"], cash["components"]["entry"]["stamp"]) == (121.5, 18.23)
    # a future pays no STT on the buy; stamp 0.002% of 3,03,750 = 6.075 → 6.08
    assert (fut["components"]["entry"]["stt"], fut["components"]["entry"]["stamp"]) == (0.0, 6.08)
    # exits at the reference 1215: cash SELL STT 121.50, no stamp; future SELL STT 0.05% of 3,03,750 = 151.875 → 151.88
    assert (cash["components"]["exit_at_expiry"]["stt"], cash["components"]["exit_at_expiry"]["stamp"]) == (121.5, 0.0)
    assert (fut["components"]["exit_at_expiry"]["stt"], fut["components"]["exit_at_expiry"]["stamp"]) == (151.88, 0.0)


def test_tc_pc8_a_short_leg_enters_with_a_sale_and_exits_with_a_purchase():
    # Sell 100 shares at 1215 (cash is linear: allowed short in the calculator). Entry SELL: STT, no stamp; exit BUY: stamp.
    c = run([leg("cash", side="sell", qty=100, entry=1215.0)])["costs"]
    assert c["components"]["entry"]["stamp"] == 0.0 and c["components"]["entry"]["stt"] == 121.5
    assert c["components"]["exit_at_expiry"]["stamp"] == 18.23


# ── TC-PC-4: request overrides ───────────────────────────────────────────────

def test_tc_pc4_request_replaces_slippage_and_brokerage_and_statutory_charges_stay():
    r = run([leg("future", qty=1, lot=250, entry=1215.0)], costs={"slippage_pct": 0.1, "brokerage_per_side": 0})
    e = r["costs"]["components"]["entry"]
    # BUY 3,03,750: brokerage 0, slippage 0.1% = 303.75, exchange 5.56, SEBI 0.30, stamp 6.08, GST 18% × 5.86 = 1.05
    assert e == {"brokerage": 0.0, "stt": 0.0, "exchange": 5.56, "sebi": 0.3, "stamp": 6.08, "gst": 1.05, "slippage": 303.75, "total": 316.74}
    assert r["costs"]["source"] == "services/desk_cost_card.py (desk-cost-v2); slippage_pct and brokerage_per_side from the request"
    only_slip = run([leg("future", qty=1, lot=250, entry=1215.0)], costs={"slippage_pct": 0})
    assert only_slip["costs"]["components"]["entry"]["brokerage"] == 20.0 and only_slip["costs"]["components"]["entry"]["slippage"] == 0.0


def test_tc_pc4_the_plan_and_the_payoff_use_the_same_model_for_the_same_request():
    from services.strategy_plan import candidates as cd
    for costs in ({}, {"slippage_pct": 0.1}, {"brokerage_per_side": 0}, {"slippage_pct": 0.2, "brokerage_per_side": 5}):
        model, _ = po.cost_params({"slippage_pct": costs.get("slippage_pct"), "brokerage_per_side": costs.get("brokerage_per_side")})
        plan_model = cd._cost_model({"costs": costs})
        assert model["version"] == plan_model["version"] == "desk-cost-v2", costs
        for k in ("slippage_pct_per_side", "brokerage_rs_per_side"):
            assert float(model[k]) == float(plan_model[k]), (costs, k)


# ── TC-PC-6: parity with what a paper trade of the structure books ───────────

def _paper_trade(legs):
    return {"legs": [{"kind": l["kind"], "side": l["side"], "lots": l["quantity"], "lot_size": l["lot_size"], "entry_price": l["entry_price"]}
                     for l in legs], "cost_model": dict(desk.COST_MODEL)}


@pytest.mark.parametrize("seed", range(25))
def test_tc_pc6_payoff_costs_equal_the_paper_trades_costs_to_the_paisa(seed):
    # A random defined-risk structure held to expiry at a price where every option is in the money: the payoff's round trip
    # equals services/desk_strategy_trades.strategy_cost_breakdown with the intrinsic values as the exit marks.
    rnd = random.Random(seed)
    lot = rnd.choice([25, 50, 75, 250])
    k1 = rnd.choice([1100.0, 1150.0, 1200.0])
    k2 = k1 + rnd.choice([50.0, 100.0])
    legs = [leg(strike=k1, ot="call", entry=rnd.choice([35.5, 60.0, 81.25]), lot=lot, qty=rnd.choice([1, 2])),
            leg(side="sell", strike=k2, ot="call", entry=rnd.choice([10.0, 18.75, 25.0]), lot=lot, qty=1)]
    if rnd.random() < 0.5:
        legs.append(leg("future", qty=1, lot=lot, entry=rnd.choice([1190.0, 1215.0])))
    if rnd.random() < 0.5:
        legs[1]["quantity"] = legs[0]["quantity"]
    s = rnd.choice([1310.0, 1355.5, 1420.0])
    parsed = parse_request({"underlying": "X", "reference_price": 1215.0, "legs": legs}, TODAY)
    assert not parsed["problems"], parsed["problems"]
    model, _ = po.cost_params(parsed["costs"])
    payoff_cost = round(po.total_cost(parsed["legs"], s, model), 2)
    marks = [po.exit_value(l, s) for l in parsed["legs"]]
    paper = strat.strategy_cost_breakdown(_paper_trade(legs), marks)
    assert payoff_cost == paper["total"], (seed, payoff_cost, paper)


def test_tc_pc6_the_cash_leg_equals_the_desk_round_trip():
    # A share leg prices exactly like a cash paper trade's round trip (desk_trading.round_trip_cost, equity delivery).
    parsed = parse_request({"underlying": "X", "reference_price": 1215.0, "legs": [leg("cash", qty=77, entry=1215.0)]}, TODAY)
    model, _ = po.cost_params(parsed["costs"])
    assert round(po.total_cost(parsed["legs"], 1180.0, model), 2) == desk.round_trip_cost(77, 1215.0, 1180.0)
