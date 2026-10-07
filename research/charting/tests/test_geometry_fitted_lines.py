"""Wave A — fitted lines, projected values and the pivot-based width ratio (NI-3 §2).

Two of these are the hard certification gates the owner asked for on 2026-09-23:

  * `test_F2_*` — P-1 flatness must use the NI-3 G4 PERCENTAGE rule. A detector that used
    `boundary_drift` (the ATR test belonging to the three frozen families) would not reproduce
    fingerprint de86626c…, so the two tests must be demonstrably different, not merely differently
    named.
  * `test_C2_*` — the width ratio must be measured at the first and last PIVOT. Measuring at the
    first and last bar of the formation gives a different number and fails the frozen fixtures.

Both are written so they fail loudly if someone "simplifies" the two conventions into one.
"""
import math

import pytest

from research.charting import geometry as g
from research.charting import ni3_config
from research.charting.config import CONFIG


# ── fit_line ────────────────────────────────────────────────────────────────────────────────────
def test_fit_line_slope_is_identical_to_ols_slope():
    """Anti-drift: the two must never disagree, or a boundary's direction would depend on which
    function the caller happened to use."""
    for xs, ys in [([0, 1, 2, 3], [10, 12, 14, 16]), ([5, 9, 14], [100, 97, 91]), ([0, 7], [50, 50])]:
        assert g.fit_line(xs, ys).slope == pytest.approx(g.ols_slope(xs, ys))


def test_fit_line_recovers_a_known_line_exactly():
    line = g.fit_line([0, 10, 20, 30], [100, 110, 120, 130])
    assert line.slope == pytest.approx(1.0)
    assert line.intercept == pytest.approx(100.0)


def test_fit_line_on_a_horizontal_series_has_zero_slope_and_the_level_as_intercept():
    line = g.fit_line([3, 8, 15], [250.0, 250.0, 250.0])
    assert line.slope == pytest.approx(0.0)
    assert line.intercept == pytest.approx(250.0)


def test_fit_line_degenerates_honestly_rather_than_raising():
    """One pivot cannot define a slope; a flat line through it is the honest default (as ols_slope)."""
    line = g.fit_line([7], [42.0])
    assert line.slope == 0.0
    assert line.intercept == pytest.approx(42.0)
    assert math.isnan(g.fit_line([], []).intercept)


# ── trendline_value_at ──────────────────────────────────────────────────────────────────────────
def test_trendline_value_at_projects_forward_and_backward():
    line = g.Line(slope=2.0, intercept=100.0)
    assert g.trendline_value_at(line, 0) == pytest.approx(100.0)
    assert g.trendline_value_at(line, 25) == pytest.approx(150.0)
    assert g.trendline_value_at(line, -10) == pytest.approx(80.0)


def test_trendline_value_at_reproduces_the_fitted_points():
    xs, ys = [4, 9, 16], [120.0, 126.0, 134.4]      # exactly collinear: slope 1.2, intercept 115.2
    line = g.fit_line(xs, ys)
    for x, y in zip(xs, ys):
        assert g.trendline_value_at(line, x) == pytest.approx(y, abs=1e-6)


# ── line_direction: the G4 percentage rule ──────────────────────────────────────────────────────
def test_line_direction_flat_rising_falling_by_the_g4_percentage():
    flat = g.fit_line([0, 20], [100.0, 100.8])        # +0.8% over the formation -> <= 1.5%
    rising = g.fit_line([0, 20], [100.0, 105.0])      # +5%
    falling = g.fit_line([0, 20], [100.0, 95.0])      # -5%
    assert g.line_direction(flat, 0, 20) == g.FLAT
    assert g.line_direction(rising, 0, 20) == g.RISING
    assert g.line_direction(falling, 0, 20) == g.FALLING


def test_line_direction_has_no_gap_between_flat_and_sloped():
    """NI-3 §2: "One threshold, so there is no gap and no second number." Every line must classify."""
    for pct in (0.0, 1.49, 1.5, 1.51, 3.0, -1.5, -1.51, -9.0):
        line = g.fit_line([0, 20], [100.0, 100.0 * (1 + pct / 100)])
        assert g.line_direction(line, 0, 20) in (g.FLAT, g.RISING, g.FALLING)


