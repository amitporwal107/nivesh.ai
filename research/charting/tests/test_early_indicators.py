"""§34.4 indicators added by CHART-S25/Y-2 — docs/charting.md §34.4, §34.5.

Covers the five gaps `research/charting/early/indicators.py`'s own module docstring
documents against the actual §34.4 table and the actual (pre-existing) code in
`early/scoring.py`: Bollinger Band Width, Higher lows/lower highs, Support/resistance
stability, Volume accumulation, Failed breakout attempts. Each indicator gets:
  1. basic shape/bounds/insufficient-data unit tests,
  2. a poisoned-future PIT probe (test-plan.md Part B methodology, matching
     `test_early_lookahead.py`'s and `test_patterns_lookahead.py`'s own style), and
  3. a peeking negative control proving the probe can actually detect a leak.
A final section confirms the wiring into `early/scoring.py`'s `_structural_quality`,
`_volatility_compression` and `_volume_behaviour` — the three §34.5 components these
five indicators feed — without a seventh component being invented.
"""
from __future__ import annotations

import inspect

import numpy as np
import pandas as pd
import pytest

from research.charting.config import BARS_COLUMNS, CONFIG
from research.charting.early import indicators
from research.charting.early import scoring as _scoring
from research.charting.early.records import find_range_candidate_as_of
from research.charting.early.scoring import compute_early_scores
from research.charting.geometry import boundary_drift, ols_slope
from research.charting.series import atr as atr_series
from research.charting.series import bollinger, relative_volume
from research.charting.swings import find_swings
from research.charting.tests import synth


# ── Shared helpers (locally defined, per this package's own convention — see
# test_early_records.py's own `_extend_range_bound`, redefined there rather than
# imported from test_early_lookahead.py) ─────────────────────────────────────


def _poison_after(bars: pd.DataFrame, t: int) -> pd.DataFrame:
    """Every row strictly after `t` becomes a deterministic adversarial extreme
    (alternating huge/tiny OHLCV) -- rows [0, t] are left byte-identical. Mirrors the
    poison helper used throughout this repo's other lookahead probes."""
    poisoned = bars.copy()
    for i in range(t + 1, len(bars)):
        if (i - t) % 2 == 1:
            poisoned.loc[i, ["open", "high", "low", "close"]] = [9999.0, 9999.5, 9998.5, 9999.0]
            poisoned.loc[i, "volume"] = 9_999_999.0
        else:
            poisoned.loc[i, ["open", "high", "low", "close"]] = [0.02, 0.03, 0.01, 0.02]
            poisoned.loc[i, "volume"] = 1.0
    return poisoned


def _extend_range_bound(bars: pd.DataFrame, n_quiet: int, breakout_close: float) -> pd.DataFrame:
    """RECT-1 + `n_quiet` byte-identical flat bars (no new swing pivots) + one decisive
    breakout bar -- long enough runway for BB_PERIOD+BB_PCTILE_LOOKBACK-1 (24 bars)
    warmup and for a PIT sweep with room to poison."""
    last_date = pd.Timestamp(bars["date"].iloc[-1])
    dates = pd.bdate_range(start=last_date + pd.tseries.offsets.BDay(1), periods=n_quiet + 1)
    rows = [(dates[i], 105.0, 105.6, 104.4, 105.2, 100_000.0) for i in range(n_quiet)]
    rows.append((dates[n_quiet], 105.2, breakout_close + 1.0, 104.7, breakout_close, 250_000.0))
    ext = pd.DataFrame(rows, columns=list(BARS_COLUMNS))
    return pd.concat([bars, ext], ignore_index=True)


