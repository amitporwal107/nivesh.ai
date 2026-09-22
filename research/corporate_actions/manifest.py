"""Shared helpers for research/corporate_actions: sha256 file hashing and manifest.json
read/merge/write -- mirrors research/index_history/manifest.py's shape (source, files,
generated_at) but for this package's own data files and sources instead of one fixed
Kite index source. There is no sealed-out-of-sample-window concept here: that rule
(research/index_history/manifest.py, research/charting/research_window.py) governs
whether a RESEARCH EVALUATION may use a date range, an orthogonal concern to whether a
demerger happened on a given date. See research/corporate_actions/__init__.py.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def sha256_file(path) -> str:
    """Hex sha256 digest of a file's exact bytes on disk."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _empty_manifest() -> dict:
    return {"generated_at": None, "sources": {}, "files": {}}


def load_manifest(path) -> dict:
    """Load manifest.json, or a fresh empty structure if it does not exist yet."""
    p = Path(path)
    if not p.exists():
        return _empty_manifest()
    data = json.loads(p.read_text())
    data.setdefault("generated_at", None)
    data.setdefault("sources", {})
    data.setdefault("files", {})
    return data


def upsert_file_entry(manifest: dict, filename: str, entry: dict) -> dict:
    """Add/replace one file's entry in-place (sha256 + row_count etc); returns the
    manifest for chaining."""
    manifest.setdefault("files", {})[filename] = entry
    return manifest


def upsert_source_entry(manifest: dict, source_key: str, entry: dict) -> dict:
    """Add/replace one source's provenance entry in-place (name, reference, retrieved_at,
    what it was used for); returns the manifest for chaining."""
    manifest.setdefault("sources", {})[source_key] = entry
    return manifest


def save_manifest(path, manifest: dict, generated_at: str) -> None:
    """Write manifest.json (sorted keys, trailing newline). Never include any credential --
    this manifest only ever holds file hashes, row counts, dates and public source URLs."""
    manifest = dict(manifest)
    manifest["generated_at"] = generated_at
    manifest.setdefault("sources", {})
    manifest.setdefault("files", {})
    Path(path).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
