"""Sealed-window guard (task item 6, docs/charting.md S35.4 fix #1): every research entry
point in this package must refuse a window/segment that touches 2023-01-01..2024-07-31."""
from __future__ import annotations

import pandas as pd
import pytest

from research.charting.events import extraction, pipeline, schema
from research.charting.research_window import SealedWindowError
from research.charting.tests import synth
from research.charting.tests._events_helpers import confirmed_rectangle_with_runway


def test_extract_events_refuses_a_frame_overlapping_the_sealed_block():
    # synth.py's own default anchor (2024-01-02) lands squarely inside the sealed window --
    # extract_events must refuse it exactly as replay.replay() does, never silently proceed.
    bars = synth.fixture_02_low_volume_breakout(synth.rect1())
    assert schema.SEALED_GAP_START <= bars["date"].min() <= schema.SEALED_GAP_END  # sanity: really inside
    with pytest.raises(SealedWindowError):
        extraction.extract_events(bars, "SYN1")


def test_extract_events_refuses_a_frame_straddling_into_the_sealed_block():
    bars = synth.bars_from_closes([100.0 + i * 0.1 for i in range(80)], start_date="2022-11-01")
    assert bars["date"].max() >= pd.Timestamp("2023-01-01")  # sanity: really straddles in
    with pytest.raises(SealedWindowError):
        extraction.extract_events(bars, "SYN1")


def test_extract_events_accepts_a_frame_entirely_before_the_sealed_block():
    bars = confirmed_rectangle_with_runway()  # already shifted to 2021
    assert bars["date"].max() < pd.Timestamp("2023-01-01")
    rows = extraction.extract_events(bars, "SYN1")  # must not raise
    assert len(rows) == 1


# ── pipeline.py's own, additional per-segment bound (stricter than the overlap-only guard) ──


def test_assert_segment_bounds_pre_sealed_rejects_a_frame_that_runs_into_2023():
    bars = synth.bars_from_closes([100.0] * 10, start_date="2022-12-20")  # crosses into 2023
    with pytest.raises(SealedWindowError):
        pipeline.assert_segment_bounds(bars, "pre_sealed", symbol="SYN1")


def test_assert_segment_bounds_pre_sealed_accepts_a_frame_entirely_in_2021():
    bars = synth.bars_from_closes([100.0] * 10, start_date="2021-06-01")
    pipeline.assert_segment_bounds(bars, "pre_sealed", symbol="SYN1")  # must not raise


def test_assert_segment_bounds_post_sealed_rejects_a_frame_starting_before_2024_08_01():
    bars = synth.bars_from_closes([100.0] * 10, start_date="2024-07-15")
    with pytest.raises(SealedWindowError):
        pipeline.assert_segment_bounds(bars, "post_sealed", symbol="SYN1")


def test_assert_segment_bounds_post_sealed_accepts_fresh_history():
    bars = synth.bars_from_closes([100.0] * 10, start_date="2024-09-01")
    pipeline.assert_segment_bounds(bars, "post_sealed", symbol="SYN1")  # must not raise


def test_assert_segment_bounds_unknown_segment_raises_value_error():
    bars = synth.bars_from_closes([100.0] * 3, start_date="2021-01-01")
    with pytest.raises(ValueError):
        pipeline.assert_segment_bounds(bars, "mid_sealed", symbol="SYN1")


def test_build_event_dataset_raises_before_extracting_any_symbol_on_a_bad_segment():
    """One mis-scoped symbol out of several must fail the WHOLE call before any extraction
    happens -- never silently drop just that symbol and continue (task hard rule: a real
    blocker is reported, not routed around)."""
    good = confirmed_rectangle_with_runway()
    bad = synth.fixture_02_low_volume_breakout(synth.rect1())  # inside the sealed block
    with pytest.raises((SealedWindowError, ValueError)):
        pipeline.build_event_dataset({"GOOD": good, "BAD": bad}, segment="pre_sealed")


def test_build_event_dataset_succeeds_for_a_properly_scoped_pre_sealed_universe():
    bars = confirmed_rectangle_with_runway()
    result = pipeline.build_event_dataset({"SYN1": bars}, segment="pre_sealed")
    assert result["segment"] == "pre_sealed"
    assert result["symbols"] == ["SYN1"]
    assert len(result["rows"]) == 1
    assert result["manifest"] is None  # no out_dir given
