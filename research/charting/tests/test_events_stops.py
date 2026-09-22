"""stops.py: the §37.2/§37.3 initial stop (Layer 1 structural + Layer 2 ATR floor), the §37.2
targets, and the per-horizon target/stop outcome walk -- all-synthetic, hand-computed fixtures
only (task rule: no real-data numeric assertions in this file). See `test_events_lookahead.py`
for this module's own poisoned-future probe + negative control.
"""
from __future__ import annotations

import pytest

from research.charting.events import extraction, schema, stops
from research.charting.tests._events_helpers import confirmed_rectangle_bearish_with_runway, raw_bars as _raw_bars


# ── structural_stop (Layer 1) ────────────────────────────────────────────────────────────────


def test_structural_stop_rectangle_bullish_is_broken_level_minus_failure_buffer_atr():
    stop, method = stops.structural_stop("RECTANGLE", "BULLISH", {}, level_broken_value=110.5, atr_at_t=2.0, cfg={"failure_buffer_atr": 0.25})
    assert stop == pytest.approx(110.5 - 0.25 * 2.0)  # 110.0
    assert method == "broken_level_minus_failure_buffer_atr"


def test_structural_stop_support_resistance_bearish_is_broken_level_plus_failure_buffer_atr():
    stop, method = stops.structural_stop("SUPPORT_RESISTANCE", "BEARISH", {}, level_broken_value=99.6, atr_at_t=2.0, cfg={"failure_buffer_atr": 0.25})
    assert stop == pytest.approx(99.6 + 0.25 * 2.0)  # 100.1 -- BEARISH stop sits ABOVE the broken level
    assert method == "broken_level_minus_failure_buffer_atr"


def test_structural_stop_breakout_families_none_when_level_or_atr_missing():
    assert stops.structural_stop("RECTANGLE", "BULLISH", {}, None, 2.0) == (None, None)
    assert stops.structural_stop("RECTANGLE", "BULLISH", {}, 110.5, None) == (None, None)
    assert stops.structural_stop("RECTANGLE", "BULLISH", {}, 110.5, float("nan")) == (None, None)


def test_structural_stop_hh_hl_uses_the_invalidation_swing_no_atr_buffer():
    levels = {"prior_high": 120.0, "prior_low": 90.0}
    stop, method = stops.structural_stop("HH_HL", "BULLISH", levels, level_broken_value=120.0, atr_at_t=2.0)
    assert stop == pytest.approx(90.0)  # the OTHER swing (prior_low), no ATR buffer subtracted
    assert method == "hh_hl_invalidation_swing"
    stop_b, _ = stops.structural_stop("HH_HL", "BEARISH", levels, level_broken_value=90.0, atr_at_t=2.0)
    assert stop_b == pytest.approx(120.0)


def test_structural_stop_hh_hl_missing_swing_or_unknown_family_returns_none_never_a_guess():
    assert stops.structural_stop("HH_HL", "BULLISH", {}, None, 2.0) == (None, None)
    assert stops.structural_stop("HH_HL", "BULLISH", {"prior_low": None}, None, 2.0) == (None, None)
    assert stops.structural_stop("TRIANGLE", "BULLISH", {"prior_low": 90.0}, 90.0, 2.0) == (None, None)
    assert stops.structural_stop(None, "BULLISH", {}, 90.0, 2.0) == (None, None)


# ── resolve_stop (Layer 1 + Layer 2) ─────────────────────────────────────────────────────────


def test_resolve_stop_structural_wins_when_already_wider_than_layer_2_floor():
    # entry=112, structural=110 -> structural_distance=2.0; atr=2.0 -> layer2=0.75*2.0=1.5.
    out = stops.resolve_stop(112.0, 110.0, 2.0, cfg={})
    assert out["final_stop"] == pytest.approx(110.0)
    assert out["stop_layer"] == "structural"
    assert out["layer2_min_distance"] == pytest.approx(1.5)
    assert out["r_value"] == pytest.approx(2.0)


