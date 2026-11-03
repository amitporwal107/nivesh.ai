"""PRD §8 worked examples A–H as golden tests (Phase 4.1), plus the edge cases §4.1 names.

Source of the examples: docs/NIVESH_AI_LAB_TRADING_DECISION_GUIDELINES.md §8 (hypothetical prices). Every function called
is the repo's own: services.strategy_plan.candidates.size_position / scenario_levels (the plan's sizing and targets),
services.desk_trading.round_trip_cost / max_units_within_budget (the desk cost card desk-cost-v2, the model a paper trade
books), routes.positional._trade_scenario (the desk calculator), services.strategy_plan.engine.compute_payoff (options),
services.exit_rules (the exit step shared by the backtest and paper trades).

The PRD's figures are GROSS ("Quantities omit transaction costs unless noted"). Where the code now applies the PRD's own
§5 rule ("Include fees, taxes, spread and realistic slippage in the risk estimate"), the cost-inclusive figure is pinned
next to the gross one and the difference is explained. If a number here changes, the change must be intentional and the
expected value updated with the reason (Phase 4.1: "fail when a regression changes expected results without an
intentional update"). Case ids: test_reports/p2_exits_backtest_TESTCASES.md TC-60, TC-61.
"""
from __future__ import annotations

import asyncio
import inspect
import random
from datetime import date, datetime, timedelta, timezone

import pytest

from services import desk_trading as desk
from services import exit_rules as er
from services.strategy_engine import backtest as bt
from services.strategy_plan import candidates as cd
from services.strategy_plan.engine import compute_payoff

CAPITAL = 10_000_000.0       # large, so the 25 % allocation cap never binds and only the risk budget sizes


def inputs(budget):
    return {"risk_budget_inr": budget, "capital": CAPITAL, "max_allocation_pct": 25.0}


def gross_size(budget, entry, stop, lot=1, unit="shares"):
    return cd.size_position(inputs(budget), risk_per_unit=abs(entry - stop), value_per_unit=entry, unit=unit,
                            lot_units=lot, per_unit_label="x")


def net_size(budget, entry, stop, lot=1, unit="shares", segment="equity_delivery"):
    return cd.size_position(inputs(budget), risk_per_unit=abs(entry - stop), value_per_unit=entry, unit=unit,
                            lot_units=lot, per_unit_label="x",
                            cost_at_stop=lambda u: desk.round_trip_cost(u, entry, stop, segment=segment, long=stop < entry))


def levels(entry, stop, up=True):
    return {l["name"]: l["price"] for l in cd.scenario_levels(entry, up, stop, None, None)}


# ── TC-60: the arithmetic of the linear examples, exactly as the PRD prints it (gross) ───────────────────────
LINEAR = [
    # id, entry, stop, budget, lot, unit, PRD quantity, PRD risk, PRD 2R target, PRD 3R target (None = not given)
    ("A", 1005, 970, 3000, 1, "shares", 85, 2975.0, 1075.0, 1110.0),
    ("B", 882, 868, 2500, 1, "shares", 178, 2492.0, 910.0, None),
    ("C", 522, 517, 2000, 1, "shares", 400, 2000.0, 532.0, None),
    ("D", 675, 686, 2500, 1, "shares", 227, 2497.0, 653.0, None),        # a short: the stop is above the entry
    ("E", 1250, 1225, 2500, 100, "lots", 1, 2500.0, 1300.0, None),       # futures, lot 100: one lot
    ("G", 1005, 970, 2500, 1, "shares", 71, 2485.0, None, None),
]


@pytest.mark.parametrize("ex,entry,stop,budget,lot,unit,qty,risk,t2r,t3r", LINEAR, ids=[x[0] for x in LINEAR])
def test_tc60_prd_gross_arithmetic(ex, entry, stop, budget, lot, unit, qty, risk, t2r, t3r):
    s = gross_size(budget, entry, stop, lot, unit)
    assert (s["status"], s["quantity"], s["risk_at_stop_inr"], s["binding"]) == ("complete", qty, risk, "risk_budget")
    assert s["units"] == qty * lot
    lv = levels(entry, stop, up=stop < entry)
    if t2r is not None:
        assert lv["base"] == t2r
    if t3r is not None:
        assert lv["optimistic"] == t3r


