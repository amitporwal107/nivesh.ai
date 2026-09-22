"""study/integrity.py: CHARTING_PREREGISTRATION_V1 §8 integrity rules as callable functions.
Kill switch and independent-recomputation are run over the real extraction pipeline (they are
ABOUT that pipeline's own reproducibility/correctness); the sealed-window check is exercised
both against clean rows and a deliberately poisoned one."""
from __future__ import annotations

import pytest

from research.charting.events import extraction
from research.charting.research_window import SealedWindowError
from research.charting.study import integrity
from research.charting.tests._events_helpers import confirmed_rectangle_with_runway


# ── kill_switch_check ─────────────────────────────────────────────────────────────────────


def test_kill_switch_passes_for_two_builds_of_the_same_inputs():
    bars = confirmed_rectangle_with_runway(tail_len=40)
    rows_a = extraction.extract_events(bars, "SYN1")
    rows_b = extraction.extract_events(bars, "SYN1")  # same inputs, called again
    out = integrity.kill_switch_check(rows_a, rows_b)
    assert out["passed"] is True
    assert out["pattern_id_sets_match"] is True
    assert out["event_file_sha256_match"] is True
    assert out["sha256_a"] == out["sha256_b"]
    assert out["pattern_id_set_symmetric_difference"] == []


def test_kill_switch_fails_when_pattern_id_sets_differ():
    bars = confirmed_rectangle_with_runway(tail_len=40)
    rows_a = extraction.extract_events(bars, "SYN1")
    rows_b = extraction.extract_events(bars, "OTHER_SYMBOL")  # different pattern_id prefix
    out = integrity.kill_switch_check(rows_a, rows_b)
    assert out["passed"] is False
    assert out["pattern_id_sets_match"] is False
    assert out["event_file_sha256_match"] is False
    assert out["pattern_id_set_symmetric_difference"] != []


def test_kill_switch_fails_when_row_content_differs_but_ids_happen_to_match():
    bars = confirmed_rectangle_with_runway(tail_len=40)
    rows_a = extraction.extract_events(bars, "SYN1")
    rows_b = [dict(r) for r in rows_a]
    rows_b[0] = {**rows_b[0], "atr_at_t": (rows_b[0]["atr_at_t"] or 0.0) + 999.0}  # same id, different content
    out = integrity.kill_switch_check(rows_a, rows_b)
    assert out["pattern_id_sets_match"] is True
    assert out["event_file_sha256_match"] is False
    assert out["passed"] is False


# ── assert_no_sealed_rows_in_dataset ──────────────────────────────────────────────────────


def test_assert_no_sealed_rows_in_dataset_passes_for_clean_rows():
    bars = confirmed_rectangle_with_runway(tail_len=40)
    rows = extraction.extract_events(bars, "SYN1")
    integrity.assert_no_sealed_rows_in_dataset(rows)  # must not raise


def test_assert_no_sealed_rows_in_dataset_raises_for_a_sealed_signal_date():
    rows = [{"event_id": "E1", "signal_date": "2023-06-15"}]  # inside 2023-01-01..2024-07-31
    with pytest.raises(SealedWindowError):
        integrity.assert_no_sealed_rows_in_dataset(rows)


# ── recompute_row_independently / recompute_sample (§8 / TC-40) ─────────────────────────


def test_recompute_row_independently_zero_mismatches_for_a_real_event():
    bars = confirmed_rectangle_with_runway(tail_len=40)
    rows = extraction.extract_events(bars, "SYN1")
    row = rows[0]
    result = integrity.recompute_row_independently(bars, row, horizon=5)
    assert result["event_id"] == row["event_id"]
    assert all(result["checks"].values()), result["checks"]
    assert set(result["checks"].keys()) >= {"signal_date_valid", "entry", "exit_close", "close_return", "mfe", "mae", "net_before_tax"}


def test_recompute_row_independently_bearish_row_only_checks_the_flag():
    from research.charting.tests._events_helpers import confirmed_rectangle_bearish_with_runway

    bars = confirmed_rectangle_bearish_with_runway(tail_len=40)
    rows = extraction.extract_events(bars, "SYN1")
    bearish_rows = [r for r in rows if r["direction"] == "BEARISH"]
    assert bearish_rows
    result = integrity.recompute_row_independently(bars, bearish_rows[0], horizon=5)
    assert set(result["checks"].keys()) == {"signal_date_valid", "bearish_flagged"}
    assert result["checks"]["bearish_flagged"] is True


def test_recompute_row_independently_detects_a_deliberately_corrupted_row():
    """Negative control: feeding a hand-corrupted row (wrong entry price) must produce a
    mismatch, proving the recomputation actually checks something rather than trivially
    agreeing with whatever the row says."""
    bars = confirmed_rectangle_with_runway(tail_len=40)
    row = extraction.extract_events(bars, "SYN1")[0]
    corrupted = {**row, "entry": {**row["entry"], "primary": {**row["entry"]["primary"], "price": row["entry"]["primary"]["price"] + 1000.0}}}
    result = integrity.recompute_row_independently(bars, corrupted, horizon=5)
    assert result["checks"]["entry"] is False


def test_recompute_sample_tallies_matches_across_multiple_rows_and_symbols():
    from research.charting.tests._events_helpers import (
        confirmed_hh_hl_with_runway,
        confirmed_support_resistance_with_runway,
    )

    bars_by_symbol = {
        "SYN1": confirmed_rectangle_with_runway(tail_len=40),
        "SYN2": confirmed_support_resistance_with_runway(tail_len=40),
        "ZZ": confirmed_hh_hl_with_runway(tail_len=40),
    }
    rows = []
    for symbol, bars in bars_by_symbol.items():
        rows.extend(extraction.extract_events(bars, symbol))
    assert len(rows) >= 3

    result = integrity.recompute_sample(bars_by_symbol, rows, horizon=5)
    assert result["n_rows"] == len(rows)
    assert result["passed"] is True
    assert result["mismatched_event_ids"] == []
    for field, tally in result["fields"].items():
        assert tally["mismatch"] == 0, (field, tally)


def test_recompute_sample_respects_sample_size_and_is_deterministic_for_the_same_seed():
    bars = confirmed_rectangle_with_runway(tail_len=200)  # long runway -> many confirmed events unlikely with 1 symbol,
    rows = extraction.extract_events(bars, "SYN1")         # but sample_size larger than n_rows is the common real case
    a = integrity.recompute_sample({"SYN1": bars}, rows, horizon=5, sample_size=100, seed=3)
    b = integrity.recompute_sample({"SYN1": bars}, rows, horizon=5, sample_size=100, seed=3)
    assert a["n_rows"] == b["n_rows"] == len(rows)  # capped at population size, same as random_control_rows
    assert a["mismatched_event_ids"] == b["mismatched_event_ids"]
