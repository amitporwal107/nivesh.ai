"""pipeline.py: multi-symbol orchestration + optional artifact write. Segment-guard-specific
tests live in test_events_sealed.py; this file covers the multi-symbol/aggregation/write path."""
from __future__ import annotations

from research.charting.events import pipeline
from research.charting.tests._events_helpers import (
    confirmed_hh_hl_with_runway,
    confirmed_rectangle_with_runway,
    confirmed_support_resistance_with_runway,
)


def test_build_event_dataset_aggregates_multiple_symbols_in_sorted_order():
    bars = {
        "ZZZ": confirmed_hh_hl_with_runway(),
        "AAA": confirmed_rectangle_with_runway(),
        "MMM": confirmed_support_resistance_with_runway(),
    }
    result = pipeline.build_event_dataset(bars, segment="pre_sealed")
    assert result["symbols"] == ["AAA", "MMM", "ZZZ"]
    assert [r["symbol"] for r in result["rows"]] == sorted(r["symbol"] for r in result["rows"])
    assert len(result["rows"]) >= 3  # at least one confirmed event per symbol


def test_build_event_dataset_writes_a_run_when_out_dir_given(tmp_path):
    bars = {"AAA": confirmed_rectangle_with_runway()}
    result = pipeline.build_event_dataset(bars, segment="pre_sealed", out_dir=tmp_path)
    assert result["manifest"] is not None
    assert (tmp_path / "events.jsonl").exists()
    assert (tmp_path / "manifest.json").exists()
    assert result["manifest"]["row_count"] == len(result["rows"])


def test_build_event_dataset_manifest_carries_the_resolved_cost_and_tax_rule_versions(tmp_path):
    bars = {"AAA": confirmed_rectangle_with_runway()}
    result = pipeline.build_event_dataset(bars, segment="pre_sealed", out_dir=tmp_path)
    manifest = result["manifest"]
    assert manifest["cost_rule_versions"] == ["nse-equity-statutory-v1@1"]
    assert manifest["tax_rule_versions"] == ["tax-equity-v1@1"]


def test_build_event_dataset_empty_universe_produces_no_rows():
    result = pipeline.build_event_dataset({}, segment="pre_sealed")
    assert result["rows"] == []
    assert result["symbols"] == []