# ── TC-60: what the code does with costs in (PRD §5 "include fees, taxes, spread and slippage") ──────────────
@pytest.mark.parametrize("ex,entry,stop,budget,lot,segment,gross_qty,net_qty,net_loss_at_stop", [
    # A: 85 shares are ₹2,975 gross, but ₹3,293.11 after the desk cost card (round trip at the stop ₹318.11) — over the
    #    ₹3,000 budget. The most that fits after costs is 77: 77 × 35 = 2,695 + 292.61 = ₹2,987.61 (78 would be ₹3,025.81).
    #    (The study measured ₹3,098.94 for 85 under the older flat model, desk-flat-v1.)
    ("A", 1005, 970, 3000, 1, "equity_delivery", 85, 77, 2987.61),
    # B: a ₹14 stop is narrow against the costs: 178 shares lose ₹3,041.65 after costs; 145 fit (₹2,030 + costs).
    ("B", 882, 868, 2500, 1, "equity_delivery", 178, 145, None),
    # C: priced at delivery rates (the card has no intraday segment; the intraday workflow is refused, see below).
    ("C", 522, 517, 2000, 1, "equity_delivery", 400, 292, None),
    # E: one lot is exactly the ₹2,500 budget gross; the futures round trip at the stop (₹240.34) takes it to ₹2,740.34,
    #    so no whole lot fits: the trade is refused (or the budget raised), as the PRD's own risk check would do.
    ("E", 1250, 1225, 2500, 100, "futures", 1, 0, None),
    # G: the PRD's 71 shares are ₹2,485 before costs and ₹2,758.49 after (cost ₹273.49) — above a ₹2,500 budget; 64 fit.
    ("G", 1005, 970, 2500, 1, "equity_delivery", 71, 64, None),
], ids=["A", "B", "C", "E", "G"])
def test_tc60_cost_inclusive_sizing_under_desk_cost_v2(ex, entry, stop, budget, lot, segment, gross_qty, net_qty, net_loss_at_stop):
    assert gross_size(budget, entry, stop, lot)["quantity"] == gross_qty
    n = net_size(budget, entry, stop, lot, segment=segment)
    assert n["quantity"] == net_qty and desk.max_units_within_budget(budget, entry, stop, lot_units=lot, segment=segment) == net_qty * lot
    if net_qty:
        units = net_qty * lot
        loss = units * abs(entry - stop) + desk.round_trip_cost(units, entry, stop, segment=segment)
        assert loss <= budget
        nxt = (net_qty + 1) * lot
        assert nxt * abs(entry - stop) + desk.round_trip_cost(nxt, entry, stop, segment=segment) > budget
        if net_loss_at_stop is not None:
            assert round(loss, 2) == net_loss_at_stop
    else:
        assert n["status"] == "too_small"


def test_tc60_example_a_on_the_desk_calculator_is_77_not_85():
    from routes.positional import _trade_scenario
    r = _trade_scenario(entry=1005, stop=970, target=1075, capital=CAPITAL, risk_budget=3000)
    assert r["valid"] and r["sizing"]["quantity"] == 77
    assert r["outcomes"]["loss_at_stop"] == 2695 and r["outcomes"]["loss_at_stop_net"] == 2987.61
    assert r["outcomes"]["profit_at_target"] == 5390                     # 77 × (1,075 − 1,005)


def test_tc60_example_a_gross_85_shares_would_break_the_budget_after_costs():
    cost = desk.round_trip_cost(85, 1005, 970)
    assert (cost, round(85 * 35 + cost, 2)) == (318.11, 3293.11)


# ── C and D: arithmetic only; the workflows are refused, as the PRD's own caveats require ────────────────────
def test_tc60_example_c_atr_stop_and_the_intraday_refusal():
    assert 522 - 2 * 2.5 == 517                                          # the ATR stop (ATR 2.50, multiplier 2)
    from services.strategy_plan import plan
    ins = {"horizon": "intraday", "underlying": "FIXC", "horizon_days": 1, "avoid_events": False, "defaults_applied": [],
           "direction": "bullish"}
    ledger = {"summary": {g: {"conflicts": 0, "supports": 0} for g in plan.RULES["conflict"]["groups"]}}
    reasons = plan.global_reasons(ins, {}, {"as_of": None, "today": date(2026, 10, 27)}, ledger)
    hit = [r for r in reasons if r["code"] == "intraday_not_supported"]
    assert hit and hit[0]["kind"] == "data"                              # → the plan is insufficient_data, no entry


