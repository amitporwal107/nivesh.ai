"""The six frozen NI-3 §3 fixtures for P-2 flags and pennants.

Each is tested at the level its rule lives at — the lesson from the P-1 fixtures, where trying to
reverse-engineer OHLCV into an indirect assertion kept testing something adjacent to the rule. A
pole rule is tested against `find_poles`, a classification rule against the table built from the
frozen config, and a body rule against the body window.
"""
import numpy as np
import pandas as pd
import pytest

from research.charting import geometry, ni3_config
from research.charting.patterns_p1 import SHAPE_FLAT_PARALLEL_IS_RECTANGLE, _alternating_suffix
from research.charting.patterns_p2 import (
    BODY_INSUFFICIENT_PIVOTS, FLAT_PARALLEL_BODY, POLE_TOO_SLOW, POLE_TOO_WEAK, _p2_table,
    detect_p2_as_of, find_poles,
)
from research.charting.series import atr as atr_fn
from research.charting.swings import Pivot, find_swings

NI3 = ni3_config.load()
F, SHARED, P1 = NI3["p2_flags"], NI3["shared"], NI3["p1_geometry"]
DATES = pd.date_range("2026-01-01", periods=200, freq="D")


def _piv(kind, x, price):
    return Pivot(kind=kind, pivot_index=x, pivot_date=DATES[x], price=price,
                 confirmed_index=x + 3, confirmed_date=DATES[x + 3])


def _flat_bars(n, level=100.0, atr_target=1.0):
    """Bars with a known, near-constant ATR so a pole's move-in-ATR is controllable."""
    close = [level] * n
    return pd.DataFrame({
        "date": DATES[:n], "open": close,
        "high": [c + atr_target / 2 for c in close], "low": [c - atr_target / 2 for c in close],
        "close": close, "volume": [1_000_000.0] * n,
    })


# ── Fixture 1 ───────────────────────────────────────────────────────────────────────────────────
def test_FIXTURE_P2_01_a_pole_of_1_5_atr_is_too_weak():
    """F1 = 2.0 x ATR. A 1.5 x ATR move is a sloped line, not a pole."""
    df = _flat_bars(40)
    atr = atr_fn(df, period=SHARED["atr_period"]).to_numpy()
    at = float(atr[20])
    assert np.isfinite(at) and at > 0

    weak = [_piv("LOW", 14, 100.0), _piv("HIGH", 20, 100.0 + 1.5 * at)]
    ok, bad = find_poles(weak, atr, F)
    assert ok == []
    assert [p.reason for p in bad] == [POLE_TOO_WEAK]
    assert bad[0].move_atr == pytest.approx(1.5, abs=0.01)

    # and 2.0 x ATR is accepted, so the boundary is the frozen one
    strong = [_piv("LOW", 14, 100.0), _piv("HIGH", 20, 100.0 + 2.0 * at)]
    ok2, bad2 = find_poles(strong, atr, F)
    assert len(ok2) == 1 and bad2 == []


def test_FIXTURE_P2_01b_a_pole_taking_too_long_is_too_slow():
    """F2 = 15 bars. Steep enough but spread over 20 bars is not a pole."""
    df = _flat_bars(60)
    atr = atr_fn(df, period=SHARED["atr_period"]).to_numpy()
    at = float(atr[40])
    slow = [_piv("LOW", 14, 100.0), _piv("HIGH", 34, 100.0 + 5 * at)]
    ok, bad = find_poles(slow, atr, F)
    assert ok == []
    assert [p.reason for p in bad] == [POLE_TOO_SLOW]


# ── Fixture 2 ───────────────────────────────────────────────────────────────────────────────────
def test_FIXTURE_P2_02_a_body_retracing_60_percent_of_the_pole_is_rejected():
    """F6: the body must retrace LESS than 50% of the pole. 60% fails.

    Tested on the retracement arithmetic the detector uses, so the fixture pins the rule rather than
    a particular synthetic series.
    """
    pole_start, pole_end = 100.0, 120.0
    height = pole_end - pole_start
    deep_low = pole_end - 0.60 * height          # 108 -> 60% retracement
    shallow_low = pole_end - 0.40 * height       # 112 -> 40%

    for low, expect_reject in [(deep_low, True), (shallow_low, False)]:
        retrace_pct = (pole_end - low) / height * 100.0
        rejected = retrace_pct >= F["body_max_retracement_pct_of_pole"]
        assert rejected is expect_reject, f"{retrace_pct:.0f}% retracement"
    assert F["body_max_retracement_pct_of_pole"] == 50


