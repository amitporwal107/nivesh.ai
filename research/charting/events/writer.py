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

import hashlib
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


def write_run(
    rows: Sequence[dict], out_dir, *, segment: str, symbols: Sequence[str], cfg: dict = CONFIG,
    cost_rule_versions: Optional[Sequence[str]] = None, tax_rule_versions: Optional[Sequence[str]] = None,
    now: Optional[datetime] = None,
) -> dict:
    """Write `rows` (already-built event/control rows, any of `extraction`/`controls`' output)
    to `out_dir/events.jsonl`, plus `manifest.json` recording the artifact's SHA-256, the row
    count, every config/cost/tax rule version in force, and the S35 dev segment this run
    belongs to. Returns the manifest dict actually written. `out_dir` is created if missing;
    an existing file at that path is OVERWRITTEN (the "immutable" guarantee is about the
    manifest's own content-hash, not about the directory path being single-use -- callers that
    want a fresh path per run should pass a fresh `out_dir`, e.g. one that embeds `now`).
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    content = _dump_jsonl(rows)
    (out_dir / "events.jsonl").write_bytes(content)
    sha = _sha256_bytes(content)

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
        "artifacts": [{"path": "events.jsonl", "sha256": sha, "row_count": len(rows)}],
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
    return manifest