def test_tc60_example_d_short_cash_is_refused_everywhere():
    # The plan: a bearish cash view is "avoid" with reason long_only.
    [c] = cd.cash_candidates({"direction": "bearish"})
    assert c["status"] == "avoid" and "long_only" in [r["code"] for r in c["reasons"]]
    # The desk: a stop above the entry is refused.
    with pytest.raises(desk.DeskInputError, match="stop_not_below_entry"):
        desk.new_trade("u", {"symbol": "FIXD", "quantity": 227, "entry_price": 675, "stop_price": 686})
    # The calculator: invalid for a long.
    from routes.positional import _trade_scenario
    r = _trade_scenario(entry=675, stop=686, target=653, capital=CAPITAL, risk_budget=2500)
    assert not r["valid"] and {p["code"] for p in r["problems"]} == {"stop_not_below_entry", "target_not_above_entry"}


# ── F: the bull call spread ───────────────────────────────────────────────────────────────────────────────
F_LEGS = [{"kind": "option", "side": "buy", "quantity": 1, "lot_size": 50, "entry_price": 220, "expiry": "2026-11-26", "strike": 25000, "option_type": "call"},
          {"kind": "option", "side": "sell", "quantity": 1, "lot_size": 50, "entry_price": 130, "expiry": "2026-11-26", "strike": 25200, "option_type": "call"}]


def _payoff(costs):
    body = {"underlying": "NIFTY", "reference_price": 25000, "legs": F_LEGS, "grid": {"from_pct": -5, "to_pct": 5, "points": 201},
            "as_of": "2026-10-26"}
    if costs is not None:
        body["costs"] = costs
    return compute_payoff(body, date(2026, 10, 26))


def test_tc60_example_f_payoff_and_rejection_against_2500():
    gross = _payoff({"slippage_pct": 0, "brokerage_per_side": 0})
    ex = gross["expiry"]
    assert (ex["max_loss"], ex["max_profit"], ex["breakevens"], ex["net_premium"]) == (-4500.0, 5500.0, [25090.0], -4500.0)
    # The PRD's ₹4,500 (90 × 50) is the gross maximum loss. payoff-v2 prices costs with the desk cost card, whose statutory
    # charges apply even with slippage and brokerage set to 0 (payoff-v1 gave exactly 4,500 here):
    #   entry BUY 25000C 11,000: exch 3.91 + SEBI 0.01 + stamp 0.33 + GST 18% × 3.92 = 0.71 = 4.96
    #   entry SELL 25200C 6,500: STT 9.75 + exch 2.31 + SEBI 0.01 + GST 18% × 2.32 = 0.42 = 12.49 ; worthless exits 0 -> 4,517.45
    assert gross["capital_at_risk"] == 4517.45
    with_costs = _payoff(None)
    # The card's defaults (payoff-v1: 4,588.75 = 4,500 + 25.50 + 23.25 + 2 × 20):
    #   entry BUY 11,000: 20 + 3.91 + 0.01 + 0.33 + GST 18% × 23.92 = 4.31 + slippage 5.50 = 34.06
    #   entry SELL 6,500: 20 + STT 9.75 + 2.31 + 0.01 + GST 18% × 22.32 = 4.02 + slippage 3.25 = 39.34
    #   the two worthless exits, charged for capital at risk: (20 + GST 3.60) × 2 = 47.20 -> 4,620.60
    assert with_costs["capital_at_risk"] == 4620.6
    for car in (-ex["max_loss"], gross["capital_at_risk"], with_costs["capital_at_risk"]):
        s = cd.size_position(inputs(2500), risk_per_unit=car, value_per_unit=car, unit="lots", lot_units=1, per_unit_label="x")
        assert (s["status"], s["quantity"]) == ("too_small", 0)        # one lot exceeds ₹2,500: rejected


# ── G: the failed breakout exits at the planned stop; a gap fills at the open ─────────────────────────────────
def test_tc60_example_g_exits_at_the_stop_and_a_gap_fills_worse():
    r = er.Rules(side="long", target=1075.0)
    _, ex = er.step(er.start(1005.0, 970.0, r), {"date": date(2026, 10, 6), "open": 990, "high": 995, "low": 965, "close": 968}, r)
    assert (ex["reason"], ex["price"]) == ("stop", 970.0)
    assert round(71 * (ex["price"] - 1005), 2) == -2485.0               # the planned ₹2,485, before costs
    _, gap = er.step(er.start(1005.0, 970.0, r), {"date": date(2026, 10, 6), "open": 950, "high": 955, "low": 940, "close": 945}, r)
    assert (gap["reason"], gap["price"], gap["gapped"]) == ("stop", 950, True)
    assert 71 * (gap["price"] - 1005) == -3905                          # the gap costs ₹1,420 more than the plan


