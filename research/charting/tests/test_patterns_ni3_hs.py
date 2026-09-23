"""NI-3 §6 / §6b — head & shoulders and inverse head & shoulders.

These are the two families unblocked by `trendline_value_at` alone: the neckline may slope, and the
breakdown test uses its projected value AT THE BREAKDOWN BAR, not its value at formation.
"""
import pandas as pd
import pytest

from research.charting import geometry, ni3_config
from research.charting.patterns_ni3 import detect_ni3_as_of


def _bars(px):
    return pd.DataFrame({
        "date": pd.date_range("2026-01-01", periods=len(px), freq="D"),
        "open": px, "high": [p * 1.004 for p in px], "low": [p * 0.996 for p in px],
        "close": px, "volume": [1_000_000.0] * len(px),
    })


def _only(snaps, ptype):
    return [s for s in snaps if s.pattern_type == ptype]


# left shoulder ~100 (bar 7) · trough 90 (bar 13) · head 112 (bar 19) · trough 91 (bar 25) ·
# right shoulder ~101 (bar 31), then a break below the rising neckline.
HS_BASE = (
    [92] * 4 + [95, 97, 99, 100, 99, 97, 95] + [93, 91, 90, 91, 93, 96]
    + [100, 105, 110, 112, 110, 106, 102] + [97, 93, 91, 92, 95, 98]
    + [100, 101, 100, 99, 97]
)
HS_BREAK = HS_BASE + [95, 93, 91, 89, 87]
HS_PENDING = HS_BASE + [96, 97, 96, 95, 96]


def test_a_head_and_shoulders_is_detected():
    snaps = _only(detect_ni3_as_of(_bars(HS_BREAK), len(HS_BREAK) - 1, symbol="T"), "HEAD_AND_SHOULDERS")
    assert snaps, "expected a head & shoulders"
    s = snaps[0]
    assert s.direction == "BEARISH"
    assert s.levels["head"] > max(s.levels["left_shoulder"], s.levels["right_shoulder"])


def test_the_neckline_is_a_fitted_line_not_a_horizontal_level():
    """The whole reason these two families needed `trendline_value_at`."""
    s = _only(detect_ni3_as_of(_bars(HS_BREAK), len(HS_BREAK) - 1, symbol="T"), "HEAD_AND_SHOULDERS")[0]
    assert "neckline_slope" in s.levels and "neckline_intercept" in s.levels
    line = geometry.Line(slope=s.levels["neckline_slope"], intercept=s.levels["neckline_intercept"])
    # the recorded live value at t must equal the projection, not a stored constant
    assert s.levels["neckline_value_at_t"] == pytest.approx(
        geometry.trendline_value_at(line, len(HS_BREAK) - 1), abs=1e-6)


def test_the_breakdown_uses_the_necklines_value_at_the_breakdown_bar():
    s = _only(detect_ni3_as_of(_bars(HS_BREAK), len(HS_BREAK) - 1, symbol="T"), "HEAD_AND_SHOULDERS")[0]
    assert s.status == "PRICE_CONFIRMED"
    ev = [e for e in s.events if e["event_type"] == "PRICE_CONFIRMED"][0]
    line = geometry.Line(slope=s.levels["neckline_slope"], intercept=s.levels["neckline_intercept"])
    bar = list(pd.date_range("2026-01-01", periods=len(HS_BREAK), freq="D").date).index(
        pd.Timestamp(ev["date"]).date())
    assert ev["observed_values"]["neckline_value"] == pytest.approx(
        geometry.trendline_value_at(line, bar), abs=1e-6)
    # and the trigger is that live value shifted by S5, not the formation-time value
    thresh = ni3_config.load()["head_and_shoulders"]["breakdown_threshold_pct"]
    assert ev["observed_values"]["trigger"] == pytest.approx(
        ev["observed_values"]["neckline_value"] * (1 - thresh / 100.0), abs=1e-6)


def test_before_the_breakdown_it_stays_geometry_valid():
    snaps = _only(detect_ni3_as_of(_bars(HS_PENDING), len(HS_PENDING) - 1, symbol="T"), "HEAD_AND_SHOULDERS")
    assert snaps and snaps[0].status == "GEOMETRY_VALID"


def test_CERT_both_stop_variants_are_always_reported():
    """#110: "Both stop variants are computed and reported for every H&S event. Neither is picked
    for looking better." """
    s = _only(detect_ni3_as_of(_bars(HS_BREAK), len(HS_BREAK) - 1, symbol="T"), "HEAD_AND_SHOULDERS")[0]
    assert s.levels["stop_primary"] is not None
    assert s.levels["stop_secondary_research"] is not None
    assert s.levels["stop_primary"] != s.levels["stop_secondary_research"]


