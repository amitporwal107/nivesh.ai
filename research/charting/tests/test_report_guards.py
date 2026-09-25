"""Fail-loud guards against the silent-wrong-answer class of bug.

Both guards exist because the failure they catch does NOT crash. A missed horizon lookup, or a
filter that matches nothing, produces a complete-looking report full of nulls — which a reader
interprets as "the patterns did nothing" rather than "nothing was measured". Those conclusions are
opposite, and nothing in the output distinguishes them.

Encountered for real on 2026-09-25: a JSON-backed cache turned integer horizon keys into strings,
and every `by_h.get(horizon)` would have missed.
"""
from __future__ import annotations

import pytest

from research.charting.study import report


def _priced_row(horizon_keys, *, event_id="E1"):
    scen = {s: {"gross": 10.0, "net_before_tax": 8.0, "total_cost": 2.0,
                "entry_slippage": 0.5, "exit_slippage": 0.5} for s in report.DEFAULT_COST_SCENARIOS}
    return {
        "event_id": event_id, "signal_date": "2021-03-01", "direction": "BULLISH",
        "costs": {"by_horizon": {h: {"available": True, "scenarios": scen} for h in horizon_keys}},
    }


# ── the horizon key guard ───────────────────────────────────────────────────────────────────────

def test_string_horizon_keys_raise_rather_than_silently_missing():
    """The exact JSON round-trip corruption. Must be loud."""
    row = _priced_row(["1", "3", "5", "10", "20"])          # strings, not ints
    with pytest.raises(report.HorizonKeyError, match="key-type corruption"):
        report._horizon_cost_scenario(row, 5, "base")


def test_a_bearish_row_with_no_priced_trade_is_still_legal():
    """`by_horizon: None` is legitimate — a BEARISH row prices no trade. The guard must not turn
    ordinary absence into an error, or every real dataset fails."""
    assert report._horizon_cost_scenario({"costs": {"by_horizon": None}}, 5) is None
    assert report._horizon_cost_scenario({"costs": {}}, 5) is None
    assert report._horizon_cost_scenario({}, 5) is None


def test_an_unavailable_horizon_block_is_still_legal():
    """`available: False` means 'insufficient forward bars', which is data, not corruption."""
    row = _priced_row([1, 3, 5, 10, 20])
    row["costs"]["by_horizon"][5] = {"available": False, "reason": "insufficient_forward_bars"}
    assert report._horizon_cost_scenario(row, 5) is None


def test_correct_int_keys_work_normally():
    assert report._horizon_cost_scenario(_priced_row([1, 3, 5, 10, 20]), 5)["net_before_tax"] == 8.0


def test_the_same_guard_covers_target_blocks():
    row = {"targets": {"pct_2": {"by_horizon": {"5": {"available": True}}}}}
    with pytest.raises(report.HorizonKeyError, match="key-type corruption"):
        report._target_horizon_block(row, "pct_2", 5)
    assert report._target_horizon_block({"targets": None}, "pct_2", 5) is None


# ── the vacuous-statistics guard ────────────────────────────────────────────────────────────────

def test_priced_rows_producing_only_empty_cells_is_a_defect_not_a_result():
    rows = [_priced_row([1, 3, 5, 10, 20], event_id=f"E{i}") for i in range(40)]
    all_empty = {h: {s: report.n_cell(0) for s in report.DEFAULT_COST_SCENARIOS}
                 for h in (1, 3, 5, 10, 20)}
    with pytest.raises(ValueError, match="pipeline defect, not a result"):
        report.assert_statistics_are_not_vacuous(rows, all_empty, label="pre_sealed RECTANGLE")


def test_a_genuinely_unpriceable_dataset_passes_quietly():
    """All-BEARISH rows legitimately price nothing. That is a result, not a defect."""
    rows = [{"event_id": "B1", "direction": "BEARISH", "costs": {"by_horizon": None}}]
    empty = {5: {"base": report.n_cell(0)}}
    report.assert_statistics_are_not_vacuous(rows, empty)


def test_one_populated_cell_is_enough_to_pass():
    rows = [_priced_row([1, 3, 5, 10, 20], event_id=f"E{i}") for i in range(40)]
    cells = {h: {s: report.n_cell(0) for s in report.DEFAULT_COST_SCENARIOS} for h in (1, 3, 5, 10, 20)}
    cells[5]["base"] = report.n_cell(37)
    report.assert_statistics_are_not_vacuous(rows, cells)


def test_an_empty_dataset_passes_quietly():
    report.assert_statistics_are_not_vacuous([], {})


def test_the_guard_reports_enough_to_debug_with():
    """The message must say how many rows were priceable — that is what separates 'no data reached
    this stage' from 'data reached it and produced nothing'."""
    rows = [_priced_row([1, 3, 5, 10, 20], event_id=f"E{i}") for i in range(7)]
    with pytest.raises(ValueError) as exc:
        report.assert_statistics_are_not_vacuous(rows, {5: {"base": report.n_cell(0)}}, label="seg X")
    assert "seg X" in str(exc.value) and "7 rows" in str(exc.value) and "7 carrying" in str(exc.value)