# ── H: the ATR trailing stop ──────────────────────────────────────────────────────────────────────────────
H_RULES = er.Rules(side="long", trail_atr_mult=2.0)


def test_tc60_example_h_golden_1040():
    # Entry 1,000, initial stop 970, ATR 20, k 2, highest price since entry 1,080 → 1,080 − 2 × 20 = 1,040.
    # The PRD asks us to say how ATR and the update work: ATR is recalculated every bar (Wilder, bars up to the close) and
    # the stop updates at the close, in force from the next session. With a bar whose true range is the ATR (20), the
    # ATR stays 20 and the trail is the PRD's 1,040.
    s = er.start(1000.0, 970.0, H_RULES, atr=20.0, prev_close=1070.0)
    s, ex = er.step(s, {"date": date(2026, 10, 6), "open": 1062, "high": 1080, "low": 1060, "close": 1070}, H_RULES)
    assert ex is None and s.atr == 20.0 and s.stop == 1040.0


def test_tc60_example_h_atr_is_per_bar_so_a_wider_bar_moves_it():
    # The same high with a 35-point true range: ATR (20 × 13 + 35) / 14 = 21.07 → 1,080 − 42.14 = 1,037.86 (not 1,040).
    s = er.start(1000.0, 970.0, H_RULES, atr=20.0, prev_close=1060.0)
    s, _ = er.step(s, {"date": date(2026, 10, 6), "open": 1060, "high": 1080, "low": 1045, "close": 1070}, H_RULES)
    assert s.stop == 1037.86


def test_tc60_example_h_same_bar_high_1080_low_1035_does_not_exit_at_the_raised_stop():
    # The old backtest raised the stop to 1,040 with this bar's high and stopped out at it on the same bar (₹1,039.48
    # after slippage). Now the stop in force for the bar is 970: no exit; the raised stop counts from the next session.
    s = er.start(1000.0, 970.0, H_RULES, atr=20.0, prev_close=1070.0)
    s, ex = er.step(s, {"date": date(2026, 10, 6), "open": 1062, "high": 1080, "low": 1035, "close": 1070}, H_RULES)
    assert ex is None and s.stop > 1000
    s, ex = er.step(s, {"date": date(2026, 10, 7), "open": 1050, "high": 1052, "low": s.stop - 0.5, "close": 1045}, H_RULES)
    assert ex["reason"] == "trailing_stop" and ex["price"] == s.stop


# ── TC-61: edge cases §4.1 names ──────────────────────────────────────────────────────────────────────────
NOW = datetime(2026, 10, 5, 4, 0, tzinfo=timezone.utc)


def _bar(d, o, h, l, c):
    return {"date": d, "open": o, "high": h, "low": l, "close": c, "volume": 1.0, "series": "EQ"}


def test_tc61_missing_prices_wait_and_are_never_filled_in():
    t = desk.new_trade("u", {"symbol": "FIXA", "quantity": 10, "entry_price": 100, "stop_price": 95, "target_price": 110}, NOW)
    sim = desk.simulate(t, [_bar(date(2026, 10, 6), 99, None, 94, 96), _bar(date(2026, 10, 7), 99, 100, 90, 91)])
    assert sim["exit"] is None and sim["checked_through"] is None       # the 6 Oct bar has no high: nothing after it is read
    assert [f["code"] for f in sim["flags"]] == ["bar_missing_high_low"]
    with pytest.raises(desk.DeskInputError, match="invalid_stop_price"):
        desk.new_trade("u", {"symbol": "FIXA", "quantity": 10, "entry_price": 100}, NOW)


@pytest.mark.parametrize("stop,target,code", [(100, None, "stop_not_below_entry"), (105, None, "stop_not_below_entry"),
                                              (95, 100, "target_not_above_entry"), (0, None, "invalid_stop_price"),
                                              (-1, None, "invalid_stop_price")])
def test_tc61_invalid_stops_are_refused(stop, target, code):
    with pytest.raises(desk.DeskInputError, match=code):
        desk.new_trade("u", {"symbol": "FIXA", "quantity": 1, "entry_price": 100, "stop_price": stop, "target_price": target}, NOW)


@pytest.mark.parametrize("atr", [0, None, -3, float("nan")])
def test_tc61_zero_or_missing_atr_never_moves_the_stop(atr):
    s = er.start(1000.0, 970.0, H_RULES, atr=atr)
    s, ex = er.step(s, {"date": date(2026, 10, 6), "open": 1000, "high": 1200, "low": 999, "close": 1190}, H_RULES)
    assert ex is None and s.stop == 970.0 and [e["code"] for e in s.events] == ["atr_unavailable"]


