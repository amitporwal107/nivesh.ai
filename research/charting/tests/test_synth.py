"""RECT-1's stated properties must actually hold — a fixture that doesn't match its
own spec makes every downstream test meaningless. Also smoke-tests the generic
builder and every fixture-*/append helper other packages will reuse.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from research.charting.config import BARS_COLUMNS
from research.charting.swings import find_swings
from research.charting.tests import synth


# ── Independent ATR (Wilder-14), computed here only to verify the fixture ────


def _wilder_atr14(bars: pd.DataFrame) -> float:
    h = bars["high"].to_numpy(dtype=float)
    l = bars["low"].to_numpy(dtype=float)
    c = bars["close"].to_numpy(dtype=float)
    n = len(bars)
    tr = np.empty(n)
    tr[0] = h[0] - l[0]
    for i in range(1, n):
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
    period = 14
    atr = tr[:period].mean()
    for i in range(period, n):
        atr = (atr * (period - 1) + tr[i]) / period
    return float(atr)


# ── RECT-1 shape ──────────────────────────────────────────────────────────────


def test_rect1_has_bars_columns_and_is_well_formed():
    bars = synth.rect1()
    assert tuple(bars.columns) == tuple(BARS_COLUMNS)
    assert len(bars) == synth.RECT1_WARMUP_BARS + synth.RECT1_PATTERN_LENGTH
    assert bars["date"].is_monotonic_increasing
    assert not bars["date"].duplicated().any()
    assert (bars["high"] >= bars[["open", "close"]].max(axis=1)).all()
    assert (bars["low"] <= bars[["open", "close"]].min(axis=1)).all()


def test_rect1_resistance_touches_are_confirmed_swing_highs_at_bars_3_and_9():
    bars = synth.rect1()
    pivots = find_swings(bars)  # uses CONFIG's swing_left_bars/right_bars (3/3)
    highs = [p for p in pivots if p.kind == "HIGH"]

    expected_indices = {synth._fixture_bar_index(3), synth._fixture_bar_index(9)}
    actual_indices = {p.pivot_index for p in highs}
    assert actual_indices == expected_indices, (
        f"expected confirmed swing highs at fixture bars 3,9 (indices {sorted(expected_indices)}), "
        f"got indices {sorted(actual_indices)}"
    )
    for p in highs:
        assert p.price == pytest.approx(synth.RECT1_RESISTANCE)
        assert p.confirmed_index == p.pivot_index + 3  # swing_right_bars


def test_rect1_support_touches_are_confirmed_swing_lows_at_bars_6_and_12():
    bars = synth.rect1()
    pivots = find_swings(bars)
    lows = [p for p in pivots if p.kind == "LOW"]

    expected_indices = {synth._fixture_bar_index(6), synth._fixture_bar_index(12)}
    actual_indices = {p.pivot_index for p in lows}
    assert actual_indices == expected_indices, (
        f"expected confirmed swing lows at fixture bars 6,12 (indices {sorted(expected_indices)}), "
        f"got indices {sorted(actual_indices)}"
    )
    for p in lows:
        assert p.price == pytest.approx(synth.RECT1_SUPPORT)
        assert p.confirmed_index == p.pivot_index + 3


def test_rect1_no_stray_pivots_beyond_the_four_stated_touches():
    """A fixture with extra, unintended pivots would silently confuse any downstream
    geometry/strength test that assumes exactly four touches."""
    bars = synth.rect1()
    pivots = find_swings(bars)
    assert len(pivots) == 4


def test_rect1_at_least_70pct_of_pattern_closes_are_inside_the_zone():
    bars = synth.rect1()
    pattern_closes = bars["close"].to_numpy()[synth.RECT1_WARMUP_BARS :]
    assert len(pattern_closes) == synth.RECT1_PATTERN_LENGTH
    inside = (pattern_closes > synth.RECT1_SUPPORT) & (pattern_closes < synth.RECT1_RESISTANCE)
    assert inside.mean() >= 0.70


def test_rect1_20bar_volume_baseline_is_100000():
    bars = synth.rect1()
    assert len(bars) == 20
    assert bars["volume"].mean() == pytest.approx(synth.RECT1_VOLUME_BASELINE)


def test_rect1_atr_is_close_to_the_test_plan_target():
    """Exact ATR=2.0 is not reachable together with the fixture's other exactly-
    stated properties (10-point range, touches every 3 bars — see synth.py's module
    docstring). This asserts Wilder ATR-14 lands in a documented tolerance band
    around the test-plan's ~2.0 target, order-of-magnitude consistent with the
    rectangle_min/max_range_atr=[1.50, 8.00] band (10.0 / atr must fall inside it)."""
    bars = synth.rect1()
    atr = _wilder_atr14(bars)
    assert 1.5 <= atr <= 3.5, f"ATR {atr} outside the documented ~2.0 tolerance band"
    range_in_atr = (synth.RECT1_RESISTANCE - synth.RECT1_SUPPORT) / atr
    assert 1.50 <= range_in_atr <= 8.00  # CONFIG rectangle_min/max_range_atr


def test_rect1_breakout_and_breakdown_reference_levels_bracket_the_zone():
    assert synth.RECT1_BREAKOUT_LEVEL > synth.RECT1_RESISTANCE
    assert synth.RECT1_BREAKDOWN_LEVEL < synth.RECT1_SUPPORT
    assert synth.RECT1_BREAKOUT_LEVEL == pytest.approx(110.50)
    assert synth.RECT1_BREAKDOWN_LEVEL == pytest.approx(99.50)


# ── Generic builder ───────────────────────────────────────────────────────────


def test_bars_from_closes_round_trips_the_close_path():
    closes = [100.0, 101.5, 99.0, 102.0]
    bars = synth.bars_from_closes(closes)
    assert tuple(bars.columns) == tuple(BARS_COLUMNS)
    assert list(bars["close"]) == closes
    assert (bars["high"] >= bars[["open", "close"]].max(axis=1)).all()
    assert (bars["low"] <= bars[["open", "close"]].min(axis=1)).all()
    assert bars["date"].is_monotonic_increasing
    assert not bars["date"].duplicated().any()


def test_bars_from_closes_is_deterministic():
    closes = [50.0, 51.0, 49.5, 52.0, 48.0]
    a = synth.bars_from_closes(closes)
    b = synth.bars_from_closes(closes)
    pd.testing.assert_frame_equal(a, b)


def test_bars_from_closes_rejects_mismatched_volume_length():
    with pytest.raises(ValueError):
        synth.bars_from_closes([1.0, 2.0, 3.0], volume=[100.0, 200.0])


# ── Fixture-specific extension helpers (#1-#5b, #8, #9, #12) ─────────────────


@pytest.mark.parametrize(
    "helper, n_appended",
    [
        (synth.fixture_01_wick_only_breakout, 1),
        (synth.fixture_02_low_volume_breakout, 1),
        (synth.fixture_03_close_back_inside, 2),
        (synth.fixture_04_false_retest, 4),
        (synth.fixture_05_gap_through_invalidation, 2),
        (synth.fixture_05b_gap_breakdown_control, 1),
        (synth.fixture_09_future_volume_contamination, 3),
    ],
)
def test_rect1_append_fixtures_extend_cleanly(helper, n_appended):
    base = synth.rect1()
    extended = helper(base)
    assert tuple(extended.columns) == tuple(BARS_COLUMNS)
    assert len(extended) == len(base) + n_appended
    # the base bars are untouched (helper must not mutate its input)
    pd.testing.assert_frame_equal(extended.iloc[: len(base)].reset_index(drop=True), base)
    assert extended["date"].is_monotonic_increasing
    assert not extended["date"].duplicated().any()
    assert (extended["high"] >= extended[["open", "close"]].max(axis=1)).all()
    assert (extended["low"] <= extended[["open", "close"]].min(axis=1)).all()


def test_fixture_02_low_volume_breakout_has_rel_volume_090():
    bars = synth.fixture_02_low_volume_breakout(synth.rect1())
    bar16_volume = bars["volume"].iloc[-1]
    baseline = synth.rect1()["volume"].to_numpy()[-20:].mean()
    assert bar16_volume / baseline == pytest.approx(0.90)


def test_fixture_09_bar16_rel_volume_is_150():
    bars = synth.fixture_09_future_volume_contamination(synth.rect1())
    bar16_volume = bars["volume"].iloc[-3]
    baseline = synth.rect1()["volume"].to_numpy()[-20:].mean()
    assert bar16_volume / baseline == pytest.approx(1.50)


def test_fixture_05b_never_trades_inside_the_zone():
    bars = synth.fixture_05b_gap_breakdown_control(synth.rect1())
    bar16 = bars.iloc[-1]
    assert bar16["high"] < synth.RECT1_SUPPORT  # never touches 100-110 at all


def test_fixture_08_lookahead_swing_shape_and_confirmation():
    bars = synth.fixture_08_lookahead_swing()
    assert tuple(bars.columns) == tuple(BARS_COLUMNS)
    assert len(bars) == 8
    pivots = find_swings(bars)
    highs = [p for p in pivots if p.kind == "HIGH"]
    assert len(highs) == 1
    assert highs[0].pivot_index == 4  # bar5, 0-indexed
    assert highs[0].price == pytest.approx(112.0)
    assert highs[0].confirmed_index == 7  # bar8, 0-indexed


def test_fixture_12_incomplete_candle_is_not_a_row_in_the_completed_frame():
    completed, incomplete = synth.fixture_12_incomplete_candle(synth.rect1())
    assert tuple(completed.columns) == tuple(BARS_COLUMNS)
    assert incomplete["is_complete"] is False
    assert incomplete["close"] == pytest.approx(110.6)
    # the incomplete bar's date is strictly after every completed bar's date
    assert incomplete["date"] > completed["date"].iloc[-1]
    assert incomplete["date"] not in set(completed["date"])
