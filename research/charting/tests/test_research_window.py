"""research_window.py — single source of truth for the project-wide sealed
2023-01-01..2024-07-31 out-of-sample block (review 2026-09-22, defect #1).

Covers the module's own primitives directly (bounds, overlap check, the guarded accessor,
the artifact assertion helper). Wiring into replay.py/movement.py is covered in
test_replay.py / test_movement.py's own "Fix 1" sections.
"""
from __future__ import annotations

import pandas as pd
import pytest

from research.charting import research_window


def test_sealed_bounds_are_the_documented_calendar_dates():
    assert research_window.SEALED_GAP_START == pd.Timestamp("2023-01-01")
    assert research_window.SEALED_GAP_END == pd.Timestamp("2024-07-31")


@pytest.mark.parametrize("date", ["2023-01-01", "2023-06-15", "2024-07-31"])
def test_is_sealed_gap_true_inside_window(date):
    assert research_window.is_sealed_gap(date) is True


@pytest.mark.parametrize("date", ["2022-12-31", "2024-08-01"])
def test_is_sealed_gap_false_just_outside_window(date):
    assert research_window.is_sealed_gap(date) is False


# ── overlaps_sealed_gap ──────────────────────────────────────────────────────────────────


def test_overlaps_sealed_gap_true_for_a_window_entirely_inside():
    assert research_window.overlaps_sealed_gap("2023-03-01", "2023-04-01") is True


def test_overlaps_sealed_gap_true_for_a_partial_overlap_from_before():
    assert research_window.overlaps_sealed_gap("2022-11-01", "2023-02-01") is True


def test_overlaps_sealed_gap_true_for_a_partial_overlap_into_after():
    assert research_window.overlaps_sealed_gap("2024-06-01", "2024-09-01") is True


def test_overlaps_sealed_gap_true_when_the_window_fully_contains_the_block():
    assert research_window.overlaps_sealed_gap("2022-01-01", "2025-01-01") is True


def test_overlaps_sealed_gap_false_for_a_window_entirely_before():
    assert research_window.overlaps_sealed_gap("2021-01-01", "2022-12-31") is False


def test_overlaps_sealed_gap_false_for_a_window_entirely_after():
    assert research_window.overlaps_sealed_gap("2024-08-01", "2026-01-01") is False


def test_overlaps_sealed_gap_handles_start_end_given_in_reverse_order():
    assert research_window.overlaps_sealed_gap("2023-04-01", "2023-03-01") is True
    assert research_window.overlaps_sealed_gap("2022-12-31", "2021-01-01") is False


# ── research_bars: the guarded accessor ──────────────────────────────────────────────────


def _bars_over(start: str, periods: int) -> pd.DataFrame:
    dates = pd.bdate_range(start=start, periods=periods)
    return pd.DataFrame({"date": dates, "close": [100.0] * periods})


def test_research_bars_raises_for_an_explicit_window_touching_2023_03():
    bars = _bars_over("2021-01-04", 10)  # bars themselves are safe...
    with pytest.raises(research_window.SealedWindowError):
        # ...but the caller names an explicit evaluation window that overlaps the block.
        research_window.research_bars(bars, window=("2022-11-01", "2023-03-15"))


def test_research_bars_passes_for_an_explicit_window_in_2021_2022():
    bars = _bars_over("2021-01-04", 10)
    result = research_window.research_bars(bars, window=("2021-06-01", "2022-06-01"))
    assert result is bars  # returned unchanged, never filtered/truncated


def test_research_bars_defaults_to_the_bars_own_date_span_when_no_window_given():
    sealed_bars = _bars_over("2023-02-01", 5)
    with pytest.raises(research_window.SealedWindowError):
        research_window.research_bars(sealed_bars)

    safe_bars = _bars_over("2021-02-01", 5)
    assert research_window.research_bars(safe_bars) is safe_bars


def test_research_bars_empty_frame_with_no_window_is_never_refused():
    empty = pd.DataFrame({"date": pd.to_datetime([]), "close": []})
    assert research_window.research_bars(empty) is empty


# ── assert_no_sealed_rows: the artifact assertion helper ─────────────────────────────────


def test_assert_no_sealed_rows_passes_silently_for_clean_dates():
    dates = ["2021-01-04", "2022-06-15", "2024-08-01"]
    research_window.assert_no_sealed_rows(dates)  # must not raise


def test_assert_no_sealed_rows_catches_a_single_sealed_row():
    dates = ["2021-01-04", "2023-06-15", "2024-08-01"]  # exactly one poisoned row
    with pytest.raises(research_window.SealedWindowError, match="2023-06-15"):
        research_window.assert_no_sealed_rows(dates)


def test_assert_no_sealed_rows_over_an_empty_iterable_never_raises():
    research_window.assert_no_sealed_rows([])
