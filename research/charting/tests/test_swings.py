"""find_swings(): pivots on hand-built sequences, the equal-highs/lows tie rule, and
confirmation lag exactly right_bars. Point-in-time / poisoned-future behaviour
(swings_as_of) is covered separately in test_lookahead.py.
"""
from __future__ import annotations

import pandas as pd
import pytest

from research.charting.config import BARS_COLUMNS, CONFIG
from research.charting.swings import find_swings


def _bars(highs: list[float], lows: list[float]) -> pd.DataFrame:
    """Hand-built bars with exact, caller-chosen high/low columns. open=close=the
    midpoint of (high, low) on every bar — irrelevant to swing detection (which
    reads only high/low) but keeps the frame OHLC-sane."""
    assert len(highs) == len(lows)
    n = len(highs)
    dates = pd.bdate_range("2024-01-02", periods=n)
    mid = [(h + l) / 2 for h, l in zip(highs, lows)]
    df = pd.DataFrame(
        {"date": dates, "open": mid, "high": highs, "low": lows, "close": mid, "volume": [100_000.0] * n}
    )
    return df[list(BARS_COLUMNS)]


# ── Basic pivot detection ─────────────────────────────────────────────────────


def test_find_swings_detects_a_simple_high_and_low_pivot_on_the_same_bar():
    # index 3 is a spike both up (high) and down (low); everything else is flat.
    highs = [10, 10, 10, 20, 10, 10, 10]
    lows = [8, 8, 8, 2, 8, 8, 8]
    bars = _bars(highs, lows)

    pivots = find_swings(bars)  # CONFIG defaults: left=right=3

    assert len(pivots) == 2
    by_kind = {p.kind: p for p in pivots}
    assert set(by_kind) == {"HIGH", "LOW"}

    hi = by_kind["HIGH"]
    assert hi.pivot_index == 3
    assert hi.price == pytest.approx(20.0)
    assert hi.pivot_date == bars["date"].iloc[3]
    assert hi.confirmed_index == 6
    assert hi.confirmed_date == bars["date"].iloc[6]

    lo = by_kind["LOW"]
    assert lo.pivot_index == 3
    assert lo.price == pytest.approx(2.0)
    assert lo.confirmed_index == 6


def test_find_swings_ignores_candidates_too_close_to_either_edge():
    # A real spike at index 1, but left_bars=3 means index 1 (only 1 bar of left
    # context) can never be a candidate at all -- not even "unconfirmed", absent.
    highs = [10, 50, 10, 10, 10, 10, 10]
    lows = [8, 8, 8, 8, 8, 8, 8]
    bars = _bars(highs, lows)
    pivots = find_swings(bars)
    assert pivots == []


def test_find_swings_uses_config_defaults_when_not_overridden():
    assert (CONFIG["swing_left_bars"], CONFIG["swing_right_bars"]) == (3, 3)
    highs = [5, 10, 5]
    lows = [3, 3, 3]
    bars = _bars(highs, lows)

    # Too short for the CONFIG default (left=3, right=3): no candidate positions exist.
    assert find_swings(bars) == []

    # The same data, with an explicit smaller window, does find it.
    overridden = find_swings(bars, left_bars=1, right_bars=1)
    assert len(overridden) == 1
    assert overridden[0].kind == "HIGH"
    assert overridden[0].pivot_index == 1


def test_find_swings_rejects_non_positive_windows():
    bars = _bars([10, 20, 10], [5, 5, 5])
    with pytest.raises(ValueError):
        find_swings(bars, left_bars=0, right_bars=3)
    with pytest.raises(ValueError):
        find_swings(bars, left_bars=3, right_bars=0)


# ── Confirmation lag ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("left,right", [(3, 3), (2, 5), (1, 1), (4, 2)])
def test_confirmation_lag_is_exactly_right_bars(left, right):
    n = left + right + 5
    highs = [1.0] * n
    pivot_i = left + 1
    highs[pivot_i] = 100.0
    lows = [0.5] * n
    bars = _bars(highs, lows)

    pivots = find_swings(bars, left_bars=left, right_bars=right)
    matches = [p for p in pivots if p.kind == "HIGH" and p.pivot_index == pivot_i]
    assert len(matches) == 1
    pivot = matches[0]
    assert pivot.confirmed_index - pivot.pivot_index == right
    assert pivot.confirmed_date == bars["date"].iloc[pivot_i + right]


# ── Tie rule: equal highs / lows resolve to the LATEST tied bar ──────────────


def test_tie_rule_equal_highs_resolves_to_the_latest_bar():
    # index 3 and index 4 tie at the plateau maximum (20). Left neighbours may tie
    # (non-strict), right neighbours must be strictly lower -- so index 3's right
    # window contains index 4 (also 20), disqualifying index 3; index 4's right
    # window (12, 11, 10) is strictly lower, so index 4 wins.
    highs = [10, 11, 12, 20, 20, 12, 11, 10]
    lows = [9, 10, 11, 19, 19, 11, 10, 9]  # kept below highs, no low pivots here
    bars = _bars(highs, lows)

    pivots = find_swings(bars)  # left=right=3

    high_pivots = [p for p in pivots if p.kind == "HIGH"]
    assert len(high_pivots) == 1
    assert high_pivots[0].pivot_index == 4
    assert high_pivots[0].price == pytest.approx(20.0)


def test_tie_rule_equal_lows_resolves_to_the_latest_bar():
    lows = [10, 9, 8, 2, 2, 8, 9, 10]
    highs = [x + 1 for x in lows]  # kept above lows, no high pivots here
    bars = _bars(highs, lows)

    pivots = find_swings(bars)

    low_pivots = [p for p in pivots if p.kind == "LOW"]
    assert len(low_pivots) == 1
    assert low_pivots[0].pivot_index == 4
    assert low_pivots[0].price == pytest.approx(2.0)


def test_tie_rule_three_way_plateau_only_the_last_bar_wins():
    highs = [10, 11, 12, 20, 20, 20, 12, 11, 10]
    lows = [9, 10, 11, 19, 19, 19, 11, 10, 9]
    bars = _bars(highs, lows)

    pivots = find_swings(bars)

    high_pivots = [p for p in pivots if p.kind == "HIGH"]
    assert len(high_pivots) == 1
    assert high_pivots[0].pivot_index == 5  # the last of the three tied bars