def test_resolve_stop_layer_2_widens_a_too_tight_structural_stop_never_tightens():
    # entry=100, structural=99.5 -> structural_distance=0.5; atr=1.0 -> layer2=0.75.
    out = stops.resolve_stop(100.0, 99.5, 1.0, cfg={})
    assert out["stop_layer"] == "layer2_widened"
    assert out["final_stop"] == pytest.approx(100.0 - 0.75)  # 99.25 -- WIDER (lower) than 99.5
    assert out["final_stop"] < 99.5
    assert out["r_value"] == pytest.approx(0.75)


def test_resolve_stop_layer_2_only_when_no_structural_stop_a_control_row():
    out = stops.resolve_stop(100.0, None, 2.0, cfg={})
    assert out["structural_stop"] is None
    assert out["stop_layer"] == "layer2_only"
    assert out["final_stop"] == pytest.approx(100.0 - 0.75 * 2.0)  # 98.5
    assert out["r_value"] == pytest.approx(1.5)


def test_resolve_stop_none_when_neither_layer_available():
    out = stops.resolve_stop(100.0, None, None, cfg={})
    assert out == {"structural_stop": None, "layer2_min_distance": None, "final_stop": None, "stop_layer": None, "r_value": None,
                   "entry_beyond_structural_stop": None}


def test_resolve_stop_self_corrects_a_structural_stop_at_or_above_entry():
    # A pathological gap-down entry landing AT the structural stop (distance=0): layer2 (always
    # positive) must still win and push the final stop below entry -- "widen, never tighten"
    # degrades gracefully rather than producing a non-positive R.
    out = stops.resolve_stop(100.0, 100.0, 2.0, cfg={})
    assert out["stop_layer"] == "layer2_widened"
    assert out["final_stop"] < 100.0
    assert out["r_value"] > 0


# ── target_prices ─────────────────────────────────────────────────────────────────────────────


def test_target_prices_pct_and_r_multiple_from_entry_and_r():
    prices = stops.target_prices(100.0, r_value=4.0)
    assert prices["pct_2"] == pytest.approx(102.0)
    assert prices["pct_3"] == pytest.approx(103.0)
    assert prices["pct_5"] == pytest.approx(105.0)
    assert prices["pct_10"] == pytest.approx(110.0)
    assert prices["r_1_0"] == pytest.approx(104.0)
    assert prices["r_1_5"] == pytest.approx(106.0)
    assert prices["r_2_0"] == pytest.approx(108.0)
    assert prices["r_3_0"] == pytest.approx(112.0)


def test_target_prices_r_multiples_none_when_r_value_none_pct_targets_still_computed():
    prices = stops.target_prices(100.0, r_value=None)
    assert prices["pct_2"] == pytest.approx(102.0)
    for name in ("r_1_0", "r_1_5", "r_2_0", "r_3_0"):
        assert prices[name] is None


# ── the target/stop walk: hand-computed bar-by-bar scenarios (§37.3) ────────────────────────


def test_walk_target_hit_first_no_stop_touch():
    bars = _raw_bars([
        (100.0, 105.0, 98.0, 102.0, 1e5),   # offset0 entry bar -- no touch
        (102.0, 107.0, 100.0, 105.0, 1e5),  # offset1 -- no touch
        (105.0, 111.0, 104.0, 109.0, 1e5),  # offset2 -- high>=110 target touched, low=104 safe
    ])
    out = stops.target_outcome_by_horizon(bars, 0, 100.0, target_price=110.0, stop_price=95.0, qty=10, adv_inr=None)
    for h in (3, 5, 10, 20):
        r = out[h]
        assert r["available"] is True
        assert r["first_exit_event"] == "TARGET"
        assert r["target_hit"] is True and r["stop_hit"] is False and r["both_hit"] is False and r["neither_hit"] is False
        assert r["target_hit_session"] == 2
        assert r["exit"]["exit_price"] == pytest.approx(110.0)  # fills at the target level, not the bar's own high
        assert r["exit"]["holding_period_sessions"] == 2
        assert r["exit"]["gross_return"] == pytest.approx((110.0 - 100.0) / 100.0)
        assert r["exit"]["costs"]["available"] is True
    # horizon 1: the resolution (offset 2) falls OUTSIDE a 1-session cap -- neither_hit, not a
    # different answer, since offsets 0 and 1 (the only ones inside that cap) really were scanned.
    assert out[1]["neither_hit"] is True and out[1]["first_exit_event"] == "NONE"


