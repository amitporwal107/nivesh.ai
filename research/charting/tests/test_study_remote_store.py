"""`study/remote_store.py` + the gzip artifact path end to end.

The GCS calls are exercised against a fake bucket rather than the real one: a unit test must not
depend on network, credentials or a bucket's current contents. The REAL upload is proved separately,
by an actual run against `gs://nidp-raw-niveshdataintelligence`, and its output is pasted in
`test_reports/charting_study_v2_gzip_gcs.md` — a fake alone would only prove the code calls the
methods it calls.
"""
from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path

import pytest

from research.charting.study import execute, remote_store
from research.charting.tests.test_study_execute import (
    _mixed_segment_universe, _write_etf_list, _write_kite_dir,
)


# ── a minimal in-memory stand-in for the bits of google-cloud-storage this module uses ──────────

class _FakeBlob:
    def __init__(self, store: dict, key: str):
        self._store, self.name, self.size = store, key, None

    def upload_from_filename(self, filename, content_type=None):
        self._store[self.name] = Path(filename).read_bytes()

    def reload(self):
        self.size = len(self._store[self.name]) if self.name in self._store else None

    def download_as_bytes(self):
        return self._store[self.name]


class _FakeBucket:
    def __init__(self, store: dict):
        self._store = store

    def blob(self, key):
        return _FakeBlob(self._store, key)

    def get_blob(self, key):
        if key not in self._store:
            return None
        b = _FakeBlob(self._store, key)
        b.reload()
        return b


class _FakeClient:
    def __init__(self):
        self.store: dict = {}

    def bucket(self, name):
        return _FakeBucket(self.store)


@pytest.fixture(scope="module")
def gz_run(tmp_path_factory):
    """A real study run with BOTH levers on: summarised controls and gzipped row artefacts."""
    setup = tmp_path_factory.mktemp("inputs")
    out = tmp_path_factory.mktemp("run") / "study_gz"
    result = execute.execute_study(
        out, kite_dir=_write_kite_dir(setup), etf_list_path=_write_etf_list(setup),
        bars_by_symbol=_mixed_segment_universe(), kill_switch=False, recompute_sample_size=5,
        random_control_seeds=(0, 1, 2), summarise_controls=True, compress_events=True,
    )
    assert result["status"] == "COMPLETE", result["status"]
    return out, result


# ── gzip artefacts inside a real run ────────────────────────────────────────────────────────────

def test_the_run_writes_gzipped_events_and_no_plain_jsonl(gz_run):
    out, _ = gz_run
    assert list(out.glob("*/events.jsonl.gz")), "no compressed pattern events were written"
    assert not list(out.glob("*/events.jsonl")), "an uncompressed copy was left behind"


def test_the_gzipped_events_read_back_as_the_rows_the_manifest_counts(gz_run):
    out, _ = gz_run
    for gz_path in out.glob("*/events.jsonl.gz"):
        manifest = json.loads((gz_path.parent / "manifest.json").read_text())
        artifact = manifest["artifacts"][0]
        assert artifact["path"] == "events.jsonl.gz" and artifact["compression"] == "gzip"

        rows = [json.loads(line) for line in gzip.open(gz_path, "rt", encoding="utf-8")]
        assert len(rows) == artifact["row_count"] == manifest["row_count"]
        # the recorded uncompressed hash really is the hash of what decompresses out
        raw = gzip.open(gz_path, "rb").read()
        assert hashlib.sha256(raw).hexdigest() == artifact["sha256"]
        assert hashlib.sha256(gz_path.read_bytes()).hexdigest() == artifact["compressed_sha256"]
        assert artifact["compressed_bytes"] < artifact["bytes"]


def test_the_manifest_records_that_the_run_was_compressed(gz_run):
    _, result = gz_run
    assert result["study_manifest"]["control_output"]["compressed"] is True


# ── upload ──────────────────────────────────────────────────────────────────────────────────────

def test_dry_run_sizes_the_tree_without_touching_gcs(gz_run):
    out, _ = gz_run
    res = remote_store.upload_run(out, dry_run=True, run_id="dry")
    assert res.n_objects > 0 and res.bytes_uploaded > 0
    assert all(u.startswith("gs://") for _rel, _sz, u in res.objects)
    assert res.uri.endswith("/dry")


def test_upload_then_verify_passes_against_a_fake_bucket(gz_run):
    out, _ = gz_run
    client = _FakeClient()
    res = remote_store.upload_run(out, run_id="r1", client=client)
    assert res.n_objects == len(list(p for p in out.rglob("*") if p.is_file()))

    checked = remote_store.verify_uploaded_run(res, client=client)
    assert checked["passed"] is True
    assert checked["objects"] == res.n_objects
    assert checked["manifests"] > 0 and checked["artifacts"] > 0
    assert checked["missing"] == [] and checked["mismatched"] == []


def test_verification_catches_a_corrupted_object(gz_run):
    """Negative control: verification that cannot fail proves nothing."""
    out, _ = gz_run
    client = _FakeClient()
    res = remote_store.upload_run(out, run_id="r2", client=client)

    key = next(k for k in client.store if k.endswith("events.jsonl.gz"))
    client.store[key] = client.store[key] + b"corrupted"

    checked = remote_store.verify_uploaded_run(res, client=client)
    assert checked["passed"] is False
    assert checked["mismatched"], "a corrupted artifact passed verification"


def test_verification_catches_a_missing_object(gz_run):
    out, _ = gz_run
    client = _FakeClient()
    res = remote_store.upload_run(out, run_id="r3", client=client)
    del client.store[next(k for k in client.store if k.endswith("events.jsonl.gz"))]

    checked = remote_store.verify_uploaded_run(res, client=client)
    assert checked["passed"] is False
    assert checked["missing"]


def test_an_empty_directory_is_an_error_not_a_silent_success(tmp_path):
    (tmp_path / "empty").mkdir()
    with pytest.raises(remote_store.RemoteStoreError, match="no files"):
        remote_store.upload_run(tmp_path / "empty", dry_run=True)


def test_a_missing_directory_is_an_error(tmp_path):
    with pytest.raises(remote_store.RemoteStoreError, match="not a directory"):
        remote_store.upload_run(tmp_path / "nope", dry_run=True)


def test_execute_study_raises_rather_than_reporting_an_unverified_upload(gz_run, monkeypatch):
    """A run that says "uploaded" without uploading is the worst outcome available, so a failed
    verification must raise out of `execute_study` rather than be reported as a warning."""
    out, _ = gz_run
    monkeypatch.setattr(remote_store, "upload_run", lambda *a, **k: remote_store.UploadResult(
        bucket="b", prefix="p", n_objects=1, bytes_uploaded=1, objects=[("x", 1, "gs://b/p/x")]))
    monkeypatch.setattr(remote_store, "verify_uploaded_run",
                        lambda *a, **k: {"passed": False, "missing": ["x"], "mismatched": []})
    setup = out.parent
    with pytest.raises(remote_store.RemoteStoreError, match="failed verification"):
        execute.execute_study(
            out.parent / "study2", kite_dir=_write_kite_dir(setup), etf_list_path=_write_etf_list(setup),
            bars_by_symbol=_mixed_segment_universe(), kill_switch=False, recompute_sample_size=5,
            random_control_seeds=(0,), upload_to="research/_test",
        )
