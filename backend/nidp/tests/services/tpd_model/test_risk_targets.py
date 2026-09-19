"""Target exits, fill-relative levels and the intrabar ambiguity flag (simulation PRD v1.0 §10-§11, deliverable D2).

Written against the pre-registered matrix (docs/ai_research/tpd3/sim_diag/PREREGISTRATION_SIM_MATRIX.md §4b): runs D
and F put the H#32 rule through the portfolio loop, which means the engine must exit at a target and must set both
levels from the price it actually filled at, not from the signal's reference price. Every expected number is worked by
hand here: value20 = ₹500 crore, so the slippage bucket is 0.05% a side.
"""
from __future__ import annotations

from decimal import Decimal as D

import pandas as pd
import pytest

from nidp.services.tpd_model.risk import config as RC
from nidp.services.tpd_model.risk import costs as CC
from nidp.services.tpd_model.risk import engine as EN
from nidp.services.tpd_model.risk import execution as EX

from .test_risk_engine import DAYS, EXITS, bars_frame, flat, signal

POS = RC.load_config("RISK-POS-1")
ZR = CC.load_cost_model("zerodha-equity-v1")
SEC = {"A": "X"}


def run(sigs, rows, **kw):
    return EN.run(pd.DataFrame(sigs), bars_frame(rows), POS, ZR, SEC, EXITS, allow_retroactive_costs=True, **kw)


def sig(sid="t1", day=0, stop=95, ref=100, **kw):
    return {**signal(sid, "A", day, stop, ref), **kw}


# ---------------- execution: the raw base travels with the fill ----------------

def bar(o, h, l, c, v=10_000_000, pc=100):
    return EX.Bar(D(str(o)), D(str(h)), D(str(l)), D(str(c)), v, D(str(pc)))


def test_every_fill_reports_the_raw_price_it_keyed_on():
    b = bar(100, 110, 96, 105)
    assert EX.fill_entry("MOO", b, qty=1, slippage_pct=D("0.05"), participation_pct=D("100")).base == D("100")
    assert EX.fill_entry("BUY_STOP", b, qty=1, slippage_pct=D("0.05"), participation_pct=D("100"),
                         trigger=D("104")).base == D("104")           # filled at the trigger, inside the bar
    assert EX.fill_entry("BUY_STOP", bar(108, 110, 107, 109), qty=1, slippage_pct=D("0"), participation_pct=D("100"),
                         trigger=D("104")).base == D("108")           # gapped over the trigger: the open
    assert EX.fill_entry("LIMIT", b, qty=1, slippage_pct=D("0.05"), participation_pct=D("100"),
                         limit=D("98")).base == D("98")
    under = EX.fill_entry("LIMIT", bar(95, 99, 94, 97), qty=1, slippage_pct=D("0"), participation_pct=D("100"),
                          limit=D("98"))                              # opened under the limit: the open is the fill
    assert under.base == D("95") and under.price == D("95")
    assert EX.fill_entry("MOC", b, qty=1, slippage_pct=D("0.05"), participation_pct=D("100")).base == D("105")
    t = EX.fill_entry("TYPICAL", b, qty=1, slippage_pct=D("0"), participation_pct=D("100"))
    assert t.base == (D("110") + D("96") + D("105")) / 3
    locked = EX.fill_entry("MOO", bar(105, 105, 105, 105), qty=1, slippage_pct=D("0"), participation_pct=D("100"))
    assert locked.status == "NO_FILL" and locked.base is None          # locked all day at +5%: nothing to fill against


# ---------------- engine: target exits ----------------

def test_a_target_reached_intraday_exits_at_the_target():
    rows = flat("A", 100)
    rows[2] = ("A", DAYS[2], 100, 106, 99, 105, 10_000_000, 5e9)
    t = run([sig(target=105)], rows).trades.iloc[0]
    assert t.exit_reason == "TARGET" and t.exit_date == DAYS[2]
    assert t.exit_price == D("104.95")                                # 105 x 0.9995 = 104.9475, to the paisa
    assert t.target == D("105") and t.net_pnl > 0


def test_an_open_above_the_target_exits_at_the_open_not_at_the_target():
    rows = flat("A", 100)
    rows[2] = ("A", DAYS[2], 110, 112, 109, 111, 10_000_000, 5e9)
    t = run([sig(target=105)], rows).trades.iloc[0]
    assert t.exit_reason == "GAP_OVER_TARGET" and t.exit_price == D("109.95")   # 110 x 0.9995


