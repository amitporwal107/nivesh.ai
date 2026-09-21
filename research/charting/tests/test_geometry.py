"""§30.1 NI-2 geometry predicates — positive and negative cases at and around each
threshold. Every expected number below was either hand-derived from the formula in
`ni2-geometry-predicates.md` or independently verified in a throwaway interpreter session
before being pinned here (not guessed and then rationalised).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from research.charting import geometry
from research.charting.config import CONFIG
from research.charting.swings import Pivot


# ── 1. Boundary drift (flat / rising / falling) ──────────────────────────────


def test_boundary_drift_flat_when_drift_at_or_below_threshold():
    # slope=0.05, length=20, atr=2.0 -> drift_atr = 0.05*20/2 = 0.5 == flat_boundary_max_drift_atr
    d = geometry.boundary_drift(slope=0.05, length_bars=20, atr=2.0, cfg=CONFIG)
    assert d.drift_atr == pytest.approx(0.50)
    assert d.direction == "FLAT"  # exactly at the threshold is still flat (<=)


def test_boundary_drift_small_slope_is_flat():
    d = geometry.boundary_drift(slope=0.01, length_bars=20, atr=2.0, cfg=CONFIG)
    assert d.drift_atr == pytest.approx(0.1)
    assert d.direction == "FLAT"


def test_boundary_drift_rising_at_exact_threshold():
    # slope=0.075, length=20, atr=2.0 -> drift_atr = 0.75 == sloped_boundary_min_drift_atr
    d = geometry.boundary_drift(slope=0.075, length_bars=20, atr=2.0, cfg=CONFIG)
    assert d.drift_atr == pytest.approx(0.75)
    assert d.direction == "RISING"  # exactly at the threshold counts (>=)


def test_boundary_drift_falling_mirrors_rising():
    d = geometry.boundary_drift(slope=-0.075, length_bars=20, atr=2.0, cfg=CONFIG)
    assert d.drift_atr == pytest.approx(0.75)
    assert d.direction == "FALLING"


def test_boundary_drift_strongly_rising():
    d = geometry.boundary_drift(slope=0.10, length_bars=20, atr=2.0, cfg=CONFIG)
    assert d.drift_atr == pytest.approx(1.0)
    assert d.direction == "RISING"


def test_boundary_drift_indeterminate_between_the_two_thresholds():
    # drift_atr = 0.6: strictly above flat_max(0.50) and strictly below sloped_min(0.75).
    d = geometry.boundary_drift(slope=0.06, length_bars=20, atr=2.0, cfg=CONFIG)
    assert d.drift_atr == pytest.approx(0.6)
    assert d.direction == "INDETERMINATE"


def test_boundary_drift_zero_slope_is_flat():
    d = geometry.boundary_drift(slope=0.0, length_bars=50, atr=1.0, cfg=CONFIG)
    assert d.direction == "FLAT"
    assert d.drift_atr == pytest.approx(0.0)


@pytest.mark.parametrize("atr", [0.0, -1.0, float("nan"), None])
def test_boundary_drift_indeterminate_on_unusable_atr(atr):
    d = geometry.boundary_drift(slope=0.5, length_bars=20, atr=atr, cfg=CONFIG)
    assert d.direction == "INDETERMINATE"
    assert np.isnan(d.drift_atr)


def test_boundary_drift_indeterminate_on_nonpositive_length():
    d = geometry.boundary_drift(slope=0.5, length_bars=0, atr=2.0, cfg=CONFIG)
    assert d.direction == "INDETERMINATE"


# ── ols_slope ─────────────────────────────────────────────────────────────────


def test_ols_slope_perfect_line():
    assert geometry.ols_slope([0, 1, 2, 3], [10.0, 12.0, 14.0, 16.0]) == pytest.approx(2.0)


def test_ols_slope_declining_line():
    assert geometry.ols_slope([0, 10, 20], [100.0, 98.0, 96.0]) == pytest.approx(-0.2)


def test_ols_slope_degenerate_single_x_value_is_zero():
    assert geometry.ols_slope([5, 5, 5], [1.0, 2.0, 3.0]) == 0.0


def test_ols_slope_fewer_than_two_points_is_zero():
    assert geometry.ols_slope([5], [1.0]) == 0.0
    assert geometry.ols_slope([], []) == 0.0


# ── Fixture #10: "ascending triangle" with declining support 100->98->96 ────


def test_fixture_10_declining_support_classifies_falling_not_rising():
    """test-plan.md #10: a 'wrong trendline slope' fixture — support legs 100 -> 98 -> 96
    over 20 bars must classify FALLING (never RISING), and a genuinely flat leg (<0.75 ATR
    drift) must not pass as rising either."""
    slope = geometry.ols_slope([0, 10, 20], [100.0, 98.0, 96.0])
    d = geometry.boundary_drift(slope, length_bars=20, atr=2.0, cfg=CONFIG)
    assert d.direction == "FALLING"
    assert d.direction != "RISING"

    # Flat-leg control: same length/ATR, a much smaller decline must not read as sloped at all.
    flat_slope = geometry.ols_slope([0, 10, 20], [100.0, 99.9, 99.8])
    d_flat = geometry.boundary_drift(flat_slope, length_bars=20, atr=2.0, cfg=CONFIG)
    assert d_flat.direction == "FLAT"
    assert d_flat.direction != "RISING"


# ── Convergence ratio (triangles) ────────────────────────────────────────────


def test_convergence_ratio_converging_below_threshold():
    c = geometry.convergence_ratio(gap_at_first_bar=10.0, gap_at_last_bar=6.0, cfg=CONFIG)
    assert c.ratio == pytest.approx(0.6)
    assert c.converging is True


def test_convergence_ratio_at_exact_threshold_is_converging():
    c = geometry.convergence_ratio(gap_at_first_bar=10.0, gap_at_last_bar=7.0, cfg=CONFIG)
    assert c.ratio == pytest.approx(0.70)
    assert c.converging is True  # <=, inclusive


def test_convergence_ratio_above_threshold_is_not_converging():
    c = geometry.convergence_ratio(gap_at_first_bar=10.0, gap_at_last_bar=8.0, cfg=CONFIG)
    assert c.ratio == pytest.approx(0.8)
    assert c.converging is False


def test_convergence_ratio_widening_gap_is_not_converging():
    c = geometry.convergence_ratio(gap_at_first_bar=5.0, gap_at_last_bar=9.0, cfg=CONFIG)
    assert c.converging is False


@pytest.mark.parametrize("gap_first", [0.0, -1.0, float("nan")])
def test_convergence_ratio_unusable_first_gap_is_not_converging(gap_first):
    c = geometry.convergence_ratio(gap_at_first_bar=gap_first, gap_at_last_bar=1.0, cfg=CONFIG)
    assert c.converging is False
    assert np.isnan(c.ratio)


# ── Pivot clustering into levels (§30.1 #2) ──────────────────────────────────


def _bars(n: int) -> pd.DataFrame:
    return pd.DataFrame({
        "date": pd.bdate_range("2024-01-02", periods=n),
        "open": [100.0] * n, "high": [102.0] * n, "low": [98.0] * n, "close": [100.0] * n, "volume": [100.0] * n,
    })


def _pivot(bars: pd.DataFrame, idx: int, price: float, kind: str = "HIGH") -> Pivot:
    return Pivot(
        kind=kind, pivot_index=idx, pivot_date=bars["date"].iloc[idx], price=price,
        confirmed_index=idx + 3, confirmed_date=bars["date"].iloc[idx + 3],
    )


def test_cluster_pivots_merges_within_width_and_separates_beyond_it():
    """Chain-link clustering by price (width = level_cluster_width_atr * atr = 0.35 with
    atr=1.0): touches at 100.0/100.1/100.2 (gaps 0.1, all <= 0.35) merge into one cluster;
    the touches near 105.0 (gap 4.8 from the first cluster) form a separate cluster."""
    bars = _bars(25)
    pivots = [
        _pivot(bars, 2, 100.0), _pivot(bars, 5, 100.2), _pivot(bars, 8, 100.1),
        _pivot(bars, 12, 105.0), _pivot(bars, 13, 105.05), _pivot(bars, 17, 105.02),
    ]
    levels = geometry.cluster_pivots_into_levels(pivots, bars, atr=1.0, cfg=CONFIG, kind="HIGH")
    assert len(levels) == 2
    by_price = sorted(levels, key=lambda lv: lv.price)

    low_cluster = by_price[0]
    assert low_cluster.price == pytest.approx(100.1)  # equal volumes -> simple mean of 100.0/100.2/100.1
    assert sorted(t.pivot_index for t in low_cluster.touches) == [2, 5, 8]

    high_cluster = by_price[1]
    # idx13 is only 1 bar after the kept idx12 (< touch_min_separation_bars=3) -> dropped;
    # idx17 is 5 bars after idx12 -> kept. Only 2 touches survive, not 3.
    assert sorted(t.pivot_index for t in high_cluster.touches) == [12, 17]
    assert high_cluster.price == pytest.approx((105.0 + 105.02) / 2)


def test_cluster_pivots_separation_rule_prevents_a_single_chop_inflating_touch_count():
    """ni2-geometry-predicates.md: 'without [the separation rule] a single three-day chop
    at one price counts as three touches'."""
    bars = _bars(20)
    pivots = [_pivot(bars, 4, 110.0), _pivot(bars, 5, 110.0), _pivot(bars, 6, 110.0)]
    levels = geometry.cluster_pivots_into_levels(pivots, bars, atr=1.0, cfg=CONFIG, kind="HIGH")
    assert len(levels) == 1
    assert len(levels[0].touches) == 1  # only the first of the three 1-bar-apart touches survives


