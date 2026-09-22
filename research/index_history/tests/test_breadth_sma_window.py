"""Synthetic-only: a name contributes to a rolling metric (SMA-above-price, new
52-week high/low) only once it has accumulated the FULL lookback window of its own
prior bars — the classic bug this guards against is using pandas' default
min_periods=1, which would flag a symbol's very first bar as "above its SMA" or as a
"new high/low" for free."""
import math

import pandas as pd

from research.index_history.breadth import compute_breadth


def _frame(dates, closes, highs=None, lows=None, symbol="X"):
    highs = highs if highs is not None else closes
    lows = lows if lows is not None else closes
    return pd.DataFrame({
        "symbol": [symbol] * len(dates),
        "date": dates,
        "open": closes,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": [0] * len(dates),
    })


def test_sma_full_window_only_rule():
    dates = [f"2024-08-{d:02d}" for d in range(1, 7)]
    closes = [10, 11, 9, 12, 13, 8]
    bars = _frame(dates, closes)

    out = compute_breadth(bars, sma_windows={"pct_above_sma3": 3}, high_low_window=0,
                           drop_sealed_window=False)
    out = out.set_index("date")

    # first (window - 1) = 2 dates: not enough history yet -> not eligible -> NaN
    assert math.isnan(out.loc["2024-08-01", "pct_above_sma3"])
    assert math.isnan(out.loc["2024-08-02", "pct_above_sma3"])

    # from the 3rd date on, the window is full -> a real percentage every time
    # sma@idx2 = mean(10,11,9) = 10.0, close=9 -> below -> 0%
    assert out.loc["2024-08-03", "pct_above_sma3"] == 0.0
    # sma@idx3 = mean(11,9,12) = 10.667, close=12 -> above -> 100%
    assert out.loc["2024-08-04", "pct_above_sma3"] == 100.0
    # sma@idx4 = mean(9,12,13) = 11.333, close=13 -> above -> 100%
    assert out.loc["2024-08-05", "pct_above_sma3"] == 100.0
    # sma@idx5 = mean(12,13,8) = 11.0, close=8 -> below -> 0%
    assert out.loc["2024-08-06", "pct_above_sma3"] == 0.0


def test_new_high_low_full_window_only_rule():
    dates = [f"2024-08-{d:02d}" for d in range(1, 6)]
    highs = [10, 12, 9, 15, 11]
    lows = [9, 8, 7, 14, 10]
    closes = highs  # irrelevant to this check; keep simple
    bars = _frame(dates, closes, highs=highs, lows=lows)

    out = compute_breadth(bars, sma_windows={}, high_low_window=3, drop_sealed_window=False)
    out = out.set_index("date")

    # Regression guard: without the full-window gate (e.g. pandas' default
    # min_periods=1), the very first bar would trivially be "its own" 3-day
    # high/low and get counted as a new high AND a new low for free. With no name
    # eligible yet the counts are blank (NaN), not a real zero.
    for d in ("2024-08-01", "2024-08-02"):
        assert math.isnan(out.loc[d, "new_52w_highs"]), d
        assert math.isnan(out.loc[d, "new_52w_lows"]), d

    # from the 3rd date on (window full), real new-high/new-low flags appear
    assert out.loc["2024-08-03", "new_52w_lows"] == 1   # low=7 is the rolling-3 min
    assert out.loc["2024-08-03", "new_52w_highs"] == 0  # high=9 is not the rolling-3 max (12)
    assert out.loc["2024-08-04", "new_52w_highs"] == 1  # high=15 is a new rolling-3 max
    assert out.loc["2024-08-04", "new_52w_lows"] == 0
    assert out.loc["2024-08-05", "new_52w_highs"] == 0
    assert out.loc["2024-08-05", "new_52w_lows"] == 0


def test_a_name_with_fewer_bars_than_the_window_never_becomes_eligible():
    dates = [f"2024-08-{d:02d}" for d in range(1, 4)]  # only 3 bars, window is 5
    closes = [10, 11, 12]
    bars = _frame(dates, closes)

    out = compute_breadth(bars, sma_windows={"pct_above_sma5": 5}, high_low_window=0,
                           drop_sealed_window=False)

    assert out["pct_above_sma5"].isna().all()
