"""writer.py: hashed, immutable run-folder artifact writer (task item 7) -- mirrors
`replay.write_run`'s manifest convention (sha256 per artifact, content/config vs. run-metadata
split)."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

import pytest

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


# ── gzip artifacts (study-v2 storage redesign, 2026-09-23) ──────────────────────────────────────

def _rows_for_compression():
    """Enough repeated structure to be a fair compression subject without needing real bars."""
    return [
        {"event_id": f"E{i}", "symbol": "SYN1", "signal_date": "2021-03-01", "pattern_type": "RECTANGLE",
         "costs": {"by_horizon": {h: {"available": True, "scenarios": {
             s: {"gross": 1.0 + i, "net_before_tax": 0.9 + i, "total_cost": 0.1,
                 "entry_slippage": 0.01, "exit_slippage": 0.02} for s in
             ("optimistic", "base", "conservative", "stress")}} for h in (1, 3, 5, 10, 20)}}}
        for i in range(200)
    ]


def test_gzip_artifact_round_trips_to_exactly_the_same_rows(tmp_path):
    rows = _rows_for_compression()
    manifest = writer.write_run(rows, tmp_path, segment="pre_sealed", symbols=["SYN1"], compress=True)

    path = tmp_path / "events.jsonl.gz"
    assert path.is_file()
    assert not (tmp_path / "events.jsonl").exists()   # the uncompressed copy is not left behind

    import gzip as _gz, json as _json
    back = [_json.loads(line) for line in _gz.open(path, "rt", encoding="utf-8")]
    assert len(back) == len(rows)
    assert back == [_json.loads(line) for line in writer._dump_jsonl(rows).decode().splitlines()]
    assert manifest["artifacts"][0]["path"] == "events.jsonl.gz"


def test_the_manifest_sha256_still_hashes_the_UNCOMPRESSED_bytes(tmp_path):
    """The §8 kill switch compares `sha256(_dump_jsonl(rows))` computed in memory. If compression
    changed what `sha256` means, that comparison would silently start failing (or worse, passing for
    the wrong reason), so the two manifests must agree on it."""
    rows = _rows_for_compression()
    plain = writer.write_run(rows, tmp_path / "plain", segment="pre_sealed", symbols=["SYN1"])
    gz = writer.write_run(rows, tmp_path / "gz", segment="pre_sealed", symbols=["SYN1"], compress=True)

    assert gz["artifacts"][0]["sha256"] == plain["artifacts"][0]["sha256"]
    assert gz["artifacts"][0]["sha256"] == writer._sha256_bytes(writer._dump_jsonl(rows))
    # and the stored bytes are separately verifiable
    assert gz["artifacts"][0]["compressed_sha256"] == writer._sha256_bytes(
        (tmp_path / "gz" / "events.jsonl.gz").read_bytes()
    )
    assert gz["artifacts"][0]["compressed_bytes"] < gz["artifacts"][0]["bytes"]


def test_gzip_output_is_byte_identical_across_runs(tmp_path):
    """`gzip.compress` stamps the current time into the header, which would make two identical runs
    produce different artifact bytes -- and byte-identical output across runs is exactly what §8's
    kill switch is for. `mtime=0` is what prevents that, so it is pinned here."""
    rows = _rows_for_compression()
    a = writer._gzip_bytes(writer._dump_jsonl(rows))
    b = writer._gzip_bytes(writer._dump_jsonl(rows))
    assert a == b
    assert a[4:8] == b"\x00\x00\x00\x00", "the gzip header carries an mtime: output is not reproducible"


def test_compression_actually_compresses_and_the_ratio_is_reported(tmp_path):
    rows = _rows_for_compression()
    raw = writer._dump_jsonl(rows)
    blob = writer._gzip_bytes(raw)
    assert len(blob) < len(raw) / 5, f"only {len(raw)/len(blob):.1f}x -- expected the key-name repetition to dominate"


def test_uncompressed_remains_the_default(tmp_path):
    """Nothing changes for an existing caller that does not ask for compression."""
    manifest = writer.write_run(_rows_for_compression(), tmp_path, segment="pre_sealed", symbols=["SYN1"])
    assert (tmp_path / "events.jsonl").is_file()
    assert not (tmp_path / "events.jsonl.gz").exists()
    assert set(manifest["artifacts"][0]) == {"path", "sha256", "row_count"}


# ── RunWriter: the same artifact, without materialising the dataset ─────────────────────────────


def _writer_universe():
    """Real rows grouped by symbol, in the order a streaming caller would see them."""
    from research.charting.events import extraction
    from research.charting.tests._events_helpers import confirmed_rectangle_with_runway

    base = confirmed_rectangle_with_runway(tail_len=40)
    by_symbol = {}
    for i in range(4):
        scaled = base.copy()
        for c in ("open", "high", "low", "close"):
            scaled[c] = scaled[c] * (1.0 + 0.05 * i)
        sym = f"SYM{i:02d}"
        by_symbol[sym] = extraction.extract_events(scaled, sym)
    assert sum(len(v) for v in by_symbol.values()) > 1, "need >1 row for chunking to mean anything"
    return by_symbol


@pytest.mark.parametrize("compress", [False, True])
def test_the_streamed_artifact_is_byte_identical_to_write_run(compress, tmp_path):
    """Including `compressed_sha256`: GzipFile with a fixed mtime and level produces the same bytes
    whether the data arrives in one write or many. Pinned here rather than assumed."""
    by_symbol = _writer_universe()
    rows = [r for sym in sorted(by_symbol) for r in by_symbol[sym]]
    now = datetime(2026, 9, 25, 12, 0, 0, tzinfo=timezone.utc)
    common = dict(segment="pre_sealed", symbols=sorted(by_symbol), now=now, compress=compress)

    # `write_run` is TOLD the rule versions; `RunWriter` harvests them from the chunks, because a
    # streaming caller would otherwise have to walk every row a second time to collect them. The
    # real caller (`study.run.build_segment`) derives them from exactly these rows, so the two
    # agree by construction — this passes them the way it does.
    one_shot = writer.write_run(
        rows, tmp_path / "a",
        cost_rule_versions={r["versioning"]["cost_rule_version"] for r in rows
                            if r["versioning"].get("cost_rule_version")},
        tax_rule_versions={r["versioning"]["tax_rule_version"] for r in rows
                           if r["versioning"].get("tax_rule_version")},
        **common)

    w = writer.RunWriter(tmp_path / "b", **common)
    for sym in sorted(by_symbol):
        w.add(by_symbol[sym])
    streamed = w.finish()

    assert streamed == one_shot, "manifests differ"
    name = "events.jsonl.gz" if compress else "events.jsonl"
    assert (tmp_path / "b" / name).read_bytes() == (tmp_path / "a" / name).read_bytes()
    assert (tmp_path / "b" / "manifest.json").read_text() == (tmp_path / "a" / "manifest.json").read_text()


def test_rule_versions_are_harvested_from_the_chunks(tmp_path):
    """A streaming caller cannot pre-compute the version sets without walking every row twice."""
    by_symbol = _writer_universe()
    rows = [r for sym in sorted(by_symbol) for r in by_symbol[sym]]
    expected = {r["versioning"]["cost_rule_version"] for r in rows
                if r["versioning"].get("cost_rule_version")}
    assert expected, "fixture carries no cost rule version — this gate would be vacuous"

    w = writer.RunWriter(tmp_path / "s", segment="pre_sealed", symbols=sorted(by_symbol))
    for sym in sorted(by_symbol):
        w.add(by_symbol[sym])
    assert set(w.finish()["cost_rule_versions"]) == expected


def test_an_empty_chunk_changes_nothing(tmp_path):
    by_symbol = _writer_universe()
    now = datetime(2026, 9, 25, 12, 0, 0, tzinfo=timezone.utc)
    common = dict(segment="pre_sealed", symbols=sorted(by_symbol), now=now)

    a = writer.RunWriter(tmp_path / "a", **common)
    b = writer.RunWriter(tmp_path / "b", **common)
    for sym in sorted(by_symbol):
        a.add(by_symbol[sym])
        b.add([])
        b.add(by_symbol[sym])
    assert a.finish() == b.finish()


def test_reordered_chunks_produce_a_different_artifact(tmp_path):
    """Order is part of the file, and §8 compares the file. A reordered stream must not quietly
    produce the same hash."""
    by_symbol = _writer_universe()
    syms = sorted(by_symbol)
    now = datetime(2026, 9, 25, 12, 0, 0, tzinfo=timezone.utc)
    common = dict(segment="pre_sealed", symbols=syms, now=now)

    fwd = writer.RunWriter(tmp_path / "f", **common)
    for sym in syms:
        fwd.add(by_symbol[sym])
    rev = writer.RunWriter(tmp_path / "r", **common)
    for sym in reversed(syms):
        rev.add(by_symbol[sym])

    f, r = fwd.finish(), rev.finish()
    assert f["row_count"] == r["row_count"]
    assert f["artifacts"][0]["sha256"] != r["artifacts"][0]["sha256"]


def test_use_after_finish_is_refused(tmp_path):
    w = writer.RunWriter(tmp_path / "x", segment="pre_sealed", symbols=["A"])
    w.finish()
    with pytest.raises(RuntimeError):
        w.add([{"versioning": {}}])
    with pytest.raises(RuntimeError):
        w.finish()