def _ascending_lows_bars() -> pd.DataFrame:
    """A zigzag close path whose confirmed swing LOWS rise (100.7 -> 104.7 -> 108.7) and
    whose confirmed swing HIGHS also rise (108.3 -> 114.3 -> 118.3) -- one fixture that
    exercises BOTH "matches the wanted direction" (BULLISH, checks lows) and "opposes the
    wanted direction" (BEARISH, checks highs, but they're RISING not FALLING)."""
    closes = [
        100, 102, 104, 106, 108, 106, 104, 102, 101, 103, 106, 109, 112, 114, 112, 110,
        108, 106, 105, 107, 110, 113, 116, 118, 116, 114, 112, 110, 109, 111, 114, 117, 120,
    ]
    return synth.bars_from_closes([float(c) for c in closes])


def _volume_ramp_bars(n_flat: int = 8, ramp: tuple[float, ...] = (
    100_000, 105_000, 112_000, 120_000, 130_000, 142_000, 156_000, 172_000, 190_000, 210_000, 232_000, 256_000,
)) -> pd.DataFrame:
    """Flat closes throughout (price is irrelevant to `volume_accumulation_as_of`), flat
    volume for `n_flat` bars then a smooth increasing ramp -- a genuine "gradual increase
    in volume before a move" shape, distinct from a single-bar spike."""
    vols = [100_000.0] * n_flat + list(ramp)
    dates = pd.bdate_range("2024-01-02", periods=len(vols))
    rows = []
    prev = 105.0
    for d, v in zip(dates, vols):
        rows.append((d, prev, prev + 0.2, prev - 0.2, prev, float(v)))
    return pd.DataFrame(rows, columns=list(BARS_COLUMNS))


def _failed_breakout_bars() -> pd.DataFrame:
    """8 bars against an implied resistance of 110.0 (atr=2.0, buffer=0.10*2.0=0.20 ->
    piercing threshold 110.20): bars 1 and 3 pierce intrabar and close back below 110 (two
    genuine "failed attempts"); bar 4 stops just short of the piercing threshold (no
    attempt); the rest are quiet."""
    rows = [
        ("2024-01-02", 108.0, 109.0, 107.5, 108.5, 100_000.0),  # idx0 quiet
        ("2024-01-03", 108.5, 111.0, 108.0, 109.0, 100_000.0),  # idx1 pierce + reject
        ("2024-01-04", 109.0, 109.5, 108.5, 109.2, 100_000.0),  # idx2 quiet
        ("2024-01-05", 109.2, 110.9, 108.8, 109.5, 100_000.0),  # idx3 pierce + reject
        ("2024-01-08", 109.5, 110.0, 109.0, 109.8, 100_000.0),  # idx4 no pierce (110.0 <= 110.20)
        ("2024-01-09", 109.8, 110.0, 109.5, 109.9, 100_000.0),  # idx5 quiet
        ("2024-01-10", 109.9, 110.0, 109.6, 109.95, 100_000.0),  # idx6 quiet
        ("2024-01-11", 109.95, 110.05, 109.7, 109.9, 100_000.0),  # idx7 quiet
    ]
    df = pd.DataFrame(rows, columns=list(BARS_COLUMNS))
    df["date"] = pd.to_datetime(df["date"])
    return df


# ══════════════════════════════════════════════════════════════════════════════
# §34.4 #2 Bollinger Band Width — indicators.bb_width_compression_as_of
# ══════════════════════════════════════════════════════════════════════════════


def test_bb_width_compression_insufficient_before_warmup():
    """RECT-1 alone (20 bars) is short of the v1 warmup (BB_PERIOD + BB_PCTILE_LOOKBACK -
    1 = 24 bars) -- an honest `None`, not a fabricated number."""
    bars = synth.rect1()
    res = indicators.bb_width_compression_as_of(bars, 19)
    assert res.percentile is None
    assert res.score is None


def test_bb_width_compression_matches_series_layer_and_score_formula():
    base = _extend_range_bound(synth.rect1(), n_quiet=20, breakout_close=113.0)
    t = 25
    res = indicators.bb_width_compression_as_of(base, t)
    assert res.percentile is not None
    direct = float(
        indicators.bb_width_percentile(
            base.iloc[: t + 1].reset_index(drop=True),
            bb_period=indicators.BB_PERIOD, lookback=indicators.BB_PCTILE_LOOKBACK,
        ).iloc[-1]
    )
    assert res.percentile == pytest.approx(direct)
    assert res.score == pytest.approx(1.0 - direct / 100.0)
    assert 0.0 <= res.score <= 1.0


