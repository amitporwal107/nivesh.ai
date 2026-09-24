"""Upload a finished study run to Google Cloud Storage — the study-v2 storage redesign.

`docs/ai_research/CHARTING_STUDY_V2_STORAGE_REDESIGN.md` is the scope. Two levers solve two
different halves of the problem and neither replaces the other:

- **gzip** (`events.writer.write_run(compress=True)`) shrinks the row artefacts ~25x. Measured on
  real pattern-event rows built from real Kite bars: 24.8x at level 6. That is what takes the
  pattern-event tree from TC-113's ≈24 GB to under 1 GB and unblocks the run locally.
- **this module** moves the finished artefacts off the host entirely, so a run is not bounded by the
  9.3 GB of free local disk at all, and the results outlive the VM.

What gzip does NOT fix is the random control: 32 TB of rows at V-3 is still 1.3 TB gzipped, on disk
or in a bucket. That is what the per-seed summaries are for (`study/accumulate.py`).

**Credentials.** This uses Application Default Credentials via `google.cloud.storage`, so no token
is ever read here, passed on a command line, or logged. The host's own service account is the
identity. If ADC is not configured the upload fails loudly with `RemoteStoreError` — it never falls
back to an unauthenticated client and never silently skips the upload, because a study that
reports "uploaded" without uploading is the worst outcome available.

**Verification.** Every object is checked after upload: the bucket's own stored size must match the
bytes sent. `verify_uploaded_run` re-reads the manifests from the bucket and re-checks each
artifact's recorded hash, so "it is in GCS" is a claim backed by a read, not by the absence of an
exception.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional


class RemoteStoreError(RuntimeError):
    """Raised for every failure path. Never swallowed, never downgraded to a warning."""


#: The bucket the project already uses for research artefacts — `research/kite_history/`,
#: `research/tpd_run/` and `research/tpd3_forward/` live beside this one, so a study run under
#: `research/charting_study_v2/` follows the existing convention rather than inventing a location.
DEFAULT_BUCKET = "nidp-raw-niveshdataintelligence"
DEFAULT_PREFIX = "research/charting_study_v2"


@dataclass
class UploadResult:
    bucket: str
    prefix: str
    n_objects: int = 0
    bytes_uploaded: int = 0
    objects: list = field(default_factory=list)   # (relative_path, size, gcs_uri)
    skipped: list = field(default_factory=list)

    @property
    def uri(self) -> str:
        return f"gs://{self.bucket}/{self.prefix}"


def _client():
    try:
        from google.cloud import storage
    except ImportError as exc:                                   # pragma: no cover - env-dependent
        raise RemoteStoreError(
            "google-cloud-storage is not installed; `pip install google-cloud-storage`"
        ) from exc
    try:
        return storage.Client()
    except Exception as exc:
        raise RemoteStoreError(
            "could not create a GCS client from Application Default Credentials. "
            "This does NOT fall back to an anonymous client. Configure ADC (a service account on "
            "the host, or GOOGLE_APPLICATION_CREDENTIALS) and retry."
        ) from exc


def _iter_files(root: Path) -> Iterable[Path]:
    return sorted(p for p in Path(root).rglob("*") if p.is_file())


def upload_run(
    run_dir, *, bucket: str = DEFAULT_BUCKET, prefix: str = DEFAULT_PREFIX, run_id: Optional[str] = None,
    dry_run: bool = False, client=None,
) -> UploadResult:
    """Upload every file under `run_dir` to `gs://<bucket>/<prefix>/<run_id>/<relative path>`.

    `run_id` defaults to the directory's own name, so two runs never overwrite one another. Existing
    objects at the same key ARE overwritten — pass a distinct `run_id` for a fresh destination, the
    same convention `writer.write_run` uses for `out_dir`.

    `dry_run=True` walks and sizes the tree without contacting GCS, which is how a caller checks
    what a run would cost before sending it.
    """
    run_dir = Path(run_dir)
    if not run_dir.is_dir():
        raise RemoteStoreError(f"not a directory: {run_dir}")

    run_id = run_id or run_dir.name
    dest_prefix = f"{prefix.rstrip('/')}/{run_id}"
    result = UploadResult(bucket=bucket, prefix=dest_prefix)

    files = list(_iter_files(run_dir))
    if not files:
        raise RemoteStoreError(f"nothing to upload: {run_dir} contains no files")

    if dry_run:
        for path in files:
            size = path.stat().st_size
            rel = str(path.relative_to(run_dir))
            result.n_objects += 1
            result.bytes_uploaded += size
            result.objects.append((rel, size, f"gs://{bucket}/{dest_prefix}/{rel}"))
        return result

    bkt = (client or _client()).bucket(bucket)
    for path in files:
        rel = str(path.relative_to(run_dir))
        key = f"{dest_prefix}/{rel}"
        blob = bkt.blob(key)
        size = path.stat().st_size
        # `.gz` artefacts are already compressed; marking the encoding would make GCS transparently
        # decompress on read, which would break the byte-for-byte check below and the manifest's own
        # `compressed_sha256`. They are stored as opaque bytes on purpose.
        blob.upload_from_filename(str(path), content_type="application/octet-stream")
        blob.reload()
        if blob.size != size:
            raise RemoteStoreError(
                f"upload verification failed for {key}: sent {size} bytes, bucket reports {blob.size}"
            )
        result.n_objects += 1
        result.bytes_uploaded += size
        result.objects.append((rel, size, f"gs://{bucket}/{key}"))
    return result


def verify_uploaded_run(
    result: UploadResult, *, client=None, check_manifest_hashes: bool = True,
) -> dict:
    """Re-READ what was uploaded and check it, so "it is in GCS" is backed by a read.

    Every object is confirmed to exist at its stored size. With `check_manifest_hashes`, each
    `manifest.json` is downloaded and its artifacts' `sha256` re-verified against the object beside
    it — using `compressed_sha256` for a gzipped artifact, since `sha256` is deliberately the hash of
    the UNCOMPRESSED bytes there (see `events/writer.py`).
    """
    bkt = (client or _client()).bucket(result.bucket)
    checked = {"objects": 0, "manifests": 0, "artifacts": 0, "missing": [], "mismatched": []}

    for rel, size, _uri in result.objects:
        blob = bkt.get_blob(f"{result.prefix}/{rel}")
        if blob is None:
            checked["missing"].append(rel)
            continue
        if blob.size != size:
            checked["mismatched"].append({"path": rel, "expected_bytes": size, "actual_bytes": blob.size})
        checked["objects"] += 1

    if check_manifest_hashes:
        for rel, _size, _uri in result.objects:
            if Path(rel).name != "manifest.json":
                continue
            manifest = json.loads(bkt.blob(f"{result.prefix}/{rel}").download_as_bytes())
            checked["manifests"] += 1
            for artifact in manifest.get("artifacts", []):
                key = f"{result.prefix}/{str(Path(rel).parent / artifact['path'])}"
                blob = bkt.get_blob(key)
                if blob is None:
                    checked["missing"].append(key)
                    continue
                data = blob.download_as_bytes()
                expected = artifact.get("compressed_sha256") or artifact.get("sha256")
                actual = hashlib.sha256(data).hexdigest()
                checked["artifacts"] += 1
                if expected != actual:
                    checked["mismatched"].append({"path": key, "expected_sha256": expected, "actual_sha256": actual})

    checked["passed"] = not checked["missing"] and not checked["mismatched"]
    return checked