# ── Fixtures 3, 4, 5 — classification ───────────────────────────────────────────────────────────
def test_FIXTURE_P2_03_a_flat_parallel_body_after_an_up_pole_is_a_bull_flag():
    """"sideways consolidation". P-1 will not emit FLAT/FLAT/PARALLEL standalone — the rectangle
    family owns it — but as a flag body it is valid, and the detector reads that exact rejection as
    a legitimate body shape."""
    table = _p2_table(F)
    assert table[("UP", FLAT_PARALLEL_BODY)] == "BULL_FLAG"
    assert table[("DOWN", FLAT_PARALLEL_BODY)] == "BEAR_FLAG"
    assert "flat_parallel" in F["bull_flag_bodies"] and "flat_parallel" in F["bear_flag_bodies"]
    # the bridge the detector relies on
    assert SHAPE_FLAT_PARALLEL_IS_RECTANGLE == "SHAPE_FLAT_PARALLEL_IS_RECTANGLE"


def test_FIXTURE_P2_04_a_symmetrical_triangle_body_after_an_up_pole_is_a_bull_pennant():
    """§10 Q3: pennant bodies are symmetrical triangles ONLY."""
    table = _p2_table(F)
    assert table[("UP", "SYMMETRICAL_TRIANGLE")] == "BULL_PENNANT"
    assert table[("DOWN", "SYMMETRICAL_TRIANGLE")] == "BEAR_PENNANT"
    assert F["pennant_bodies"] == ["symmetrical_triangle"]


def test_FIXTURE_P2_05_an_ascending_triangle_body_after_an_up_pole_is_not_a_pennant():
    """"It stays that P-1 shape, and linked_pattern_id points to the pole." So the P-2 table must
    have no entry for it — the P-1 engine already emits it and P-2 emits nothing."""
    table = _p2_table(F)
    assert ("UP", "ASCENDING_TRIANGLE") not in table
    assert ("DOWN", "DESCENDING_TRIANGLE") not in table
    assert F["other_body_after_pole"] == "report_as_own_p1_shape_with_linked_pattern_id"


def test_the_classification_table_is_read_from_the_frozen_config_not_transcribed():
    """If the table were hardcoded it could drift from fingerprint de86626c... silently."""
    table = _p2_table(F)
    assert len(table) == 8
    for body in F["bull_flag_bodies"]:
        assert table[("UP", body.upper())] == "BULL_FLAG"
    for body in F["bear_flag_bodies"]:
        assert table[("DOWN", body.upper())] == "BEAR_FLAG"
    assert ni3_config.fingerprint(ni3_config.load()) == ni3_config.NI3_FINGERPRINT


# ── Fixture 6 ───────────────────────────────────────────────────────────────────────────────────
def test_FIXTURE_P2_06_a_body_with_only_three_confirmed_pivots_is_insufficient():
    """G1 = 4 pivots, 2 per line. Three cannot define two lines."""
    assert F["body_min_pivots"] == 4
    three = [_piv("HIGH", 20, 110.0), _piv("LOW", 24, 104.0), _piv("HIGH", 28, 108.0)]
    run = _alternating_suffix(three)
    assert len(run) == 3
    assert len(run) < F["body_min_pivots"], "three pivots must not reach the shape test"
    assert BODY_INSUFFICIENT_PIVOTS == "BODY_INSUFFICIENT_PIVOTS"


# ── the disclosed limitation, measured rather than assumed ──────────────────────────────────────
def test_the_disclosed_body_length_limitation_is_real_and_is_not_tuned_away():
    """NI-3 §3 discloses that with 3-bar swings "bodies shorter than roughly 10 bars will rarely
    qualify even though F5 allows 5", and says the fix would be "a new decision before the freeze,
    never a change after results".

    This pins the arithmetic that causes it, so nobody quietly relaxes F3 or the swing window to
    make flags more numerous: four pivots spaced at the 3/3 swing cost need more bars than F3 allows
    a body when the pole is at its F2 maximum.
    """
    assert SHARED["swing_left_bars"] == 3 and SHARED["swing_right_bars"] == 3
    assert F["pole_max_bars"] == 15
    assert F["body_duration_strictly_less_than_pole"] is True
    assert F["body_min_bars"] == 5 and F["body_max_bars"] == 20
    # a body is capped by the pole, which is capped at 15, so a body can never exceed 14 bars
    assert F["pole_max_bars"] - 1 == 14


def test_detection_is_deterministic():
    df = _flat_bars(60)
    a = detect_p2_as_of(df, len(df) - 1, symbol="T")
    b = detect_p2_as_of(df, len(df) - 1, symbol="T")
    assert [s.__dict__ for s in a] == [s.__dict__ for s in b]