def test_bb_width_compression_rejects_out_of_range_t():
    bars = synth.rect1()
    with pytest.raises(ValueError):
        indicators.bb_width_compression_as_of(bars, len(bars))
    with pytest.raises(ValueError):
        indicators.bb_width_compression_as_of(bars, -1)


def test_probe_bb_width_compression_unchanged_by_poisoning_every_bar_after_t():
    base = _extend_range_bound(synth.rect1(), n_quiet=20, breakout_close=113.0)
    n = len(base)
    checked = 0
    for t in range(20, n - 1):
        poisoned = _poison_after(base, t)
        pd.testing.assert_frame_equal(
            poisoned.iloc[: t + 1].reset_index(drop=True), base.iloc[: t + 1].reset_index(drop=True)
        )
        a = indicators.bb_width_compression_as_of(base, t)
        b = indicators.bb_width_compression_as_of(poisoned, t)
        assert a == b, f"leak detected at t={t}"
        checked += 1
    assert checked >= 10


def _peeking_bb_width_percentile(bars: pd.DataFrame, t: int, bb_period: int, lookback: int) -> float:
    """NEGATIVE CONTROL ONLY -- deliberately PIT-broken: percentile-ranks bar t's bb_width
    against a window CENTERED on t (extending `lookback // 2` bars past t) instead of a
    trailing window ending at t. Must never be imported outside this test file."""
    width = bollinger(bars, period=bb_period)["bb_width"]
    half = lookback // 2
    lo = max(0, t - half)
    hi = min(len(bars), t + half + 1)
    window = width.iloc[lo:hi].dropna()
    if len(window) <= 1 or not np.isfinite(width.iloc[t]):
        return float("nan")
    current = width.iloc[t]
    rank = int((window <= current).sum())
    return float(rank - 1) / (len(window) - 1) * 100.0


def test_probe_bb_width_compression_negative_control_is_caught():
    base = _extend_range_bound(synth.rect1(), n_quiet=20, breakout_close=113.0)
    t = 25
    poisoned = _poison_after(base, t)
    pd.testing.assert_frame_equal(poisoned.iloc[: t + 1].reset_index(drop=True), base.iloc[: t + 1].reset_index(drop=True))

    peek_a = _peeking_bb_width_percentile(base, t, indicators.BB_PERIOD, indicators.BB_PCTILE_LOOKBACK)
    peek_b = _peeking_bb_width_percentile(poisoned, t, indicators.BB_PERIOD, indicators.BB_PCTILE_LOOKBACK)
    assert peek_a != peek_b, "negative control failed to detect the leak"

    real_a = indicators.bb_width_compression_as_of(base, t)
    real_b = indicators.bb_width_compression_as_of(poisoned, t)
    assert real_a == real_b


# ══════════════════════════════════════════════════════════════════════════════
# §34.4 #3 Higher lows / lower highs — indicators.structure_direction_as_of
# ══════════════════════════════════════════════════════════════════════════════


def test_structure_direction_insufficient_with_fewer_than_two_same_kind_pivots():
    """RECT-1 at t=14: exactly one confirmed LOW pivot (idx10, confirmed at 13) and ATR is
    already valid (15 bars) -- insufficient because of pivot count, not ATR."""
    bars = synth.rect1()
    atr_now = float(atr_series(bars.iloc[:15].reset_index(drop=True), period=CONFIG["atr_period"]).iloc[-1])
    assert np.isfinite(atr_now) and atr_now > 0
    res = indicators.structure_direction_as_of(bars, 14, "BULLISH", atr_now, CONFIG)
    assert res.direction is None
    assert res.score is None


def test_structure_direction_insufficient_when_atr_invalid():
    bars = synth.rect1()
    for bad_atr in (None, 0.0, float("nan")):
        res = indicators.structure_direction_as_of(bars, 19, "BULLISH", bad_atr, CONFIG)
        assert res.score is None


