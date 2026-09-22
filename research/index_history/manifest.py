"""Shared helpers for research/index_history: the sealed out-of-sample window, sha256
file hashing, and manifest.json read/merge/write.

Sealed window: 2023-01-01 .. 2024-07-31 (inclusive) is a reserved out-of-sample research
period (see forward-test/sealed-test program). No data file this package writes may
contain a row dated inside it. `assert_no_sealed_dates` is the enforcement point — call
it on every set of dates immediately before writing to disk.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Iterable

SEALED_START = date(2023, 1, 1)
SEALED_END = date(2024, 7, 31)
SEALED_WINDOW = (SEALED_START.isoformat(), SEALED_END.isoformat())

SOURCE = "kite-connect-v3"
INTERVAL = "day"


def _as_date(d) -> date:
    """Accept a date object or an ISO-ish string ('YYYY-MM-DD', optionally with a time
    suffix such as 'YYYY-MM-DD HH:MM:SS+05:30') and return a plain date."""
    if isinstance(d, date):
        return d
    return date.fromisoformat(str(d)[:10])


def is_sealed(d) -> bool:
    """True if `d` (date object or ISO-ish string) falls inside the sealed window,
    inclusive of both ends."""
    dd = _as_date(d)
    return SEALED_START <= dd <= SEALED_END


def assert_no_sealed_dates(dates: Iterable) -> None:
    """Raise ValueError naming the first offending date if any date in `dates` falls
    inside the sealed window. Call this right before writing any CSV to disk."""
    for d in dates:
        if is_sealed(d):
            raise ValueError(
                f"sealed out-of-sample date {d} falls inside "
                f"{SEALED_START.isoformat()}..{SEALED_END.isoformat()} and must not be "
                "fetched or stored"
            )


def sha256_file(path) -> str:
    """Hex sha256 digest of a file's exact bytes on disk."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _empty_manifest() -> dict:
    return {
        "source": SOURCE,
        "interval": INTERVAL,
        "excluded_window": list(SEALED_WINDOW),
        "generated_at": None,
        "files": {},
    }


def load_manifest(path) -> dict:
    """Load manifest.json, or a fresh empty structure if it does not exist yet."""
    p = Path(path)
    if not p.exists():
        return _empty_manifest()
    data = json.loads(p.read_text())
    data.setdefault("source", SOURCE)
    data.setdefault("interval", INTERVAL)
    data.setdefault("excluded_window", list(SEALED_WINDOW))
    data.setdefault("files", {})
    return data


def upsert_entry(manifest: dict, filename: str, entry: dict) -> dict:
    """Add/replace one file's entry in-place; returns the manifest for chaining."""
    manifest.setdefault("files", {})[filename] = entry
    return manifest


def save_manifest(path, manifest: dict, generated_at: str) -> None:
    """Write manifest.json (sorted keys, trailing newline). Never include any
    credential — this manifest only ever holds row counts, dates and hashes."""
    manifest = dict(manifest)
    manifest["generated_at"] = generated_at
    manifest.setdefault("source", SOURCE)
    manifest.setdefault("interval", INTERVAL)
    manifest.setdefault("excluded_window", list(SEALED_WINDOW))
    Path(path).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
