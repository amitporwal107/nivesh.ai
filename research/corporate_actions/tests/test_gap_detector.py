"""Synthetic-only: the large-gap safety net on (a) a genuine unadjusted discontinuity --
the SIEMENS/ABFRL shape (close halved-or-worse overnight, no back-adjustment applied to
the bars before it) -- vs (b) a back-adjusted split, where the whole pre-event history has
already been rescaled so the open-vs-prior-close ratio stays ~1.0 (the IRCTC shape from
data-availability.md: "close-to-open ratio 0.989, no discontinuity"). Also boundary/edge
cases: below-threshold gaps are not flagged, an explicit threshold overrides CONFIG, and
symbols below gap_detector_min_bars produce no flags.
"""
import pandas as pd
import pytest

from research.corporate_actions.config import CONFIG
from research.corporate_actions.gap_detector import (
    compute_gaps, flag_large_gaps, scan_universe_for_large_gaps,
)


def _bars(closes, opens=None):
    n = len(closes)
    opens = opens if opens is not None else closes
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    return pd.DataFrame({
        "date": dates, "open": opens, "high": [max(o, c) for o, c in zip(opens, closes)],
        "low": [min(o, c) for o, c in zip(opens, closes)], "close": closes,
        "volume": [1000] * n,
    })


def test_unadjusted_demerger_style_gap_is_flagged():
    # Ten steady days at ~100, then a demerger-style collapse to ~65 (SIEMENS-scale ratio),
    # never adjusted retroactively -- exactly what "not back-adjusted" looks like raw.
    closes = [100, 101, 99, 100, 102, 101, 100, 99, 100, 100]
    opens = list(closes)
    # the event bar: prior close 100, opens at 65 (a -35% gap, matching SIEMENS' -34.74%)
    closes.append(64)
    opens.append(65)
    closes += [64, 65, 63]
    opens += [64, 65, 64]
    bars = _bars(closes, opens)

    flagged = flag_large_gaps(bars)
    assert len(flagged) == 1
    row = flagged.iloc[0]
    assert row["gap_pct"] == pytest.approx(-35.0, abs=0.05)


def test_back_adjusted_split_produces_no_flag():
    # A clean 1:2 split, back-adjusted through the WHOLE history (as IRCTC's was, per
    # data-availability.md) -- every price already rescaled, so open/prev_close stays ~1.0
    # even across the split date. This is the "should NOT be flagged" control.
    pre_split_raw = [200, 202, 198, 201, 199]  # what the price "really" was, pre-adjustment
    adjustment_factor = 0.5
    adjusted_pre = [p * adjustment_factor for p in pre_split_raw]
    post_split = [101, 100, 102, 99, 101]  # already on the post-split scale
    closes = adjusted_pre + post_split
    opens = list(closes)  # no gap at all once back-adjusted
    bars = _bars(closes, opens)

    flagged = flag_large_gaps(bars)
    assert flagged.empty


def test_gap_below_threshold_is_not_flagged():
    closes = [100, 100, 100, 100]
    opens = [100, 100, 90, 100]  # -10% gap on row 2 -- below the 20% default threshold
    bars = _bars(closes, opens)
    flagged = flag_large_gaps(bars)
    assert flagged.empty


def test_explicit_threshold_overrides_config_default():
    closes = [100, 100, 100]
    opens = [100, 88, 100]  # -12% gap
    bars = _bars(closes, opens)
    assert flag_large_gaps(bars).empty  # below default 20%
    flagged = flag_large_gaps(bars, threshold_pct=10.0)
    assert len(flagged) == 1


def test_first_row_has_no_prior_close_and_is_never_flagged():
    # Row 0 has no prior close to gap from; if it were (mis)treated as gapping from 0 or
    # NaN it would look enormous. Every other row is flat, so only row 0's NaN is at risk.
    closes = [40, 40, 40]
    opens = [40, 40, 40]
    bars = _bars(closes, opens)
    gaps = compute_gaps(bars)
    assert pd.isna(gaps.iloc[0]["gap_pct"])
    assert flag_large_gaps(bars).empty


def test_below_min_bars_produces_no_flags():
    bars = _bars([100])
    flagged = flag_large_gaps(bars)
    assert flagged.empty
    assert len(bars) < CONFIG["gap_detector_min_bars"]


def test_scan_universe_aggregates_and_sorts_by_gap_magnitude_desc():
    small_gap = _bars([100, 100, 76])  # -24%
    big_gap = _bars([100, 100, 40])    # -60%
    no_gap = _bars([100, 100, 100])
    frames = [("SMALL", small_gap), ("BIG", big_gap), ("NONE", no_gap)]
    out = scan_universe_for_large_gaps(frames)
    assert list(out["symbol"]) == ["BIG", "SMALL"]
    assert out.iloc[0]["gap_pct"] < out.iloc[1]["gap_pct"]  # -60 < -24