def test_structure_direction_bullish_scores_high_for_ascending_lows():
    bars = _ascending_lows_bars()
    t = len(bars) - 1
    atr_now = float(atr_series(bars, period=CONFIG["atr_period"]).iloc[-1])
    res = indicators.structure_direction_as_of(bars, t, "BULLISH", atr_now, CONFIG)
    assert res.direction == "RISING"
    assert res.score == pytest.approx(1.0)


def test_structure_direction_bearish_scores_low_when_highs_rise_instead_of_falling():
    """Same fixture, opposite direction: confirmed HIGHS are also rising, which is the
    OPPOSITE of what a BEARISH candidate's "lower highs" needs -- a real, low score, not
    an insufficient reading."""
    bars = _ascending_lows_bars()
    t = len(bars) - 1
    atr_now = float(atr_series(bars, period=CONFIG["atr_period"]).iloc[-1])
    res = indicators.structure_direction_as_of(bars, t, "BEARISH", atr_now, CONFIG)
    assert res.direction == "RISING"
    assert res.score == pytest.approx(0.0)


def test_probe_structure_direction_unchanged_by_poisoning_every_bar_after_t():
    base = _ascending_lows_bars()
    n = len(base)
    checked = 0
    for t in range(9, n - 1):
        atr_t = float(atr_series(base.iloc[: t + 1].reset_index(drop=True), period=CONFIG["atr_period"]).iloc[-1])
        if not np.isfinite(atr_t) or atr_t <= 0:
            continue
        poisoned = _poison_after(base, t)
        pd.testing.assert_frame_equal(
            poisoned.iloc[: t + 1].reset_index(drop=True), base.iloc[: t + 1].reset_index(drop=True)
        )
        a = indicators.structure_direction_as_of(base, t, "BULLISH", atr_t, CONFIG)
        b = indicators.structure_direction_as_of(poisoned, t, "BULLISH", atr_t, CONFIG)
        assert a == b, f"leak detected at t={t}"
        checked += 1
    assert checked >= 10


def _peeking_structure_direction(bars_full: pd.DataFrame, t: int, direction: str, atr_now: float, cfg: dict):
    """NEGATIVE CONTROL ONLY -- deliberately PIT-broken exactly the way `swings.py`'s own
    module docstring warns against: "called on a wider frame and have its output filtered
    afterward". Runs `find_swings` on the FULL bars frame (not `bars.iloc[:t+1]`) and only
    THEN filters `pivot_index <= t` -- a pivot in the last `right_bars` bars before t can
    become confirmed using future context a correctly PIT-truncated call never sees. Must
    never be imported outside this test file."""
    pivots = [p for p in find_swings(bars_full) if p.pivot_index <= t]
    kind = "LOW" if direction == "BULLISH" else "HIGH"
    same = sorted((p for p in pivots if p.kind == kind), key=lambda p: p.pivot_index)
    if len(same) < 2:
        return None
    xs = [float(p.pivot_index) for p in same]
    ys = [p.price for p in same]
    slope = ols_slope(xs, ys)
    length_bars = int(xs[-1] - xs[0])
    return boundary_drift(slope, length_bars, atr_now, cfg)


def test_probe_structure_direction_negative_control_is_caught():
    base = _ascending_lows_bars()
    t = 29  # the LAST low pivot (idx29) is only confirmable with bars 30-32 as right-context
    atr_t = float(atr_series(base.iloc[: t + 1].reset_index(drop=True), period=CONFIG["atr_period"]).iloc[-1])
    poisoned = _poison_after(base, t)
    pd.testing.assert_frame_equal(poisoned.iloc[: t + 1].reset_index(drop=True), base.iloc[: t + 1].reset_index(drop=True))

    peek_a = _peeking_structure_direction(base, t, "BULLISH", atr_t, CONFIG)
    peek_b = _peeking_structure_direction(poisoned, t, "BULLISH", atr_t, CONFIG)
    assert peek_a is not None and peek_b is not None
    assert peek_a.drift_atr != peek_b.drift_atr, "negative control failed to detect the leak"

    real_a = indicators.structure_direction_as_of(base, t, "BULLISH", atr_t, CONFIG)
    real_b = indicators.structure_direction_as_of(poisoned, t, "BULLISH", atr_t, CONFIG)
    assert real_a == real_b