def test_every_frozen_gate_is_recorded_with_its_threshold():
    s = _only(detect_ni3_as_of(_bars(HS_BREAK), len(HS_BREAK) - 1, symbol="T"), "HEAD_AND_SHOULDERS")[0]
    got = {r["rule_id"]: r for r in s.rules}
    cfg = ni3_config.load()["head_and_shoulders"]
    assert got["HS_SHOULDER_TOLERANCE_PCT"]["threshold"] == cfg["shoulder_tolerance_pct"]
    assert got["HS_HEAD_PROMINENCE_PCT"]["threshold"] == cfg["head_min_prominence_pct"]
    assert got["HS_PEAK_SEPARATION_BARS"]["threshold"] == cfg["peak_min_separation_bars"]
    assert got["HS_NECKLINE_SEPARATION_BARS"]["threshold"] == cfg["neckline_trough_min_separation_bars"]


# ── the gates actually reject ───────────────────────────────────────────────────────────────────
def test_CERT_head_prominence_is_measured_against_the_nearer_shoulder():
    """H2: prominence is measured against the NEARER shoulder, so a head clearing only the lower
    one must fail."""
    px = ([92] * 4 + [95, 97, 99, 100, 99, 97, 95] + [93, 91, 90, 91, 93, 96]
          + [99, 100, 100.5, 101, 100.5, 99, 97] + [95, 93, 91, 92, 95, 98]
          + [100, 101, 100, 99, 97] + [95, 93, 91, 89, 87])
    assert _only(detect_ni3_as_of(_bars(px), len(px) - 1, symbol="T"), "HEAD_AND_SHOULDERS") == []


def test_shoulders_outside_the_tolerance_are_rejected():
    """H1: 5%. Right shoulder ~20% below the left."""
    px = ([92] * 4 + [95, 97, 99, 100, 99, 97, 95] + [93, 91, 90, 91, 93, 96]
          + [100, 105, 110, 112, 110, 106, 102] + [97, 93, 91, 92, 93, 94]
          + [95, 96, 95, 94, 93] + [90, 88, 86, 84, 82])
    snaps = _only(detect_ni3_as_of(_bars(px), len(px) - 1, symbol="T"), "HEAD_AND_SHOULDERS")
    for s in snaps:
        from research.charting.patterns_ni3 import _pct_diff
        assert _pct_diff(s.levels["left_shoulder"], s.levels["right_shoulder"]) <= 5.0


# ── the bullish mirror ──────────────────────────────────────────────────────────────────────────
def test_an_inverse_head_and_shoulders_is_the_mirror():
    px = [x * -1 + 200 for x in HS_BREAK]     # reflect the whole series
    snaps = _only(detect_ni3_as_of(_bars(px), len(px) - 1, symbol="T"), "INVERSE_HEAD_AND_SHOULDERS")
    assert snaps, "expected an inverse head & shoulders"
    s = snaps[0]
    assert s.direction == "BULLISH"
    assert s.levels["head"] < min(s.levels["left_shoulder"], s.levels["right_shoulder"])
    assert s.status == "PRICE_CONFIRMED"


# ── no look-ahead ───────────────────────────────────────────────────────────────────────────────
def test_NLA_future_bars_cannot_change_the_result_at_t():
    t = len(HS_BASE) - 1
    clean = _bars(HS_BREAK)
    poisoned = clean.copy()
    for i in range(t + 1, len(poisoned)):
        poisoned.loc[i, ["open", "high", "low", "close"]] = [9_999.0] * 4
        poisoned.loc[i, "volume"] = 9_999_999.0
    assert [s.__dict__ for s in detect_ni3_as_of(clean, t, symbol="T")] == \
           [s.__dict__ for s in detect_ni3_as_of(poisoned, t, symbol="T")]


def test_the_walk_starts_only_once_all_five_pivots_are_confirmed():
    s = _only(detect_ni3_as_of(_bars(HS_BREAK), len(HS_BREAK) - 1, symbol="T"), "HEAD_AND_SHOULDERS")[0]
    assert len(s.pivots) == 5
    ev = [e for e in s.events if e["event_type"] == "PRICE_CONFIRMED"]
    if ev:
        assert ev[0]["date"] >= max(p["confirmed_date"] for p in s.pivots)