def test_a_target_reached_on_the_entry_bar_exits_the_same_day():
    rows = flat("A", 100)
    rows[1] = ("A", DAYS[1], 100, 106, 99.5, 105, 10_000_000, 5e9)
    t = run([sig(target_pct=5)], rows).trades.iloc[0]
    assert t.exit_reason == "TARGET_SAME_DAY" and t.exit_date == DAYS[1] and t.exit_price == D("104.95")


def test_a_target_at_or_below_the_fill_cancels_the_order():
    res = run([sig(target=100)], flat("A", 100))                      # fills at 100.05, above the target
    assert res.trades.empty
    cancelled = [r for r in res.ledger.records("order") if r.get("reason") == "TARGET_AT_OR_BELOW_FILL"]
    assert len(cancelled) == 1


# ---------------- engine: levels from the fill, not from the reference price ----------------

def test_stop_and_target_percentages_are_measured_from_the_fill_not_the_reference_price():
    rows = flat("A", 100)
    rows[1] = ("A", DAYS[1], 110, 111, 109, 110, 10_000_000, 5e9)      # s1 gaps up: reference 100, fill 110
    res = run([sig(stop=98, stop_pct=2, target_pct=5)], rows)
    t = res.trades.iloc[0]
    assert t.initial_stop == D("107.80") and t.target == D("115.50")   # 110 x 0.98 and 110 x 1.05
    assert t.exit_reason == "GAP_THROUGH" and t.exit_date == DAYS[2]   # day 2 opens back at 100, under the stop
    assert t.exit_price == D("99.95")


def test_without_percentages_the_signal_stop_is_used_unchanged():
    t = run([sig(stop=95)], flat("A", 100) [:2] + [("A", DAYS[2], 94, 95, 93, 94.5, 10_000_000, 5e9)]).trades.iloc[0]
    assert t.initial_stop == D("95") and t.exit_reason == "GAP_THROUGH"


def test_an_entry_filled_inside_the_bar_is_not_gapped_through_by_that_bar_s_open():
    """A buy-stop that triggers at 100 on a bar that opened at 94 did not gap through a 95 stop: it was not held at
    the open. The bar is evaluated from the fill, stop-first, so the exit is the stop, never the open."""
    rows = flat("A", 100)
    rows[1] = ("A", DAYS[1], 94, 106, 93, 105, 10_000_000, 5e9)
    t = run([sig(stop=95, order_type="BUY_STOP", trigger=100)], rows).trades.iloc[0]
    assert t.entry_price == D("100.05") and t.exit_date == DAYS[1]
    assert t.exit_reason == "STOP_SAME_DAY" and t.exit_price == D("94.95")      # the stop, not 94 x 0.9995


# ---------------- engine: intrabar ambiguity ----------------

def test_a_bar_that_reaches_both_levels_is_flagged_and_follows_the_policy():
    rows = flat("A", 100)
    rows[2] = ("A", DAYS[2], 100, 106, 94, 100, 10_000_000, 5e9)
    res = run([sig(target=105)], rows)
    t = res.trades.iloc[0]
    assert t.exit_reason == "STOP" and t.exit_price == D("94.95")
    amb = [e for e in res.ledger.records("event") if e["event_type"] == "INTRABAR_AMBIGUOUS"]
    assert len(amb) == 1 and amb[0]["symbol"] == "A" and amb[0]["date"] == DAYS[2].isoformat()

    res2 = run([sig(target=105)], rows, intrabar_policy="TARGET_FIRST")
    t2 = res2.trades.iloc[0]
    assert t2.exit_reason == "TARGET" and t2.exit_price == D("104.95")
    assert len([e for e in res2.ledger.records("event") if e["event_type"] == "INTRABAR_AMBIGUOUS"]) == 1


def test_both_levels_on_the_entry_bar_are_flagged_too():
    rows = flat("A", 100)
    rows[1] = ("A", DAYS[1], 100, 106, 94, 105, 10_000_000, 5e9)
    res = run([sig(target=105)], rows)
    assert res.trades.iloc[0].exit_reason == "STOP_SAME_DAY"
    assert len([e for e in res.ledger.records("event") if e["event_type"] == "INTRABAR_AMBIGUOUS"]) == 1


def test_an_unambiguous_bar_is_not_flagged():
    rows = flat("A", 100)
    rows[2] = ("A", DAYS[2], 100, 106, 99, 105, 10_000_000, 5e9)
    res = run([sig(target=105)], rows)
    assert not [e for e in res.ledger.records("event") if e["event_type"] == "INTRABAR_AMBIGUOUS"]


def test_an_unknown_intrabar_policy_is_refused():
    with pytest.raises(ValueError):
        run([sig(target=105)], flat("A", 100), intrabar_policy="TARGET_IF_NICE")


# ---------------- engine: the ablation and the circuit lock still hold ----------------