# ══════════════════════════════════════════════════════════════════════════════
# §34.4 #4 Support/resistance stability — indicators.sr_stability_as_of
# ══════════════════════════════════════════════════════════════════════════════


def test_sr_stability_insufficient_when_atr_invalid():
    bars = synth.rect1()
    res = indicators.sr_stability_as_of(bars, 19, None, CONFIG)
    assert res.score is None
    assert res.high is None and res.low is None


def test_sr_stability_stable_case_for_rect1_scores_near_one():
    """RECT-1's touches are exact price repeats (110.0/110.0 resistance, 100.0/100.0
    support) -- both sides refit with zero shift and zero residual, delegating to the same
    `geometry.boundary_stability` (NI-2 #7) `test_geometry.py` already exercises directly."""
    bars = synth.rect1()
    atr_now = float(atr_series(bars, period=CONFIG["atr_period"]).iloc[-1])
    res = indicators.sr_stability_as_of(bars, 19, atr_now, CONFIG)
    assert res.high is not None and res.low is not None
    assert res.high.stable and res.low.stable
    assert res.score == pytest.approx(1.0)


def test_probe_sr_stability_unchanged_by_poisoning_every_bar_after_t():
    base = synth.rect1()
    n = len(base)
    checked = 0
    for t in range(14, n - 1):
        atr_t = float(atr_series(base.iloc[: t + 1].reset_index(drop=True), period=CONFIG["atr_period"]).iloc[-1])
        if not np.isfinite(atr_t) or atr_t <= 0:
            continue
        poisoned = _poison_after(base, t)
        pd.testing.assert_frame_equal(
            poisoned.iloc[: t + 1].reset_index(drop=True), base.iloc[: t + 1].reset_index(drop=True)
        )
        a = indicators.sr_stability_as_of(base, t, atr_t, CONFIG)
        b = indicators.sr_stability_as_of(poisoned, t, atr_t, CONFIG)
        assert a == b, f"leak detected at t={t}"
        checked += 1
    assert checked >= 5


def _peeking_sr_stability_touch_counts(bars_full: pd.DataFrame, t: int, atr_now: float, cfg: dict) -> tuple[int, int]:
    """NEGATIVE CONTROL ONLY -- same documented `find_swings`-on-the-full-frame-then-
    filter leak as `_peeking_structure_direction` above, applied to level clustering
    instead of a slope fit. Returns (resistance touch count, support touch count). Must
    never be imported outside this test file."""
    from research.charting.geometry import cluster_pivots_into_levels

    pivots = [p for p in find_swings(bars_full) if p.pivot_index <= t]
    highs = cluster_pivots_into_levels(pivots, bars_full, atr_now, cfg, kind="HIGH")
    lows = cluster_pivots_into_levels(pivots, bars_full, atr_now, cfg, kind="LOW")
    best_high = max(highs, key=lambda l: len(l.touches)) if highs else None
    best_low = max(lows, key=lambda l: len(l.touches)) if lows else None
    return (
        len(best_high.touches) if best_high else 0,
        len(best_low.touches) if best_low else 0,
    )