def test_walk_stop_hit_first_no_target_touch():
    bars = _raw_bars([
        (100.0, 104.0, 98.0, 102.0, 1e5),  # offset0 entry -- no touch
        (102.0, 106.0, 99.0, 101.0, 1e5),  # offset1 -- no touch (low=99 > 95)
        (101.0, 103.0, 93.0, 94.0, 1e5),   # offset2 -- low<=95 stop touched, high=103<110
    ])
    out = stops.target_outcome_by_horizon(bars, 0, 100.0, target_price=110.0, stop_price=95.0, qty=10, adv_inr=None)
    r = out[5]
    assert r["first_exit_event"] == "STOP"
    assert r["stop_hit"] is True and r["target_hit"] is False
    assert r["stop_hit_session"] == 2
    assert r["exit"]["exit_price"] == pytest.approx(95.0)  # fills at the stop level
    assert r["exit"]["gross_return"] == pytest.approx((95.0 - 100.0) / 100.0)


def test_walk_ambiguous_same_bar_both_touched_no_gap_never_assumes_an_order():
    bars = _raw_bars([
        (100.0, 104.0, 98.0, 102.0, 1e5),   # offset0 entry -- no touch
        (102.0, 112.0, 93.0, 105.0, 1e5),   # offset1 -- open=102 (no gap); high>=110 AND low<=95
    ])
    out = stops.target_outcome_by_horizon(bars, 0, 100.0, target_price=110.0, stop_price=95.0, qty=10, adv_inr=None)
    r = out[5]
    assert r["first_exit_event"] == "AMBIGUOUS"
    assert r["target_hit"] is True and r["stop_hit"] is True and r["both_hit"] is True and r["neither_hit"] is False
    assert r["target_hit_session"] == r["stop_hit_session"] == 1
    assert r["exit"] is None  # never a single number for an ambiguous exit
    assert r["as_if_target"]["exit_price"] == pytest.approx(110.0)
    assert r["as_if_stop"]["exit_price"] == pytest.approx(95.0)
    assert r["as_if_target"]["gross_return"] == pytest.approx(0.10)
    assert r["as_if_stop"]["gross_return"] == pytest.approx(-0.05)


def test_walk_gap_through_stop_fills_at_the_open_even_if_high_also_reaches_target():
    bars = _raw_bars([
        (100.0, 104.0, 98.0, 102.0, 1e5),  # offset0 entry -- no touch
        (90.0, 112.0, 88.0, 91.0, 1e5),    # offset1 -- OPENS at/below stop(95): gap rule fills
                                            # at the open, regardless of this same bar's high.
    ])
    out = stops.target_outcome_by_horizon(bars, 0, 100.0, target_price=110.0, stop_price=95.0, qty=10, adv_inr=None)
    r = out[5]
    assert r["first_exit_event"] == "STOP"
    assert r["exit"]["exit_price"] == pytest.approx(90.0)  # the OPEN, not the -95 stop level
    assert r["exit"]["holding_period_sessions"] == 1


def test_walk_gap_through_target_fills_at_the_open():
    bars = _raw_bars([
        (100.0, 104.0, 98.0, 102.0, 1e5),  # offset0 entry -- no touch
        (112.0, 113.0, 111.0, 112.0, 1e5),  # offset1 -- opens at/above target(110): gap fill
    ])
    out = stops.target_outcome_by_horizon(bars, 0, 100.0, target_price=110.0, stop_price=95.0, qty=10, adv_inr=None)
    r = out[5]
    assert r["first_exit_event"] == "TARGET"
    assert r["exit"]["exit_price"] == pytest.approx(112.0)  # the OPEN, not the 110 target level


def test_walk_entry_bar_itself_can_resolve_the_target_using_only_its_own_high_low():
    # "On the entry bar itself, use only the part of the bar after the open: treat the entry
    # bar like any other bar (the entry is at its open)" -- offset 0 is exempt from the gap
    # check (its own open IS the entry price) but its high/low are checked exactly like any
    # other bar's.
    bars = _raw_bars([(100.0, 106.0, 99.0, 103.0, 1e5)])
    out = stops.target_outcome_by_horizon(bars, 0, 100.0, target_price=104.0, stop_price=95.0, qty=10, adv_inr=None, horizons=(1,))
    r = out[1]
    assert r["first_exit_event"] == "TARGET"
    assert r["target_hit_session"] == 0
    assert r["exit"]["exit_price"] == pytest.approx(104.0)
    assert r["exit"]["holding_period_sessions"] == 0