def test_cluster_pivots_filters_by_kind():
    bars = _bars(20)
    pivots = [_pivot(bars, 4, 110.0, "HIGH"), _pivot(bars, 8, 90.0, "LOW")]
    highs = geometry.cluster_pivots_into_levels(pivots, bars, atr=1.0, cfg=CONFIG, kind="HIGH")
    lows = geometry.cluster_pivots_into_levels(pivots, bars, atr=1.0, cfg=CONFIG, kind="LOW")
    assert len(highs) == 1 and highs[0].kind == "RESISTANCE"
    assert len(lows) == 1 and lows[0].kind == "SUPPORT"


def test_cluster_pivots_empty_input_or_unusable_atr_returns_no_levels():
    bars = _bars(10)
    assert geometry.cluster_pivots_into_levels([], bars, atr=1.0, cfg=CONFIG, kind="HIGH") == []
    pivots = [_pivot(bars, 4, 110.0)]
    assert geometry.cluster_pivots_into_levels(pivots, bars, atr=0.0, cfg=CONFIG, kind="HIGH") == []
    assert geometry.cluster_pivots_into_levels(pivots, bars, atr=float("nan"), cfg=CONFIG, kind="HIGH") == []


# ── Rejection fraction / touch_from_pivot ────────────────────────────────────