def test_probe_sr_stability_negative_control_is_caught():
    """t=16 in RECT-1: bar12's support touch (idx16) is NOT yet confirmed (needs bars
    through idx19) -- a correctly-truncated view never sees it, but peeking at the full,
    naturally-continuing frame does (its real continuation confirms it), while poisoning
    bars 17-19 into adversarial extremes destroys that same confirmation."""
    base = synth.rect1()
    t = 16
    atr_t = float(atr_series(base.iloc[: t + 1].reset_index(drop=True), period=CONFIG["atr_period"]).iloc[-1])
    poisoned = _poison_after(base, t)
    pd.testing.assert_frame_equal(poisoned.iloc[: t + 1].reset_index(drop=True), base.iloc[: t + 1].reset_index(drop=True))

    peek_a = _peeking_sr_stability_touch_counts(base, t, atr_t, CONFIG)
    peek_b = _peeking_sr_stability_touch_counts(poisoned, t, atr_t, CONFIG)
    assert peek_a != peek_b, "negative control failed to detect the leak"
    assert peek_a == (2, 2)
    assert peek_b == (2, 1)

    real_a = indicators.sr_stability_as_of(base, t, atr_t, CONFIG)
    real_b = indicators.sr_stability_as_of(poisoned, t, atr_t, CONFIG)
    assert real_a == real_b


# ══════════════════════════════════════════════════════════════════════════════
# §34.4 #7 Volume accumulation — indicators.volume_accumulation_as_of
# ══════════════════════════════════════════════════════════════════════════════


def test_volume_accumulation_insufficient_with_fewer_than_two_trailing_points():
    bars = _volume_ramp_bars()
    res = indicators.volume_accumulation_as_of(bars, 0, n=5, trend_bars=5)
    assert res.slope is None
    assert res.score is None


def test_volume_accumulation_flat_volume_is_neutral():
    dates = pd.bdate_range("2024-01-02", periods=15)
    rows = [(d, 105.0, 105.2, 104.8, 105.0, 100_000.0) for d in dates]
    bars = pd.DataFrame(rows, columns=list(BARS_COLUMNS))
    res = indicators.volume_accumulation_as_of(bars, 14, n=5, trend_bars=5)
    assert res.slope == pytest.approx(0.0)
    assert res.score == pytest.approx(0.5)


def test_volume_accumulation_rising_volume_scores_above_neutral():
    bars = _volume_ramp_bars()
    t = len(bars) - 1
    res = indicators.volume_accumulation_as_of(bars, t, n=5, trend_bars=5)
    assert res.slope is not None and res.slope > 0.0
    assert res.score > 0.5
    rv = relative_volume(bars, n=5)
    trail = rv.tail(5).dropna()
    expected_slope = ols_slope(list(range(len(trail))), trail.tolist())
    assert res.slope == pytest.approx(expected_slope)


def test_probe_volume_accumulation_unchanged_by_poisoning_every_bar_after_t():
    base = _volume_ramp_bars()
    n = len(base)
    checked = 0
    for t in range(6, n - 1):
        poisoned = _poison_after(base, t)
        pd.testing.assert_frame_equal(
            poisoned.iloc[: t + 1].reset_index(drop=True), base.iloc[: t + 1].reset_index(drop=True)
        )
        a = indicators.volume_accumulation_as_of(base, t, n=5, trend_bars=5)
        b = indicators.volume_accumulation_as_of(poisoned, t, n=5, trend_bars=5)
        assert a == b, f"leak detected at t={t}"
        checked += 1
    assert checked >= 10


def _peeking_volume_accumulation_slope(bars_full: pd.DataFrame, t: int, n: int, trend_bars: int) -> float | None:
    """NEGATIVE CONTROL ONLY -- deliberately off-by-one into the future: the trailing
    window ends at `t + 1` instead of `t`. Must never be imported outside this test file."""
    rv = relative_volume(bars_full, n=n)
    trail = rv.iloc[t - trend_bars + 2 : t + 2].dropna()
    if len(trail) < 2:
        return None
    return ols_slope(list(range(len(trail))), trail.tolist())


