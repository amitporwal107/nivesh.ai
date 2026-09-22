"""Synthetic-only: manifest.json round-trips a per-file entry, and the recorded sha256
matches the actual bytes of the file on disk (catches a stale hash after a rewrite)."""
import hashlib
import json

from research.index_history.manifest import (
    load_manifest, save_manifest, sha256_file, upsert_entry,
)


def test_sha256_file_matches_hashlib_reference(tmp_path):
    p = tmp_path / "sample.csv"
    p.write_bytes(b"date,close\n2024-08-01,100.0\n2024-08-02,101.5\n")
    expected = hashlib.sha256(p.read_bytes()).hexdigest()
    assert sha256_file(p) == expected


def test_sha256_changes_when_file_content_changes(tmp_path):
    p = tmp_path / "sample.csv"
    p.write_bytes(b"a,b\n1,2\n")
    first = sha256_file(p)
    p.write_bytes(b"a,b\n1,2\n3,4\n")
    second = sha256_file(p)
    assert first != second


def test_manifest_round_trip_and_entry_sha256_matches_file_bytes(tmp_path):
    csv_path = tmp_path / "NIFTY_50.csv"
    csv_path.write_bytes(b"date,open,high,low,close,volume\n2024-08-01,100,101,99,100.5,0\n")
    manifest_path = tmp_path / "manifest.json"

    manifest = load_manifest(manifest_path)  # no file yet -> fresh empty structure
    assert manifest["files"] == {}
    assert manifest["source"] == "kite-connect-v3"
    assert manifest["interval"] == "day"
    assert manifest["excluded_window"] == ["2023-01-01", "2024-07-31"]

    entry = {
        "index_name": "NIFTY 50",
        "instrument_token": 256265,
        "rows": 1,
        "first_date": "2024-08-01",
        "last_date": "2024-08-01",
        "sha256": sha256_file(csv_path),
    }
    manifest = upsert_entry(manifest, "NIFTY_50.csv", entry)
    save_manifest(manifest_path, manifest, generated_at="2026-09-22T00:00:00+00:00")

    reloaded = json.loads(manifest_path.read_text())
    assert reloaded["files"]["NIFTY_50.csv"]["sha256"] == hashlib.sha256(csv_path.read_bytes()).hexdigest()
    assert reloaded["generated_at"] == "2026-09-22T00:00:00+00:00"


def test_manifest_entry_sha256_is_wrong_if_file_edited_after_recording(tmp_path):
    csv_path = tmp_path / "INDIA_VIX.csv"
    csv_path.write_bytes(b"date,open,high,low,close,volume\n2024-08-01,14.0,14.5,13.8,14.1,0\n")
    recorded_sha = sha256_file(csv_path)

    # simulate the file being silently rewritten after the manifest was recorded
    csv_path.write_bytes(b"date,open,high,low,close,volume\n2024-08-01,99.0,99.0,99.0,99.0,0\n")

    assert sha256_file(csv_path) != recorded_sha  # the staleness this check exists to catch