def test_touch_from_pivot_rejection_fraction_high():
    bars = pd.DataFrame({
        "date": pd.bdate_range("2024-01-02", periods=5),
        "open": [108.0] * 5, "high": [110.0] * 5, "low": [107.5] * 5, "close": [109.0] * 5, "volume": [200.0] * 5,
    })
    p = Pivot(kind="HIGH", pivot_index=1, pivot_date=bars["date"].iloc[1], price=110.0,
              confirmed_index=4, confirmed_date=bars["date"].iloc[4])
    touch = geometry.touch_from_pivot(p, bars)
    # wick_beyond = high - max(open, close) = 110 - 109 = 1.0; range = high-low = 2.5 -> 0.4
    assert touch.rejection == pytest.approx(0.4)
    assert touch.volume == pytest.approx(200.0)
    assert touch.bar_range == pytest.approx(2.5)


def test_touch_from_pivot_rejection_fraction_low():
    bars = pd.DataFrame({
        "date": pd.bdate_range("2024-01-02", periods=5),
        "open": [103.0] * 5, "high": [104.5] * 5, "low": [100.0] * 5, "close": [103.5] * 5, "volume": [150.0] * 5,
    })
    p = Pivot(kind="LOW", pivot_index=2, pivot_date=bars["date"].iloc[2], price=100.0,
              confirmed_index=5 if len(bars) > 5 else 4, confirmed_date=bars["date"].iloc[-1])
    touch = geometry.touch_from_pivot(p, bars)
    # wick_beyond = min(open, close) - low = 103.0 - 100.0 = 3.0; range = 4.5 -> 0.6667
    assert touch.rejection == pytest.approx(3.0 / 4.5)