def test_probe_volume_accumulation_negative_control_is_caught():
    base = _volume_ramp_bars()
    t = 12
    poisoned = _poison_after(base, t)
    pd.testing.assert_frame_equal(poisoned.iloc[: t + 1].reset_index(drop=True), base.iloc[: t + 1].reset_index(drop=True))

    peek_a = _peeking_volume_accumulation_slope(base, t, n=5, trend_bars=5)
    peek_b = _peeking_volume_accumulation_slope(poisoned, t, n=5, trend_bars=5)
    assert peek_a is not None and peek_b is not None
    assert peek_a != peek_b, "negative control failed to detect the leak"

    real_a = indicators.volume_accumulation_as_of(base, t, n=5, trend_bars=5)
    real_b = indicators.volume_accumulation_as_of(poisoned, t, n=5, trend_bars=5)
    assert real_a == real_b


# ══════════════════════════════════════════════════════════════════════════════
# §34.4 #11 Failed breakout attempts — indicators.failed_breakout_attempts_as_of
# ══════════════════════════════════════════════════════════════════════════════


def test_failed_breakout_attempts_insufficient_cases():
    bars = _failed_breakout_bars()
    assert indicators.failed_breakout_attempts_as_of(bars, 3, None, "HIGH", 2.0, 0).score is None
    assert indicators.failed_breakout_attempts_as_of(bars, 3, 110.0, "HIGH", None, 0).score is None
    assert indicators.failed_breakout_attempts_as_of(bars, 3, 110.0, "HIGH", 2.0, 10).score is None  # window_start > t


def test_failed_breakout_attempts_counts_intrabar_piercings_that_close_back_inside():
    bars = _failed_breakout_bars()
    t = len(bars) - 1
    res = indicators.failed_breakout_attempts_as_of(bars, t, 110.0, "HIGH", 2.0, 0)
    assert res.attempt_count == 2
    assert res.score == pytest.approx(2 / indicators.FAILED_BREAKOUT_SATURATION)


def test_failed_breakout_attempts_mirrors_for_the_low_side():
    rows = [
        ("2024-01-02", 102.0, 102.5, 101.0, 101.5, 100_000.0),
        ("2024-01-03", 101.5, 102.0, 99.5, 101.0, 100_000.0),  # pierce + reject
        ("2024-01-04", 101.0, 101.5, 100.5, 101.2, 100_000.0),
        ("2024-01-05", 101.2, 101.8, 99.6, 100.8, 100_000.0),  # pierce + reject
        ("2024-01-08", 100.8, 101.0, 100.0, 100.5, 100_000.0),  # no pierce (100.0 not < 99.8)
    ]
    df = pd.DataFrame(rows, columns=list(BARS_COLUMNS))
    df["date"] = pd.to_datetime(df["date"])
    res = indicators.failed_breakout_attempts_as_of(df, 4, 100.0, "LOW", 2.0, 0)
    assert res.attempt_count == 2


def test_failed_breakout_attempts_zero_is_a_real_reading_not_a_fabricated_absence():
    """RECT-1 at t=19: no bar ever pierces resistance or support beyond the buffer -- a
    genuine 0, distinguishable from `None`/insufficient."""
    bars = synth.rect1()
    atr_now = float(atr_series(bars, period=CONFIG["atr_period"]).iloc[-1])
    res = indicators.failed_breakout_attempts_as_of(bars, 19, 110.0, "HIGH", atr_now, 7, CONFIG)
    assert res.attempt_count == 0
    assert res.score == 0.0


def test_probe_failed_breakout_attempts_unchanged_by_poisoning_every_bar_after_t():
    base = _failed_breakout_bars()
    n = len(base)
    checked = 0
    for t in range(1, n - 1):
        poisoned = _poison_after(base, t)
        pd.testing.assert_frame_equal(
            poisoned.iloc[: t + 1].reset_index(drop=True), base.iloc[: t + 1].reset_index(drop=True)
        )
        a = indicators.failed_breakout_attempts_as_of(base, t, 110.0, "HIGH", 2.0, 0)
        b = indicators.failed_breakout_attempts_as_of(poisoned, t, 110.0, "HIGH", 2.0, 0)
        assert a == b, f"leak detected at t={t}"
        checked += 1
    assert checked >= 5


