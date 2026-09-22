"""Synthetic-only: the sealed window (2023-01-01..2024-07-31) must not reach any breadth
value, as an output row OR as a rolling-window input to a later date.

Probe: poison every sealed bar (prices x1000) and require identical breadth everywhere
else. Negative control: with drop_sealed_window=False (sealed bars kept as inputs) the
same poison DOES move the post-sealed values — so the probe can see a leak."""
import math

import pandas as pd
import pytest

from research.index_history.breadth import compute_breadth

PRE = [f"2022-12-{d:02d}" for d in (26, 27, 28, 29, 30)]
SEALED = ["2023-01-02", "2023-06-01", "2024-01-02", "2024-07-30", "2024-07-31"]
POST = [f"2024-08-{d:02d}" for d in (1, 2, 5, 6, 7)]


def _bars(poison: float = 1.0) -> pd.DataFrame:
    rows = []
    for sym, base in (("A", 100.0), ("B", 50.0)):
        for i, d in enumerate(PRE + SEALED + POST):
            px = base + (i % 3) - 1  # a small zig-zag so adv/decl and SMA flags vary
            if d in SEALED:
                px *= poison
            rows.append({"symbol": sym, "date": d, "open": px, "high": px + 1, "low": px - 1,
                         "close": px, "volume": 0})
    return pd.DataFrame(rows)


def _run(bars, drop_sealed_window=True):
    return compute_breadth(bars, sma_windows={"pct_above_sma3": 3}, high_low_window=3,
                           drop_sealed_window=drop_sealed_window).set_index("date")


def test_no_sealed_rows_in_output():
    out = _run(_bars())
    assert not set(out.index) & set(SEALED)
    assert list(out.index) == PRE + POST


def test_poisoned_sealed_bars_do_not_change_any_value():
    clean, poisoned = _run(_bars()), _run(_bars(poison=1000.0))
    pd.testing.assert_frame_equal(clean, poisoned)


def test_negative_control_the_probe_sees_a_leak_when_sealed_bars_are_inputs():
    clean = _run(_bars(), drop_sealed_window=False).loc[POST]
    poisoned = _run(_bars(poison=1000.0), drop_sealed_window=False).loc[POST]
    with pytest.raises(AssertionError):
        pd.testing.assert_frame_equal(clean, poisoned)


def test_rolling_state_restarts_after_the_sealed_window():
    out = _run(_bars())
    first = out.loc[POST[0]]
    # no post-sealed prior close yet: nothing contributes, ratio blank
    assert first["names_contributing"] == 0
    assert first["advancers"] == first["decliners"] == first["unchanged"] == 0
    assert math.isnan(first["advance_decline_ratio"])
    # the 3-bar windows fill from post-sealed bars alone: blank on bars 1-2, real on bar 3
    for d in POST[:2]:
        assert math.isnan(out.loc[d, "pct_above_sma3"]), d
        assert math.isnan(out.loc[d, "new_52w_highs"]), d
    assert not math.isnan(out.loc[POST[2], "pct_above_sma3"])
    assert not math.isnan(out.loc[POST[2], "new_52w_highs"])
    assert out.loc[POST[1], "names_contributing"] == 2