def test_rejection_fraction_zero_range_bar_is_zero_not_error():
    bars = pd.DataFrame({
        "date": pd.bdate_range("2024-01-02", periods=3),
        "open": [100.0] * 3, "high": [100.0] * 3, "low": [100.0] * 3, "close": [100.0] * 3, "volume": [1.0] * 3,
    })
    p = Pivot(kind="HIGH", pivot_index=1, pivot_date=bars["date"].iloc[1], price=100.0,
              confirmed_index=2, confirmed_date=bars["date"].iloc[2])
    touch = geometry.touch_from_pivot(p, bars)
    assert touch.rejection == 0.0


# ── Level strength — five stored components (§30.1 #3) ──────────────────────


def test_level_strength_matches_hand_computation():
    touches = (
        geometry.Touch(pivot_index=5, pivot_date=pd.Timestamp("2024-01-08"), confirmed_index=8,
                        confirmed_date=pd.Timestamp("2024-01-11"), kind="HIGH", price=110.0,
                        volume=200.0, bar_range=2.5, rejection=0.4),
        geometry.Touch(pivot_index=10, pivot_date=pd.Timestamp("2024-01-15"), confirmed_index=13,
                        confirmed_date=pd.Timestamp("2024-01-18"), kind="HIGH", price=110.0,
                        volume=100.0, bar_range=1.2, rejection=0.41666666666667),
    )
    level = geometry.Level(kind="RESISTANCE", price=110.0, touches=touches)

    n = 16
    closes = np.array([100.0] * n)
    closes[[2, 5, 9, 10]] = [109.5, 110.0, 110.6, 110.0]  # exactly 4 inside band [109.3, 110.7]
    bars = pd.DataFrame({"close": closes})

    relvol = pd.Series([np.nan] * n)
    relvol.iloc[5] = 1.2
    relvol.iloc[10] = 1.8

    result = geometry.level_strength(
        level, as_of_index=15, window_start=0, window_end=15,
        bars=bars, relative_volume=relvol, atr=2.0, cfg=CONFIG,
    )

    assert result.touch_c == pytest.approx(min(2 / 5, 1.0))
    assert result.recency_c == pytest.approx(0.5 ** (5 / 60))
    assert result.rejection_c == pytest.approx((0.4 + 0.41666666666667) / 2)
    assert result.volume_c == pytest.approx(min(((1.2 + 1.8) / 2) / 1.50, 1.0))
    assert result.time_c == pytest.approx(min(4 / (0.25 * 16), 1.0))
    w = CONFIG["strength_weights"]
    expected = w[0] * result.touch_c + w[1] * result.recency_c + w[2] * result.rejection_c + w[3] * result.volume_c + w[4] * result.time_c
    assert result.level_strength == pytest.approx(expected)
    assert result.is_probability is False  # PRD §16: descriptive only


def test_level_strength_touch_saturation_caps_at_one():
    touches = tuple(
        geometry.Touch(pivot_index=i * 5, pivot_date=pd.Timestamp("2024-01-02") + pd.Timedelta(days=i * 5),
                        confirmed_index=i * 5 + 3, confirmed_date=pd.Timestamp("2024-01-05") + pd.Timedelta(days=i * 5),
                        kind="HIGH", price=110.0, volume=100.0, bar_range=1.0, rejection=0.5)
        for i in range(8)  # 8 touches >> strength_touch_saturation=5
    )
    level = geometry.Level(kind="RESISTANCE", price=110.0, touches=touches)
    bars = pd.DataFrame({"close": [100.0] * 40})
    relvol = pd.Series([1.0] * 40)
    result = geometry.level_strength(level, as_of_index=39, window_start=0, window_end=39, bars=bars, relative_volume=relvol, atr=2.0, cfg=CONFIG)
    assert result.touch_c == 1.0


def test_level_strength_empty_touches_is_all_zero():
    level = geometry.Level(kind="RESISTANCE", price=110.0, touches=())
    bars = pd.DataFrame({"close": [100.0] * 10})
    relvol = pd.Series([1.0] * 10)
    result = geometry.level_strength(level, as_of_index=9, window_start=0, window_end=9, bars=bars, relative_volume=relvol, atr=2.0, cfg=CONFIG)
    assert result.touch_c == 0.0
    assert result.recency_c == 0.0
    assert result.rejection_c == 0.0
    assert result.level_strength == 0.0