def _peeking_failed_breakout_attempts(
    bars_full: pd.DataFrame, t: int, level_price: float, level_kind: str, atr_now: float, window_start: int,
    buffer_atr: float = indicators.FAILED_BREAKOUT_BUFFER_ATR,
) -> int:
    """NEGATIVE CONTROL ONLY -- deliberately off-by-one: scans through `t + 1` instead of
    `t` on the FULL (unsliced) bars frame. Must never be imported outside this test file."""
    window = bars_full.iloc[window_start : t + 2]
    buffer = buffer_atr * atr_now
    if level_kind == "HIGH":
        pierced = window["high"] > (level_price + buffer)
        rejected = window["close"] < level_price
    else:
        pierced = window["low"] < (level_price - buffer)
        rejected = window["close"] > level_price
    return int((pierced & rejected).sum())


def test_probe_failed_breakout_attempts_negative_control_is_caught():
    base = _failed_breakout_bars()
    t = 2  # bar t+1 = idx3 is a genuine pierce+reject in the real continuation
    poisoned = _poison_after(base, t)
    pd.testing.assert_frame_equal(poisoned.iloc[: t + 1].reset_index(drop=True), base.iloc[: t + 1].reset_index(drop=True))

    peek_a = _peeking_failed_breakout_attempts(base, t, 110.0, "HIGH", 2.0, 0)
    peek_b = _peeking_failed_breakout_attempts(poisoned, t, 110.0, "HIGH", 2.0, 0)
    assert peek_a != peek_b, "negative control failed to detect the leak"
    assert peek_a == 2 and peek_b == 1

    real_a = indicators.failed_breakout_attempts_as_of(base, t, 110.0, "HIGH", 2.0, 0)
    real_b = indicators.failed_breakout_attempts_as_of(poisoned, t, 110.0, "HIGH", 2.0, 0)
    assert real_a == real_b


# ══════════════════════════════════════════════════════════════════════════════
# Wiring into early/scoring.py — no seventh component invented
# ══════════════════════════════════════════════════════════════════════════════


def test_structural_quality_wires_in_all_three_new_indicators():
    src = inspect.getsource(_scoring._structural_quality)
    assert "structure_direction_as_of" in src
    assert "sr_stability_as_of" in src
    assert "failed_breakout_attempts_as_of" in src


def test_volatility_compression_wires_in_bb_width():
    src = inspect.getsource(_scoring._volatility_compression)
    assert "bb_width_compression_as_of" in src


def test_volume_behaviour_wires_in_volume_accumulation():
    src = inspect.getsource(_scoring._volume_behaviour)
    assert "volume_accumulation_as_of" in src


def test_early_score_weights_still_has_exactly_the_six_prd_components():
    """§34.5's table names exactly six components -- confirms this ticket's wiring folded
    every new indicator INTO one of them rather than inventing a seventh."""
    assert set(CONFIG["early_score_weights"]) == {
        "structural_quality", "volatility_compression", "distance_to_trigger",
        "volume_behaviour", "momentum_relative_strength", "market_sector_context",
    }


def test_compute_early_scores_end_to_end_still_bounded_with_new_indicators_active():
    """Integration smoke test on a fixture long enough (41 bars) for the BB and
    volume-accumulation warmups to actually engage (not just fall back to the
    pre-existing formula) -- every OK-status score/component stays in [0,1]."""
    base = _extend_range_bound(synth.rect1(), n_quiet=20, breakout_close=113.0)
    cand = find_range_candidate_as_of(base, 19)
    t = 25
    bb = indicators.bb_width_compression_as_of(base, t)
    assert bb.score is not None  # sanity: BB really is warmed up at this t, not silently skipped

    scores = compute_early_scores(
        base, t, trigger_level=cand.trigger_level, invalidation_level=cand.invalidation_level, direction="BULLISH"
    )
    for sv in (scores.formation_score, scores.readiness_score, scores.confirmation_score, scores.failure_risk):
        if sv.status == "OK":
            assert 0.0 <= sv.value <= 1.0
    for comp in scores.components.values():
        if comp.status == "OK":
            assert 0.0 <= comp.value <= 1.0