def test_F2_the_percentage_flatness_rule_is_not_the_atr_drift_rule():
    """HARD GATE (owner, 2026-09-23). A line can be FLAT under the P0 ATR test and RISING under the
    P-1 percentage test. A detector that used `boundary_drift` for a P-1 family would classify the
    shape differently and could not reproduce fingerprint de86626c…, so certification must fail it.

    Construction: ~100 price rising 3% over 20 bars, with a large ATR of 20. The ATR drift is
    |0.15| * 20 / 20 = 0.15, well under the 0.50 flat threshold; the percentage change is 3%, over
    the 1.5% threshold.
    """
    line = g.fit_line([0, 20], [100.0, 103.0])
    atr_verdict = g.boundary_drift(line.slope, length_bars=20, atr=20.0, cfg=CONFIG).direction
    pct_verdict = g.line_direction(line, 0, 20)
    assert atr_verdict == "FLAT", "the P0 ATR test should call this flat"
    assert pct_verdict == g.RISING, "the NI-3 G4 percentage test should call this rising"
    assert atr_verdict != pct_verdict, "the two conventions must stay distinguishable"


# ── width_ratio: measured at pivots ─────────────────────────────────────────────────────────────
def test_width_ratio_on_converging_lines():
    upper = g.fit_line([0, 20], [110.0, 104.0])
    lower = g.fit_line([0, 20], [90.0, 96.0])
    assert g.width_ratio(upper, lower, 0, 20) == pytest.approx(8.0 / 20.0)


def test_width_ratio_on_parallel_lines_is_one():
    upper = g.Line(slope=0.5, intercept=110.0)
    lower = g.Line(slope=0.5, intercept=90.0)
    assert g.width_ratio(upper, lower, 0, 30) == pytest.approx(1.0)


def test_width_ratio_rejects_a_non_positive_starting_width():
    upper = g.Line(slope=0.0, intercept=90.0)
    lower = g.Line(slope=0.0, intercept=110.0)      # already crossed
    assert math.isnan(g.width_ratio(upper, lower, 0, 20))
    assert g.classify_pair(g.width_ratio(upper, lower, 0, 20)) == g.SHAPE_UNCLASSIFIED


def test_C2_width_is_measured_at_the_pivots_not_at_the_formation_bars():
    """HARD GATE (owner, 2026-09-23). NI-3 §2 measures width at the first and last PIVOT. The older
    NI-2 wording (still in `convergence_ratio`'s docstring) says first and last BAR.

    This construction is chosen so the two conventions do not merely differ numerically -- they land
    in DIFFERENT BANDS, so a bar-based detector would emit a different shape: it would call this a
    converging triangle or wedge where NI-3 calls it a parallel channel.

    Upper slope -0.45 from 110, lower slope +0.45 from 90; pivots at bars 5 and 7 in a 0..20 window.
    """
    upper = g.Line(slope=-0.45, intercept=110.0)
    lower = g.Line(slope=+0.45, intercept=90.0)

    #   at pivot 5 -> 107.75 - 92.25 = 15.50 ; at pivot 7 -> 106.85 - 93.15 = 13.70
    #   at bar   0 -> 110.00 - 90.00 = 20.00 ; at bar  20 -> 101.00 - 99.00 =  2.00
    at_pivots = g.width_ratio(upper, lower, 5, 7)
    at_bars = g.width_ratio(upper, lower, 0, 20)

    assert at_pivots == pytest.approx(13.70 / 15.50)
    assert at_bars == pytest.approx(2.0 / 20.0)

    assert g.classify_pair(at_pivots) == g.PARALLEL, "NI-3 reads this structure as a channel"
    assert g.classify_pair(at_bars) == g.CONVERGING, "a bar-based detector would read a triangle/wedge"


