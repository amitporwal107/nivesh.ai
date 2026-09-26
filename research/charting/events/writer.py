"""Hashed, immutable run-folder writer for the historical pattern event dataset -- task item 7.
Mirrors `research.charting.replay.write_run`'s manifest convention (sha256 per artifact, a
content/config vs. run-metadata split so `manifest.json`'s wall-clock fields never affect the
hashed content) so a reader of either package's `runs/` output recognises the same shape.

Format: JSONL, not CSV/parquet (task item 7 allows either). Chosen over CSV because each row
carries a genuinely nested structure (per-horizon outcomes, per-horizon x per-scenario cost
breakdowns) -- flattening that to CSV columns would mean ~350+ columns
(5 horizons x (4 sensitivity scenarios + 1 liquidity-bucket model) x ~20 cost fields, plus the
outcome fields) for little benefit over one JSON object per line, which every consumer touching
this dataset (a notebook, pandas' own `read_json(lines=True)`, or a future SQL loader) can
already read natively.

`research/charting/runs/` is the default base for `out_dir` (gitignored -- see `.gitignore`);
this module never assumes that specific location, it only writes wherever `out_dir` points.
"""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import math
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

from research.charting.config import CONFIG, ENGINE_VERSION, PROFILE_NAME, config_hash
from research.charting.events.schema import EVENTS_SCHEMA_VERSION

DEFAULT_RUNS_DIR = Path(__file__).resolve().parents[1] / "runs"


def _json_default(obj):
    if is_dataclass(obj):
        return asdict(obj)
    raise TypeError(f"object of type {type(obj)!r} is not JSON serialisable")