def test_tc61_stale_data_freezes_the_trail_rather_than_moving_it():
    # A paper trade with the opt-in trail: a session with no high/low stops the scan, so the stop cannot move on it.
    t = desk.new_trade("u", {"symbol": "FIXA", "quantity": 10, "entry_price": 100, "stop_price": 95, "target_price": 150,
                             "exit_rules": {"trailing_atr": {"k": 2, "atr_period": 2}}}, NOW)
    warm = [_bar(date(2026, 10, 2), 100, 101, 99, 100), _bar(date(2026, 10, 5), 100, 101, 99, 100)]
    sim = desk.simulate(t, warm + [_bar(date(2026, 10, 6), 100, None, 99, 120), _bar(date(2026, 10, 7), 120, 125, 119, 124)])
    assert sim["current_stop"] == 95.0 and sim["checked_through"] is None


def test_tc61_minimum_lot_a_budget_below_one_lot_sizes_zero():
    s = gross_size(2400, 1250, 1225, lot=100, unit="lots")               # one lot risks 2,500 > 2,400
    assert (s["status"], s["quantity"]) == ("too_small", 0)


def test_tc61_partial_fills_are_not_modelled_the_whole_quantity_fills_or_nothing():
    # Documented in the desk FILL MODEL: a close takes no quantity, and P&L is always the whole position's.
    assert "quantity" not in inspect.signature(desk.close_trade).parameters
    t = desk.new_trade("u", {"symbol": "FIXA", "quantity": 10, "entry_price": 100, "stop_price": 95}, NOW)
    assert desk.realized_pnl(t, 95.0) == -50.0


@pytest.mark.parametrize("seed", range(10))
def test_tc61_the_stop_is_monotone(seed):
    rnd = random.Random(seed)
    s, px = er.start(100.0, 92.0, er.Rules(side="long", trail_atr_mult=1.5, atr_period=5)), 100.0
    stops = [s.stop]
    for i in range(150):
        o = px * (1 + rnd.uniform(-0.01, 0.01))
        h, l = max(o, px) * (1 + rnd.uniform(0, 0.02)), min(o, px) * (1 - rnd.uniform(0, 0.02))
        c = rnd.uniform(l, h)
        s, ex = er.step(s, {"date": date(2026, 1, 1) + timedelta(days=i), "open": o, "high": h, "low": l, "close": c},
                        er.Rules(side="long", trail_atr_mult=1.5, atr_period=5))
        if ex:
            break
        stops.append(s.stop)
        px = c
    assert stops == sorted(stops)


def test_tc61_backtest_and_paper_fill_a_gap_the_same_way(monkeypatch):
    # One fixed path through both simulators (the 60-path parity property is in tests/test_paper_exit_rules.py).
    d0, d1 = date(2026, 10, 5), date(2026, 10, 6)

    class P:
        basis = {}

        async def prepare(self, *a):
            return None

        async def trading_dates(self, *a):
            return [d0, d1]

        async def latest_date(self):
            return d1

        async def screen(self, spec, d):
            return [{"symbol": "FIXA", "close": 100.0, "adj_close": 100.0, "adj_factor": 1.0, "atr14": None}] if d == d0 else []

        async def exit_bars(self, symbols, d):
            return {"FIXA": {"open": 92, "high": 93, "low": 90, "close": 91}} if d == d1 else {}
    monkeypatch.setattr(bt, "get_provider", lambda pool=None: P())
    spec = {"version": "1", "asset_class": "STOCK", "name": "g", "universe": {"type": "index", "ref": "NIFTY500"},
            "entry": {"all_of": [{"feature": "rsi14", "op": ">", "value": 1}]}, "exit": {"stoploss_pct": 5, "target_rr": 2},
            "ranking": {"by": "score", "limit": 1}, "rebalance": "daily"}
    [t] = asyncio.run(bt.run_backtest(None, spec, from_date=d0, to_date=d1, max_positions=1, slippage_pct=0.0,
                                      brokerage_inr=0.0, cost_model=bt.COST_FLAT)).trades
    paper = desk.simulate(desk.new_trade("u", {"symbol": "FIXA", "quantity": 1, "entry_price": 100, "stop_price": 95,
                                                "target_price": 110}, NOW), [_bar(d1, 92, 93, 90, 91)])
    assert (t.exit_reason, t.exit_price) == ("STOPLOSS", 92.0)
    assert (paper["exit"]["exit_reason"], paper["exit"]["exit_price"]) == ("stop", 92)
