"""writer.py: hashed, immutable run-folder artifact writer (task item 7) -- mirrors
`replay.write_run`'s manifest convention (sha256 per artifact, content/config vs. run-metadata
split)."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from research.charting.events import extraction, writer
from research.charting.tests._events_helpers import confirmed_rectangle_with_runway


def _rows():
    bars = confirmed_rectangle_with_runway()
    return extraction.extract_events(bars, "SYN1")


def test_write_run_creates_events_jsonl_and_manifest(tmp_path):
    rows = _rows()
    manifest = writer.write_run(rows, tmp_path, segment="pre_sealed", symbols=["SYN1"])
    events_path = tmp_path / "events.jsonl"
    manifest_path = tmp_path / "manifest.json"
    assert events_path.exists()
    assert manifest_path.exists()
    assert manifest["row_count"] == len(rows) == 1
    assert manifest["segment"] == "pre_sealed"
    assert manifest["symbols"] == ["SYN1"]
    assert manifest["schema_version"] == 2
    assert len(manifest["artifacts"]) == 1
    assert manifest["artifacts"][0]["path"] == "events.jsonl"


def test_manifest_sha256_matches_the_actual_file_bytes(tmp_path):
    rows = _rows()
    manifest = writer.write_run(rows, tmp_path, segment="pre_sealed", symbols=["SYN1"])
    content = (tmp_path / "events.jsonl").read_bytes()
    assert manifest["artifacts"][0]["sha256"] == hashlib.sha256(content).hexdigest()


def test_events_jsonl_is_one_json_object_per_row_and_round_trips():
    rows = _rows()
    content = writer._dump_jsonl(rows)
    lines = content.decode("utf-8").splitlines()
    assert len(lines) == len(rows)
    parsed = [json.loads(line) for line in lines]
    assert parsed[0]["symbol"] == rows[0]["symbol"]
    assert parsed[0]["pattern_id"] == rows[0]["pattern_id"]


def test_write_run_is_deterministic_across_repeated_calls_same_rows(tmp_path):
    rows = _rows()
    out_a, out_b = tmp_path / "a", tmp_path / "b"
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    manifest_a = writer.write_run(rows, out_a, segment="pre_sealed", symbols=["SYN1"], now=now)
    manifest_b = writer.write_run(rows, out_b, segment="pre_sealed", symbols=["SYN1"], now=now)
    # The primary content artifact is byte-identical across repeated runs over the same rows...
    assert (out_a / "events.jsonl").read_bytes() == (out_b / "events.jsonl").read_bytes()
    assert manifest_a["artifacts"][0]["sha256"] == manifest_b["artifacts"][0]["sha256"]
    # ...and the manifest matches too when wall-clock time is pinned identically.
    assert manifest_a == manifest_b


def test_write_run_id_and_generated_at_are_the_only_wall_clock_dependent_fields(tmp_path):
    rows = _rows()
    now_a = datetime(2026, 1, 1, tzinfo=timezone.utc)
    now_b = datetime(2026, 6, 1, tzinfo=timezone.utc)
    manifest_a = writer.write_run(rows, tmp_path / "a", segment="pre_sealed", symbols=["SYN1"], now=now_a)
    manifest_b = writer.write_run(rows, tmp_path / "b", segment="pre_sealed", symbols=["SYN1"], now=now_b)
    diffs = {k for k in manifest_a if manifest_a[k] != manifest_b[k]}
    assert diffs == {"run_id", "generated_at"}


def test_write_run_records_cost_and_tax_rule_versions_when_supplied(tmp_path):
    rows = _rows()
    manifest = writer.write_run(
        rows, tmp_path, segment="pre_sealed", symbols=["SYN1"],
        cost_rule_versions=["nse-equity-statutory-v1@1", "nse-equity-statutory-v1@1"],
        tax_rule_versions=["tax-equity-v1@1"],
    )
    assert manifest["cost_rule_versions"] == ["nse-equity-statutory-v1@1"]  # de-duplicated
    assert manifest["tax_rule_versions"] == ["tax-equity-v1@1"]


def test_write_run_handles_zero_rows():
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        manifest = writer.write_run([], d, segment="post_sealed", symbols=[])
        assert manifest["row_count"] == 0
        from pathlib import Path

        assert (Path(d) / "events.jsonl").read_bytes() == b""


def test_non_finite_values_are_written_as_null_so_the_jsonl_is_strict_json(tmp_path):
    import json
    from research.charting.events.writer import _dump_jsonl

    data = _dump_jsonl([{"liquidity": {"participation_ratio": float("inf"), "adv_inr_at_t": 0.0}, "x": [float("nan"), 1.0]}])
    row = json.loads(data.decode("utf-8"))
    assert row["liquidity"]["participation_ratio"] is None and row["x"] == [None, 1.0]
    assert b"Infinity" not in data and b"NaN" not in data
