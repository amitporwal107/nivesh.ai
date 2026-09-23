"""NI-3 §7 — cup & handle. The strictest family: seventeen frozen parameters, all gating."""
import numpy as np
import pandas as pd
import pytest

from research.charting import ni3_config, regime
from research.charting.patterns_ni3 import detect_ni3_as_of


def _bars(px):
    return pd.DataFrame({
        "date": pd.date_range("2025-01-01", periods=len(px), freq="D"),
        "open": px, "high": [p * 1.004 for p in px], "low": [p * 0.996 for p in px],
        "close": px, "volume": [1_000_000.0] * len(px),
    })


PRE = list(np.linspace(55, 100, 60))                                   # strong prior uptrend
CUP = list(np.linspace(100, 78, 16)) + list(np.linspace(78.5, 100, 16))  # 31 bars, ~22% deep
GOOD = PRE + CUP + [99, 97, 95, 94, 96, 103]                            # 6-bar handle, breaks out


def _cups(px, t=None):
    b = _bars(px)
    return [s for s in detect_ni3_as_of(b, len(px) - 1 if t is None else t, symbol="T")
            if s.pattern_type == "CUP_AND_HANDLE"]


def test_a_cup_and_handle_is_detected_and_breaks_out():
    snaps = _cups(GOOD)
    assert len(snaps) == 1
    s = snaps[0]
    assert s.direction == "BULLISH"
    assert s.status == "PRICE_CONFIRMED"
    assert s.levels["breakout_level"] == pytest.approx(s.levels["rim"] * 1.005)
    assert s.levels["layer1_stop"] == s.levels["handle_low"]        # OWNER §37.3


def test_all_frozen_gates_are_recorded_with_their_thresholds():
    s = _cups(GOOD)[0]
    got = {r["rule_id"]: r for r in s.rules}
    c = ni3_config.load()["cup_and_handle"]
    assert got["CAH_RIM_TOLERANCE_PCT"]["threshold"] == c["cup_rim_tolerance_pct"]
    assert got["CAH_CUP_DEPTH_PCT"]["threshold"] == (c["cup_min_depth_pct"], c["cup_max_depth_pct"])
    assert got["CAH_CUP_BARS"]["threshold"] == (c["cup_min_bars"], c["cup_max_bars"])
    assert got["CAH_CUP_LOW_POSITION"]["threshold"] == (c["cup_low_position_min_frac"], c["cup_low_position_max_frac"])
    assert got["CAH_MAX_SINGLE_BAR_RANGE_ATR"]["threshold"] == c["cup_max_single_bar_range_atr"]
    assert got["CAH_HANDLE_BARS"]["threshold"] == (c["handle_min_bars"], c["handle_max_bars"])


# ── each gate rejects ───────────────────────────────────────────────────────────────────────────
def test_C15_a_handle_longer_than_a_quarter_of_the_cup_is_rejected():
    """The gate that made the first real-data run return nothing: a 31-bar cup allows at most a
    7-bar handle."""
    long_handle = PRE + CUP + [99, 97, 95, 94, 94, 95, 95, 96, 97, 98, 99, 103]   # 12 bars
    assert _cups(long_handle) == []


def test_C5_a_cup_shorter_than_twenty_five_bars_is_rejected():
    short_cup = list(np.linspace(100, 80, 9)) + list(np.linspace(80.5, 100, 9))   # ~17 bars
    assert _cups(PRE + short_cup + [99, 97, 95, 96, 103]) == []


def test_C3_a_cup_shallower_than_fifteen_percent_is_rejected():
    shallow = list(np.linspace(100, 94, 16)) + list(np.linspace(94.2, 100, 16))   # ~6% deep
    assert _cups(PRE + shallow + [99, 97, 95, 94, 96, 103]) == []


def test_C8_a_cup_whose_low_is_not_in_the_middle_third_is_rejected():
    """A late, V-shaped low: the descent takes most of the cup."""
    skewed = list(np.linspace(100, 78, 26)) + list(np.linspace(79, 100, 6))
    assert _cups(PRE + skewed + [99, 97, 95, 94, 96, 103]) == []


def test_the_prior_trend_gate_rejects_a_flat_lead_in():
    """`prior_trend_at_cup_start` is BULL or STRONG_BULL and is in the frozen config, so it gates."""
    flat = [100.0] * 60
    assert _cups(flat + CUP + [99, 97, 95, 94, 96, 103]) == []


def test_the_prior_trend_gate_reads_the_stock_trend_by_DATE_not_by_index():
    """Regression for a real defect. `regime.trend_classification` is keyed by date; passing a bar
    index returns UNAVAILABLE silently, and because this gate rejects on an uncomputable value it
    produced zero detections across all 50 symbols — indistinguishable from the family being rare."""
    b = _bars(GOOD)
    by_date = regime.trend_classification(b, b["date"].iloc[60])["class"]
    by_index = regime.trend_classification(b, 60)["class"]
    assert getattr(by_date, "value", None) in ("BULL", "STRONG_BULL")
    assert getattr(by_index, "value", None) is None
    assert _cups(GOOD), "the detector must use the date form"


# ── point-in-time ───────────────────────────────────────────────────────────────────────────────
def test_NLA_future_bars_cannot_change_the_result_at_t():
    t = len(PRE) + len(CUP) + 4
    clean = _bars(GOOD)
    poisoned = clean.copy()
    for i in range(t + 1, len(poisoned)):
        poisoned.loc[i, ["open", "high", "low", "close"]] = [9_999.0] * 4
        poisoned.loc[i, "volume"] = 9_999_999.0
    a = [s for s in detect_ni3_as_of(clean, t, symbol="T") if s.pattern_type == "CUP_AND_HANDLE"]
    b = [s for s in detect_ni3_as_of(poisoned, t, symbol="T") if s.pattern_type == "CUP_AND_HANDLE"]
    assert [s.__dict__ for s in a] == [s.__dict__ for s in b]


def test_handle_relative_volume_is_recorded_but_never_gates():
    """C16 is descriptive (NI-3 §1.6): a handle above 1.0x relative volume must still be emitted."""
    s = _cups(GOOD)[0]
    row = [r for r in s.rules if r["rule_id"] == "CAH_HANDLE_REL_VOLUME"][0]
    assert row["result"] == "PASS"
    assert row["threshold"] == ni3_config.load()["cup_and_handle"]["handle_max_rel_volume"]