def test_with_stops_off_a_target_still_exits_and_a_breached_stop_does_not():
    rows = flat("A", 100)
    rows[2] = ("A", DAYS[2], 100, 106, 90, 100, 10_000_000, 5e9)       # breaches the 95 stop and reaches the target
    t = run([sig(target=105)], rows, stops_active=False).trades.iloc[0]
    assert t.exit_reason == "TARGET" and t.exit_price == D("104.95")


def test_a_session_locked_at_the_lower_circuit_blocks_the_exit():
    rows = flat("A", 100)
    rows[2] = ("A", DAYS[2], 95, 95, 95, 95, 10_000_000, 5e9)          # -5% on a 100 prev close, open = low = high
    res = run([sig(stop=96, target=105)], rows)
    blocked = [e for e in res.ledger.records("event") if e["event_type"] == "EXIT_BLOCKED"]
    assert blocked and blocked[0]["reason"] == "LOCKED_LOWER"
    assert res.trades.iloc[0].exit_date > DAYS[2]                      # still held, exits later


def test_the_existing_behaviour_is_unchanged_when_no_signal_carries_a_target():
    rows = flat("A", 100)
    rows[2] = ("A", DAYS[2], 94, 95, 93, 94.5, 10_000_000, 5e9)
    a = run([sig("t1")], rows)
    b = EN.run(pd.DataFrame([sig("t1")]), bars_frame(rows), POS, ZR, SEC, EXITS, allow_retroactive_costs=True)
    assert a.ledger_digest == b.ledger_digest
    assert a.trades.iloc[0].exit_reason == "GAP_THROUGH" and a.trades.iloc[0].target is None


# ---------------- D7 (owner approved 2026-09-20): the lock test and the blocked stop ----------------

def test_a_bar_that_opens_at_a_band_and_then_trades_is_not_locked():
    """The old test (open == high, or open == low, at a band) fired on bars that traded away from the band, refusing
    fills the market really offered. Only a bar that never left the band (high == low) is locked."""
    assert EX.locked_upper(bar(105, 105, 105, 105)) and EX.locked_lower(bar(95, 95, 95, 95))
    assert not EX.locked_upper(bar(105, 105, 101, 102))                # opened at +5%, sold off: tradable
    assert not EX.locked_lower(bar(95, 99, 95, 98))                    # opened at -5%, rallied: tradable
    assert not EX.locked_upper(bar(103, 103, 103, 103))                # flat all day, but not at a band
    f = EX.check_stop(bar(95, 99, 95, 98), D("96"), D("0"))            # a stop under a tradable open
    assert f.status == "FILLED" and f.reason == "GAP_THROUGH" and f.price == D("95")


def test_a_stop_blocked_by_a_lock_exits_at_the_next_open_not_at_the_old_stop():
    """D3 found the engine kept the old stop after a blocked exit, so a position could escape a stop it had already
    hit (TTML 28 Jan 2022 ended +9.4%). It now leaves at the first price the market offers."""
    rows = flat("A", 100)
    rows[2] = ("A", DAYS[2], 95, 95, 95, 95, 10_000_000, 5e9)          # locked all day at -5%: no sale possible
    rows[3] = ("A", DAYS[3], 102, 104, 101, 103, 10_000_000, 5e9)      # trades again, well above the 96 stop
    res = run([sig(stop=96)], rows)
    t = res.trades.iloc[0]
    blocked = [e for e in res.ledger.records("event") if e["event_type"] == "EXIT_BLOCKED"]
    assert len(blocked) == 1 and blocked[0]["date"] == DAYS[2].isoformat()
    assert t.exit_reason == "BLOCKED_STOP" and t.exit_date == DAYS[3]
    assert t.exit_price == D("101.95")                                 # 102 x 0.9995, the open - NOT the 96 stop


def test_a_position_stays_blocked_while_the_lock_continues():
    rows = flat("A", 100)
    rows[2] = ("A", DAYS[2], 95, 95, 95, 95, 10_000_000, 5e9)
    rows[3] = ("A", DAYS[3], 90.25, 90.25, 90.25, 90.25, 10_000_000, 5e9)   # -5% again, locked again
    rows[4] = ("A", DAYS[4], 88, 91, 87, 90, 10_000_000, 5e9)
    res = run([sig(stop=96)], rows)
    t = res.trades.iloc[0]
    assert len([e for e in res.ledger.records("event") if e["event_type"] == "EXIT_BLOCKED"]) == 2
    assert t.exit_reason == "BLOCKED_STOP" and t.exit_date == DAYS[4] and t.exit_price == D("87.96")   # 88 x 0.9995