# ── Minimum rectangle range relative to ATR (§30.1 #4) ───────────────────────


def test_rectangle_range_ok_within_bounds():
    r = geometry.rectangle_range_ok(110.0, 100.0, atr=2.0, cfg=CONFIG)
    assert r.range_atr == pytest.approx(5.0)
    assert r.valid is True


def test_rectangle_range_ok_exact_lower_bound():
    r = geometry.rectangle_range_ok(101.5, 100.0, atr=1.0, cfg=CONFIG)
    assert r.range_atr == pytest.approx(1.50)
    assert r.valid is True


def test_rectangle_range_ok_exact_upper_bound():
    r = geometry.rectangle_range_ok(108.0, 100.0, atr=1.0, cfg=CONFIG)
    assert r.range_atr == pytest.approx(8.00)
    assert r.valid is True


def test_rectangle_range_too_tight_is_invalid():
    r = geometry.rectangle_range_ok(110.0, 109.0, atr=2.0, cfg=CONFIG)
    assert r.range_atr == pytest.approx(0.5)
    assert r.valid is False


def test_rectangle_range_too_wide_is_invalid():
    r = geometry.rectangle_range_ok(150.0, 50.0, atr=2.0, cfg=CONFIG)
    assert r.range_atr == pytest.approx(50.0)
    assert r.valid is False


def test_rectangle_range_unusable_atr_is_invalid():
    r = geometry.rectangle_range_ok(110.0, 100.0, atr=0.0, cfg=CONFIG)
    assert r.valid is False
    assert np.isnan(r.range_atr)


# ── Boundary stability (§30.1 #7) ────────────────────────────────────────────


def _stability_touch(idx: int, price: float, d0: pd.Timestamp) -> geometry.Touch:
    dt = d0 + pd.Timedelta(days=idx)
    return geometry.Touch(pivot_index=idx, pivot_date=dt, confirmed_index=idx + 3, confirmed_date=dt + pd.Timedelta(days=3),
                           kind="HIGH", price=price, volume=100.0, bar_range=1.0, rejection=0.3)


def test_boundary_stability_stable_case():
    d0 = pd.Timestamp("2024-01-02")
    touches = (_stability_touch(2, 110.0, d0), _stability_touch(10, 109.9, d0), _stability_touch(20, 110.1, d0))
    r = geometry.boundary_stability(touches, window_start=0, window_end=25, atr=2.0, cfg=CONFIG)
    assert r.stable is True
    assert r.insufficient_data is False
    assert r.shift_atr <= CONFIG["boundary_stability_max_shift_atr"]
    assert r.residual_std_atr <= CONFIG["boundary_max_residual_atr"]


def test_boundary_stability_unstable_case_large_shift():
    d0 = pd.Timestamp("2024-01-02")
    touches = (_stability_touch(2, 110.0, d0), _stability_touch(10, 110.0, d0), _stability_touch(24, 115.0, d0))
    r = geometry.boundary_stability(touches, window_start=0, window_end=25, atr=2.0, cfg=CONFIG)
    assert r.stable is False
    assert r.insufficient_data is False
    assert r.shift_atr > CONFIG["boundary_stability_max_shift_atr"]


def test_boundary_stability_insufficient_data_when_no_touch_in_refit_window():
    d0 = pd.Timestamp("2024-01-02")
    touches = (_stability_touch(24, 110.0, d0),)  # only touch is AFTER the 70% refit cutoff
    r = geometry.boundary_stability(touches, window_start=0, window_end=25, atr=2.0, cfg=CONFIG)
    assert r.insufficient_data is True
    assert r.stable is False


def test_boundary_stability_no_touches_or_unusable_atr_is_insufficient():
    r1 = geometry.boundary_stability((), window_start=0, window_end=10, atr=2.0, cfg=CONFIG)
    assert r1.insufficient_data is True
    d0 = pd.Timestamp("2024-01-02")
    r2 = geometry.boundary_stability((_stability_touch(2, 110.0, d0),), window_start=0, window_end=10, atr=0.0, cfg=CONFIG)
    assert r2.insufficient_data is True