def _finite_or_none(x):
    """Strict JSON has no NaN/Infinity (e.g. liquidity.participation_ratio is inf for a zero-ADV
    instrument, by that module's contract): written as null, with the row's own fields (adv_inr_at_t)
    still showing why."""
    if isinstance(x, float) and not math.isfinite(x):
        return None
    if isinstance(x, dict):
        return {k: _finite_or_none(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_finite_or_none(v) for v in x]
    return x


def _dump_jsonl(rows: Sequence[dict]) -> bytes:
    """One JSON object per line, keys sorted WITHIN each row (matching replay.py's `_dump`
    `sort_keys=True` convention for reproducibility) -- row ORDER itself is preserved exactly
    as given (the caller's own deterministic per-symbol, per-replay generation order), never
    re-sorted here."""
    lines = [json.dumps(_finite_or_none(json.loads(json.dumps(row, default=_json_default))), sort_keys=True,
                        allow_nan=False) for row in rows]
    return ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


#: gzip level for `compress=True`. Measured on real pattern-event rows built from real Kite bars
#: (496 rows, 33.0 MB): -1 gives 15.9x at 379 MB/s, -6 gives 24.8x at 124 MB/s, -9 gives 26.0x at
#: 63 MB/s. -6 is the knee: -9 buys 4% more for half the speed. The rows compress this well because
#: every line repeats the same ~350 key names, which is a structural property of the format rather
#: than of any particular dataset -- so the ratio should hold at scale rather than decay.
GZIP_LEVEL = 6


def _gzip_bytes(data: bytes, level: int = GZIP_LEVEL) -> bytes:
    """Deterministic gzip: `mtime=0` and a fixed filename, so the same rows always produce the same
    BYTES. `gzip.compress` stamps the current time into the header, which would make every artifact
    hash differ between two otherwise identical runs -- and byte-identical output across runs is
    exactly what §8's kill switch checks.
    """
    buf = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", compresslevel=level, fileobj=buf, mtime=0) as f:
        f.write(data)
    return buf.getvalue()


class RunWriter:
    """`write_run`, fed a chunk at a time — the same files, the same manifest, the same hashes.

    WHY
    ---
    `write_run` builds `_dump_jsonl(rows)` for the WHOLE dataset before writing a byte, so
    publishing a segment costs the rows plus a full serialised copy of them, on top of whatever the
    caller is still holding. That is the last place a v2 study run materialises everything at once.

    Both hashes survive chunking. The uncompressed sha256 is over `"\n".join(lines) + "\n"`, whose
    bytes for a whole list are exactly its chunks' bytes concatenated. The compressed one survives
    because `GzipFile` with a fixed `mtime`/level produces identical output whether the data arrives
    in one `write` or many, provided nothing flushes in between — pinned by
    `tests/test_events_writer.py`, not assumed.

    ORDER IS PART OF THE ARTIFACT. Chunks must arrive in the order `write_run` would have received
    them, or the file differs and §8's kill switch reads it as a reproducibility failure.

    Usage is `add(...)` per chunk then `finish()`, which returns the manifest `write_run` returns.
    """

    __slots__ = ("out_dir", "_segment", "_symbols", "_cfg", "_cost_versions", "_tax_versions",
                 "_now", "_compress", "_sha", "_rows", "_raw_bytes", "_fh", "_gz", "_finished")

    def __init__(self, out_dir, *, segment: str, symbols: Sequence[str], cfg: dict = CONFIG,
                 cost_rule_versions: Optional[Sequence[str]] = None,
                 tax_rule_versions: Optional[Sequence[str]] = None,
                 now: Optional[datetime] = None, compress: bool = False):
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self._segment, self._symbols, self._cfg = segment, symbols, cfg
        self._cost_versions = set(cost_rule_versions or ())
        self._tax_versions = set(tax_rule_versions or ())
        self._now, self._compress = now, compress
        self._sha = hashlib.sha256()
        self._rows = 0
        self._raw_bytes = 0
        self._finished = False

        path = self.out_dir / ("events.jsonl.gz" if compress else "events.jsonl")
        self._fh = open(path, "wb")
        self._gz = (gzip.GzipFile(filename="", mode="wb", compresslevel=GZIP_LEVEL,
                                  fileobj=self._fh, mtime=0) if compress else None)

    def add(self, rows: Sequence[dict]) -> "RunWriter":
        """Append one chunk — typically one symbol's rows — in run order.

        Rule versions are harvested here rather than demanded up front, so a streaming caller does
        not have to walk every row a second time to collect them.
        """
        if self._finished:
            raise RuntimeError("RunWriter.add after finish()")
        if not rows:
            return self                          # `_dump_jsonl([])` is b"": a real no-op
        content = _dump_jsonl(rows)
        self._sha.update(content)
        self._raw_bytes += len(content)
        self._rows += len(rows)
        (self._gz or self._fh).write(content)
        for row in rows:
            versioning = row.get("versioning") or {}
            if versioning.get("cost_rule_version"):
                self._cost_versions.add(versioning["cost_rule_version"])
            if versioning.get("tax_rule_version"):
                self._tax_versions.add(versioning["tax_rule_version"])
        return self

    def finish(self) -> dict:
        """Close the artifact and write `manifest.json`. Returns the manifest, as `write_run` does."""
        if self._finished:
            raise RuntimeError("RunWriter.finish called twice")
        self._finished = True
        if self._gz is not None:
            self._gz.close()
        self._fh.close()

        sha = self._sha.hexdigest()
        if self._compress:
            stored = (self.out_dir / "events.jsonl.gz").read_bytes()
            artifact = {
                "path": "events.jsonl.gz", "sha256": sha, "row_count": self._rows,
                "compression": "gzip", "compressed_sha256": _sha256_bytes(stored),
                "bytes": self._raw_bytes, "compressed_bytes": len(stored),
            }
        else:
            artifact = {"path": "events.jsonl", "sha256": sha, "row_count": self._rows}

        now = self._now or datetime.now(timezone.utc)
        manifest = {
            "schema_version": EVENTS_SCHEMA_VERSION,
            "run_id": f"events_{self._segment}_{now.strftime('%Y%m%dT%H%M%SZ')}",
            "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "engine_version": ENGINE_VERSION,
            "profile": PROFILE_NAME,
            "config_hash": config_hash(self._cfg),
            "segment": self._segment,
            "symbols": sorted(self._symbols),
            "row_count": self._rows,
            "cost_rule_versions": sorted(self._cost_versions),
            "tax_rule_versions": sorted(self._tax_versions),
            "artifacts": [artifact],
        }
        (self.out_dir / "manifest.json").write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
        return manifest


def write_run(
    rows: Sequence[dict], out_dir, *, segment: str, symbols: Sequence[str], cfg: dict = CONFIG,
    cost_rule_versions: Optional[Sequence[str]] = None, tax_rule_versions: Optional[Sequence[str]] = None,
    now: Optional[datetime] = None, compress: bool = False,
) -> dict:
    """Write `rows` (already-built event/control rows, any of `extraction`/`controls`' output)
    to `out_dir/events.jsonl`, plus `manifest.json` recording the artifact's SHA-256, the row
    count, every config/cost/tax rule version in force, and the S35 dev segment this run
    belongs to. Returns the manifest dict actually written. `out_dir` is created if missing;
    an existing file at that path is OVERWRITTEN (the "immutable" guarantee is about the
    manifest's own content-hash, not about the directory path being single-use -- callers that
    want a fresh path per run should pass a fresh `out_dir`, e.g. one that embeds `now`).

    `compress=True` writes `events.jsonl.gz` instead (measured 24.8x on real rows). The manifest's
    `sha256` still hashes the UNCOMPRESSED bytes either way, so a manifest written before and after
    this option existed compares identically and §8's kill switch is untouched; `compressed_sha256`
    records the stored bytes separately. Reading it back is `gzip.open(path, "rt")` -- and pandas'
    `read_json(lines=True)` handles `.gz` natively, so the format note above still holds.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    content = _dump_jsonl(rows)
    sha = _sha256_bytes(content)
    if compress:
        # `sha256` stays the hash of the UNCOMPRESSED bytes. That is deliberate: it is the value
        # §8's kill switch compares (`integrity.kill_switch_check` hashes `_dump_jsonl(rows)` in
        # memory, never a file), and it must not change meaning because the artifact on disk is now
        # compressed. The compressed file's own hash is recorded separately, so the stored bytes are
        # verifiable too.
        blob = _gzip_bytes(content)
        artifact_path = "events.jsonl.gz"
        (out_dir / artifact_path).write_bytes(blob)
        artifact = {
            "path": artifact_path, "sha256": sha, "row_count": len(rows),
            "compression": "gzip", "compressed_sha256": _sha256_bytes(blob),
            "bytes": len(content), "compressed_bytes": len(blob),
        }
    else:
        artifact_path = "events.jsonl"
        (out_dir / artifact_path).write_bytes(content)
        artifact = {"path": artifact_path, "sha256": sha, "row_count": len(rows)}

    now = now or datetime.now(timezone.utc)
    manifest = {
        "schema_version": EVENTS_SCHEMA_VERSION,
        "run_id": f"events_{segment}_{now.strftime('%Y%m%dT%H%M%SZ')}",
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "engine_version": ENGINE_VERSION,
        "profile": PROFILE_NAME,
        "config_hash": config_hash(cfg),
        "segment": segment,
        "symbols": sorted(symbols),
        "row_count": len(rows),
        "cost_rule_versions": sorted(set(cost_rule_versions)) if cost_rule_versions else [],
        "tax_rule_versions": sorted(set(tax_rule_versions)) if tax_rule_versions else [],
        "artifacts": [artifact],
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
    return manifest
