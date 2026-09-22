"""Synthetic-only: a hand-built 3-symbol, 10-day frame, cross-checked against
advance/decline/unchanged/ratio/names-contributing numbers computed by an independent,
plain-Python reference loop (not the pandas machinery in breadth.compute_breadth) —
i.e. genuine "hand counts", not a restatement of the implementation under test.

SMA and 52-week high/low are disabled here (covered by test_breadth_sma_window.py) so
this file stays focused on the advance/decline arithmetic.
"""
import math

import pandas as pd
import pytest

from research.index_history.breadth import compute_breadth

DATES = [f"2024-01-{d:02d}" for d in range(1, 11)]  # 10 sequential days

CLOSES = {
    "AAA": [100, 101, 102, 101, 101, 105, 106, 104, 104, 110],
    "BBB": [50, 49, 49, 48, 50, 50, 51, 52, 52, 52],
    "CCC": [20, 22, 21, 21, 23, 22, 24, 24, 23, 25],
}


def _hand_reference():
    """Plain-Python, index-by-index recomputation of what each date's breadth numbers
    must be, used purely as an independent check — no pandas, no rolling windows."""
    symbols = list(CLOSES)
    n_days = len(DATES)
    rows = []
    for i in range(n_days):
        adv = dec = unch = contributing = 0
        for sym in symbols:
            if i == 0:
                continue  # no prior day to compare against
            prev, cur = CLOSES[sym][i - 1], CLOSES[sym][i]
            contributing += 1
            if cur > prev:
                adv += 1
            elif cur < prev:
                dec += 1
            else:
                unch += 1
        ratio = (adv / dec) if dec else None  # None stands in for NaN here
        rows.append({
            "date": DATES[i], "advancers": adv, "decliners": dec, "unchanged": unch,
            "advance_decline_ratio": ratio, "names_contributing": contributing,
        })
    return rows


def _bars_frame():
    frames = []
    for sym, closes in CLOSES.items():
        frames.append(pd.DataFrame({
            "symbol": sym, "date": DATES, "open": closes, "high": closes,
            "low": closes, "close": closes, "volume": 0,
        }))
    return pd.concat(frames, ignore_index=True)


def test_hand_built_frame_matches_independent_reference_counts():
    expected = _hand_reference()
    out = compute_breadth(_bars_frame(), sma_windows={}, high_low_window=0,
                           drop_sealed_window=False)
    out = out.set_index("date")

    assert len(out) == len(DATES)

    for exp in expected:
        row = out.loc[exp["date"]]
        assert int(row["advancers"]) == exp["advancers"], exp["date"]
        assert int(row["decliners"]) == exp["decliners"], exp["date"]
        assert int(row["unchanged"]) == exp["unchanged"], exp["date"]
        assert int(row["names_contributing"]) == exp["names_contributing"], exp["date"]
        if exp["advance_decline_ratio"] is None:
            assert math.isnan(row["advance_decline_ratio"]), exp["date"]
        else:
            assert row["advance_decline_ratio"] == pytest.approx(exp["advance_decline_ratio"]), exp["date"]


def test_first_day_has_no_prior_close_so_nobody_contributes():
    out = compute_breadth(_bars_frame(), sma_windows={}, high_low_window=0,
                           drop_sealed_window=False)
    first = out.set_index("date").loc[DATES[0]]
    assert first["advancers"] == 0
    assert first["decliners"] == 0
    assert first["unchanged"] == 0
    assert first["names_contributing"] == 0
    assert math.isnan(first["advance_decline_ratio"])


def test_advance_decline_ratio_is_nan_when_there_are_zero_decliners():
    # day index 4 (2024-01-05): AAA unch, BBB advances, CCC advances -> 2 adv, 0 dec
    out = compute_breadth(_bars_frame(), sma_windows={}, high_low_window=0,
                           drop_sealed_window=False)
    row = out.set_index("date").loc["2024-01-05"]
    assert row["advancers"] == 2
    assert row["decliners"] == 0
    assert math.isnan(row["advance_decline_ratio"])