# ── classify_pair: five bands, two of them gaps ─────────────────────────────────────────────────
@pytest.mark.parametrize("w,expected", [
    (0.10, g.CONVERGING), (0.6999, g.CONVERGING), (0.70, g.CONVERGING),
    (0.7001, g.SHAPE_UNCLASSIFIED), (0.80, g.SHAPE_UNCLASSIFIED), (0.8499, g.SHAPE_UNCLASSIFIED),
    (0.85, g.PARALLEL), (1.00, g.PARALLEL), (1.15, g.PARALLEL),
    (1.1501, g.SHAPE_UNCLASSIFIED), (1.30, g.SHAPE_UNCLASSIFIED), (1.4299, g.SHAPE_UNCLASSIFIED),
    (1.43, g.EXPANDING), (2.50, g.EXPANDING),
])
def test_classify_pair_bands(w, expected):
    assert g.classify_pair(w) == expected


def test_classify_pair_gaps_are_deliberate_not_rounded():
    """A structure in a gap is rejected, never rounded into the nearer band."""
    assert g.classify_pair(0.84) == g.SHAPE_UNCLASSIFIED      # nearer PARALLEL, still rejected
    assert g.classify_pair(0.71) == g.SHAPE_UNCLASSIFIED      # nearer CONVERGING, still rejected


def test_classify_pair_handles_nan_and_none():
    assert g.classify_pair(float("nan")) == g.SHAPE_UNCLASSIFIED
    assert g.classify_pair(None) == g.SHAPE_UNCLASSIFIED


def test_expanding_is_classified_even_though_it_is_out_of_scope_to_emit():
    """Classification and emission are different questions: `expanding_in_scope` is false, but the
    classifier must still name what it saw so the detector can reject it by reason code."""
    assert ni3_config.p1()["expanding_in_scope"] is False
    assert g.classify_pair(1.60) == g.EXPANDING


# ── the shape table's inputs compose ────────────────────────────────────────────────────────────
def test_an_ascending_triangle_falls_out_of_the_primitives():
    """NI-3 §2 shape table: FLAT upper + RISING lower + converging = ascending triangle."""
    upper = g.fit_line([0, 10, 20], [100.0, 100.2, 100.1])
    lower = g.fit_line([0, 10, 20], [90.0, 93.0, 96.0])
    assert g.line_direction(upper, 0, 20) == g.FLAT
    assert g.line_direction(lower, 0, 20) == g.RISING
    assert g.classify_pair(g.width_ratio(upper, lower, 0, 20)) == g.CONVERGING


def test_an_ascending_channel_falls_out_of_the_primitives():
    """RISING + RISING + parallel = ascending channel."""
    upper = g.Line(slope=0.5, intercept=110.0)
    lower = g.Line(slope=0.5, intercept=90.0)
    assert g.line_direction(upper, 0, 40) == g.RISING
    assert g.line_direction(lower, 0, 40) == g.RISING
    assert g.classify_pair(g.width_ratio(upper, lower, 0, 40)) == g.PARALLEL


# ── the NI-3 configuration itself ───────────────────────────────────────────────────────────────
def test_ni3_config_reproduces_the_frozen_fingerprint():
    """NI-3: "the detector code must reproduce this fingerprint from its own configuration, or it
    is not this table"."""
    assert ni3_config.fingerprint(ni3_config.load()) == ni3_config.NI3_FINGERPRINT


def test_a_tampered_ni3_config_is_rejected():
    cfg = dict(ni3_config.load())
    cfg["p1_geometry"] = dict(cfg["p1_geometry"], convergence_max_ratio=0.75)
    assert ni3_config.fingerprint(cfg) != ni3_config.NI3_FINGERPRINT


def test_the_p1_bands_come_from_ni3_not_from_the_v1_config():
    """§37.7: the ATR rules stay with the P0 families; the percentage rules apply to the new ones.
    Reading a P-1 band out of CONFIG would silently couple the two."""
    p1 = ni3_config.p1()
    assert p1["flat_max_drift_pct"] == 1.5
    assert p1["parallel_ratio_min"] == 0.85 and p1["parallel_ratio_max"] == 1.15
    assert p1["expanding_min_ratio"] == 1.43
    assert "flat_max_drift_pct" not in CONFIG
