"""study/integrity.py: CHARTING_PREREGISTRATION_V1 §8 integrity rules as callable functions.
Kill switch and independent-recomputation are run over the real extraction pipeline (they are
ABOUT that pipeline's own reproducibility/correctness); the sealed-window check is exercised
both against clean rows and a deliberately poisoned one."""
from __future__ import annotations

import hashlib

import pytest

from research.charting.events import extraction, writer
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


# ── RunDigest: §8 evidence without holding the dataset twice ────────────────────────────────────


def _digest_universe():
    """Real multi-symbol pattern rows, grouped by symbol in run order — the order a streaming
    digest would actually see them."""
    from research.charting.events import extraction
    from research.charting.tests._events_helpers import confirmed_rectangle_with_runway

    base = confirmed_rectangle_with_runway(tail_len=40)
    by_symbol = {}
    for i in range(5):
        scaled = base.copy()
        for c in ("open", "high", "low", "close"):
            scaled[c] = scaled[c] * (1.0 + 0.05 * i)
        sym = f"SYM{i:02d}"
        by_symbol[sym] = extraction.extract_events(scaled, sym)
    assert sum(len(v) for v in by_symbol.values()) > 1, "need >1 row for chunking to mean anything"
    return by_symbol


def test_a_chunked_digest_equals_the_whole_list_hash():
    """The claim the streaming path rests on: `_dump_jsonl` emits `"\\n".join(lines) + "\\n"`, so a
    whole list's bytes are exactly its chunks' bytes concatenated."""
    by_symbol = _digest_universe()
    rows = [r for sym in sorted(by_symbol) for r in by_symbol[sym]]

    d = integrity.RunDigest()
    for sym in sorted(by_symbol):
        d.update(by_symbol[sym])

    whole = hashlib.sha256(writer._dump_jsonl(rows)).hexdigest()
    assert d.hexdigest() == whole
    assert d.n_rows == len(rows)
    assert d.pattern_ids == {r["pattern_id"] for r in rows}


def test_the_streamed_verdict_is_identical_to_the_row_based_one():
    by_symbol = _digest_universe()
    rows = [r for sym in sorted(by_symbol) for r in by_symbol[sym]]

    def digest():
        d = integrity.RunDigest()
        for sym in sorted(by_symbol):
            d.update(by_symbol[sym])
        return d

    assert integrity.kill_switch_check_digests(digest(), digest()) == \
        integrity.kill_switch_check(rows, rows)


def test_an_empty_chunk_changes_nothing():
    """A symbol that produced no events is normal, and must not perturb the hash — `_dump_jsonl([])`
    is `b""`, so skipping it and feeding it must agree."""
    by_symbol = _digest_universe()
    a, b = integrity.RunDigest(), integrity.RunDigest()
    for sym in sorted(by_symbol):
        a.update(by_symbol[sym])
        b.update([])
        b.update(by_symbol[sym])
    assert a.hexdigest() == b.hexdigest() and a.n_rows == b.n_rows


def test_a_reordered_stream_is_reported_as_a_mismatch_not_silently_accepted():
    """Order is part of §8's claim — "identical event files" is about bytes `write_run` would
    produce. Feeding chunks out of order must read as a FAILED reproducibility check, which is
    exactly what it would mean if a real run's order had drifted."""
    by_symbol = _digest_universe()
    syms = sorted(by_symbol)
    assert len(syms) > 1

    fwd, rev = integrity.RunDigest(), integrity.RunDigest()
    for sym in syms:
        fwd.update(by_symbol[sym])
    for sym in reversed(syms):
        rev.update(by_symbol[sym])

    verdict = integrity.kill_switch_check_digests(fwd, rev)
    assert verdict["passed"] is False
    assert verdict["event_file_sha256_match"] is False
    assert verdict["pattern_id_sets_match"] is True, "same rows, so only the ORDER differs"


def test_a_genuinely_different_dataset_fails_and_names_the_difference():
    by_symbol = _digest_universe()
    syms = sorted(by_symbol)
    full, short = integrity.RunDigest(), integrity.RunDigest()
    for sym in syms:
        full.update(by_symbol[sym])
    for sym in syms[:-1]:
        short.update(by_symbol[sym])

    verdict = integrity.kill_switch_check_digests(full, short)
    assert verdict["passed"] is False
    assert verdict["pattern_id_set_symmetric_difference"], "the differing ids must be named"
    assert verdict["n_rows_a"] > verdict["n_rows_b"]