def test_walk_neither_within_a_fully_available_horizon_vs_insufficient_forward_bars():
    # 6 bars total (offsets 0..5): target/stop never touched anywhere.
    flat_row = (100.0, 101.0, 99.0, 100.0, 1e5)
    bars = _raw_bars([flat_row] * 6)
    out = stops.target_outcome_by_horizon(bars, 0, 100.0, target_price=110.0, stop_price=95.0, qty=10, adv_inr=None)
    for h in (1, 3, 5):  # offsets 0..h all really existed and were scanned
        assert out[h]["available"] is True
        assert out[h]["neither_hit"] is True
        assert out[h]["first_exit_event"] == "NONE"
    for h in (10, 20):  # offset 6 does not exist -- never silently truncated
        assert out[h] == {"available": False, "reason": "insufficient_forward_bars"}


# ── BEARISH rows: no stop/target trade, informational flags present (§37.4) ─────────────────


def test_bearish_confirmed_event_row_has_no_stop_or_targets_but_keeps_informational_flags():
    bars = confirmed_rectangle_bearish_with_runway()
    rows = extraction.extract_events(bars, "SYNB")
    bearish = [r for r in rows if r["direction"] == "BEARISH"]
    assert bearish, "fixture must produce a confirmed BEARISH row for this test to be meaningful"
    row = bearish[0]
    assert row["stop"] is None
    assert row["targets"] is None
    assert row["costs"]["by_horizon"] is None
    assert row["costs"]["short_side_costs"] == "NOT_MODELLED"
    assert row["costs"]["trade_side"] == "LONG"
    assert row["tradability"] == schema.TRADABILITY_INFORMATIONAL
    assert row["action"] == schema.ACTION_AVOID_NEW_LONG
    # the "avoid" signal itself must still be checkable: directional forward returns present.
    directional = row["outcomes"]["forward_returns_directional"]
    assert any(v.get("available") for v in directional.values())


def test_bullish_confirmed_event_row_has_stop_and_targets_and_tradability_long_actionable():
    from research.charting.tests._events_helpers import confirmed_rectangle_with_runway

    bars = confirmed_rectangle_with_runway()
    row = extraction.extract_events(bars, "SYN1")[0]
    assert row["direction"] == "BULLISH"
    assert row["tradability"] == schema.TRADABILITY_LONG_ACTIONABLE
    assert row["action"] == schema.ACTION_CONSIDER_LONG
    assert row["stop"]["final_stop"] is not None
    assert row["stop"]["final_stop"] < row["entry"]["primary"]["price"]
    assert row["stop"]["r_value"] == pytest.approx(row["entry"]["primary"]["price"] - row["stop"]["final_stop"])
    assert set(row["targets"].keys()) == {"pct_2", "pct_3", "pct_5", "pct_10", "r_1_0", "r_1_5", "r_2_0", "r_3_0"}
    for name, block in row["targets"].items():
        assert block["target_price"] > row["entry"]["primary"]["price"]
        assert set(block["by_horizon"].keys()) == {1, 3, 5, 10, 20}


def test_entry_opening_below_the_structural_stop_is_flagged_not_hidden():
    from research.charting.events.stops import resolve_stop

    # structural stop 98, entry gapped down to 97 (already beyond it), ATR 2 -> Layer 2 floor 1.5 below entry
    r = resolve_stop(97.0, 98.0, 2.0)
    assert r["entry_beyond_structural_stop"] is True
    assert r["final_stop"] == pytest.approx(95.5) and r["r_value"] == pytest.approx(1.5)
    ordinary = resolve_stop(100.0, 98.0, 2.0)  # 2.0 below entry >= 1.5 floor: structural stop stands
    assert ordinary["entry_beyond_structural_stop"] is False and ordinary["stop_layer"] == "structural"
    # without an ATR there is no valid stop at all for a pattern already invalid at entry
    assert resolve_stop(97.0, 98.0, None)["final_stop"] is None
