"""Committed chart snapshot loader — research/charting/export.py WRITES this
(backend/services/research_chart_snapshot/manifest.json + symbols/<SYMBOL>.json.gz);
backend/routes/research_chart.py READS it through this module. Nothing is computed here and
nothing else is read: no DB, no network, no other file (research/charting/SNAPSHOT_SCHEMA.md, the
Sim Lab rule — see services/sim_lab.py). A missing, unreadable, schema-invalid, or hash-mismatched
manifest or symbol file returns None so the routes answer 503, never a partial response.

Two-tier cache, both keyed on (path, mtime_ns, size) like services/sim_lab.py:
  - the manifest is small and read on every route, so it's cached whole;
  - each symbol payload is its own gzip file and can be tens of KB, so it's parsed lazily (only
    when a route actually asks for that symbol) and cached per-symbol. A stale in-memory copy is
    detected the same way sim_lab does — a re-exported file changes mtime/size, so the next
    request re-reads and re-validates it.

Every symbol payload is checked against the manifest's OWN recorded sha256 of that file (not just
"does it parse") before being trusted — export.py's determinism promise (same input -> same bytes)
only has teeth if something on the read side actually verifies it.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

SNAPSHOT_DIR = Path(__file__).with_name("research_chart_snapshot")
MANIFEST_PATH = SNAPSHOT_DIR / "manifest.json"
SCHEMA_VERSION = 1

SHA256 = re.compile(r"[0-9a-f]{64}")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
SYMBOL_RE = re.compile(r"^[A-Z0-9&\-]{1,32}$")
ADJUSTMENT_STATUSES = frozenset({"ADJUSTED", "UNADJUSTED", "UNVERIFIED", "ADJUSTED_SPLITS_BONUS_ONLY"})
DATA_QUALITY_STATUSES = frozenset({"VALID", "PARTIAL", "STALE", "INVALID", "BLOCKED"})
PIT_STATUSES = frozenset({"PIT_VALIDATED", "PIT_UNVERIFIED", "PIT_BLOCKED"})

_MANIFEST_SYMBOL_KEYS = ("symbol", "n_bars", "first_date", "last_date", "data_quality_status",
                         "pit_status", "file", "sha256", "n_patterns")

# One parsed manifest per (path, mtime, size) — re-exported files change mtime/size, so a fresh
# export is picked up on the very next request (same convention as services/sim_lab.py).
_manifest_cache: dict = {"key": None, "data": None}
# One parsed payload per symbol, each independently keyed on its OWN file's (path, mtime, size).
_symbol_cache: dict = {}


# ---------------------------------------------------------------------------
# Manifest validation + load
# ---------------------------------------------------------------------------

def _valid_manifest(d: dict) -> bool:
    """The shape research_chart.py and its routes rely on. Anything else is a 503, never a
    partially rendered page (SNAPSHOT_SCHEMA.md)."""
    if d.get("schema_version") != SCHEMA_VERSION:
        return False
    if d.get("fixture") is not None and not isinstance(d.get("fixture"), bool):
        return False
    for k in ("run_id", "generated_at", "engine_version", "profile", "universe_rule"):
        if not isinstance(d.get(k), str) or not d[k]:
            return False
    if not SHA256.fullmatch(str(d.get("config_hash", ""))):
        return False

    source = d.get("source")
    if not isinstance(source, dict):
        return False
    for k in ("provider", "series", "adjustment_status", "last_bar_date"):
        if not isinstance(source.get(k), str) or not source[k]:
            return False
    if source["adjustment_status"] not in ADJUSTMENT_STATUSES:
        return False
    if not DATE.fullmatch(source["last_bar_date"]):
        return False
    files = source.get("files")
    if not isinstance(files, list) or not all(
        isinstance(f, dict) and isinstance(f.get("name"), str) and SHA256.fullmatch(str(f.get("sha256", "")))
        for f in files
    ):
        return False

    symbols = d.get("symbols")
    if not isinstance(symbols, list) or not symbols:
        return False
    seen = set()
    for e in symbols:
        if not isinstance(e, dict) or not all(k in e for k in _MANIFEST_SYMBOL_KEYS):
            return False
        if not SYMBOL_RE.fullmatch(str(e["symbol"])) or e["symbol"] in seen:
            return False
        seen.add(e["symbol"])
        if not isinstance(e["n_bars"], int) or e["n_bars"] < 0:
            return False
        if not DATE.fullmatch(str(e["first_date"])) or not DATE.fullmatch(str(e["last_date"])):
            return False
        if e["data_quality_status"] not in DATA_QUALITY_STATUSES:
            return False
        if e["pit_status"] not in PIT_STATUSES:
            return False
        if not isinstance(e["file"], str) or not e["file"]:
            return False
        if not SHA256.fullmatch(str(e["sha256"])):
            return False
        if not isinstance(e["n_patterns"], int) or e["n_patterns"] < 0:
            return False
    return True


def load_manifest(path: Optional[Path] = None) -> Optional[dict]:
    """The validated manifest, or None (-> the routes answer 503 snapshot_unavailable).

    `path` defaults to the CURRENT value of the module-level MANIFEST_PATH, resolved at call
    time, not import time -- a plain `path: Path = MANIFEST_PATH` default would bind the
    original path into the function object once at module import, so monkeypatching
    MANIFEST_PATH afterwards (as tests do, to point at a temp snapshot) would silently have no
    effect. This mirrors how SNAPSHOT_DIR is already read as a bare global inside load_symbol().
    """
    if path is None:
        path = MANIFEST_PATH
    try:
        stat = path.stat()
    except OSError as e:
        logger.warning("chart snapshot manifest missing (%s): %s", path, e)
        return None
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    if _manifest_cache["key"] == key:
        return _manifest_cache["data"]
    try:
        d = json.loads(path.read_text())
    except (OSError, ValueError) as e:
        logger.warning("chart snapshot manifest unreadable (%s): %s", path, e)
        return None
    if not isinstance(d, dict) or not _valid_manifest(d):
        logger.warning("chart snapshot manifest failed validation (%s)", path)
        return None
    _manifest_cache["key"], _manifest_cache["data"] = key, d
    return d


def _manifest_symbol_entry(manifest: dict, symbol: str) -> Optional[dict]:
    for e in manifest["symbols"]:
        if e["symbol"] == symbol:
            return e
    return None


# ---------------------------------------------------------------------------
# Per-symbol payload validation + load
# ---------------------------------------------------------------------------

def _valid_bar_row(row) -> bool:
    return (isinstance(row, list) and len(row) == 6 and isinstance(row[0], str) and DATE.fullmatch(row[0])
            and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in row[1:]))


def _valid_finding(f) -> bool:
    return isinstance(f, dict) and isinstance(f.get("rule_id"), str) and "date" in f and "observed" in f


def _valid_indicator(v) -> bool:
    if not isinstance(v, dict):
        return False
    contract = v.get("contract")
    if not isinstance(contract, dict) or not isinstance(contract.get("indicator_id"), str):
        return False
    if "pane" not in v or not isinstance(v.get("values"), list):
        return False
    return all(isinstance(row, list) and len(row) >= 2 and isinstance(row[0], str) for row in v["values"])


def _valid_symbol_payload(symbol: str, d: dict) -> bool:
    if d.get("symbol") != symbol:
        return False
    bars = d.get("bars")
    if not isinstance(bars, list) or not all(_valid_bar_row(r) for r in bars):
        return False
    if d.get("data_quality_status") not in DATA_QUALITY_STATUSES:
        return False
    if d.get("pit_status") not in PIT_STATUSES:
        return False
    findings = d.get("findings")
    if not isinstance(findings, list) or not all(_valid_finding(f) for f in findings):
        return False
    indicators = d.get("indicators")
    if not isinstance(indicators, dict) or not all(_valid_indicator(v) for v in indicators.values()):
        return False
    if not isinstance(d.get("patterns"), list):
        return False
    return True


def load_symbol(symbol: str) -> Optional[dict]:
    """Validated payload for one symbol: its file must exist, its bytes must hash to the sha256
    the manifest recorded for it, and its parsed shape must be valid. None on any of that failing
    (never a partial/best-effort payload) -- the routes answer 503, the SAME as a whole-manifest
    failure, because a symbol the manifest itself lists is a snapshot-integrity problem, not a
    404 (that's reserved for a symbol the manifest never listed at all)."""
    manifest = load_manifest()
    if manifest is None:
        return None
    entry = _manifest_symbol_entry(manifest, symbol)
    if entry is None:
        return None
    path = SNAPSHOT_DIR / entry["file"]
    try:
        stat = path.stat()
    except OSError as e:
        logger.warning("chart snapshot symbol file missing (%s, %s): %s", symbol, path, e)
        return None
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    cached = _symbol_cache.get(symbol)
    if cached and cached["key"] == key:
        return cached["data"]
    try:
        raw = path.read_bytes()
    except OSError as e:
        logger.warning("chart snapshot symbol file unreadable (%s, %s): %s", symbol, path, e)
        return None
    digest = hashlib.sha256(raw).hexdigest()
    if digest != entry["sha256"]:
        logger.warning("chart snapshot symbol file sha256 mismatch (%s): manifest=%s actual=%s",
                       symbol, entry["sha256"], digest)
        return None
    try:
        d = json.loads(gzip.decompress(raw))
    except (OSError, ValueError) as e:
        logger.warning("chart snapshot symbol file unparseable (%s, %s): %s", symbol, path, e)
        return None
    if not isinstance(d, dict) or not _valid_symbol_payload(symbol, d):
        logger.warning("chart snapshot symbol payload failed validation (%s)", symbol)
        return None
    _symbol_cache[symbol] = {"key": key, "data": d}
    return d


# ---------------------------------------------------------------------------
# Route-facing views
# ---------------------------------------------------------------------------

def manifest_view(manifest: dict) -> dict:
    """GET /run: the manifest minus per-file integrity hashes (source.files[].sha256 and
    symbols[].sha256 are for this module's own use, not an API concern), fixture flag included."""
    source = {k: v for k, v in manifest["source"].items() if k != "files"}
    source["files"] = [{"name": f["name"]} for f in manifest["source"]["files"]]
    symbols = [{k: v for k, v in e.items() if k != "sha256"} for e in manifest["symbols"]]
    return {k: v for k, v in manifest.items() if k not in ("source", "symbols")} | {
        "source": source, "symbols": symbols,
    }


def ohlcv_view(manifest: dict, payload: dict) -> dict:
    """GET /{symbol}/ohlcv: provenance = manifest.source (verbatim, including file hashes -- this
    route is explicitly NOT redacted the way /run is) + run_id + config_hash."""
    provenance = dict(manifest["source"])
    provenance["run_id"] = manifest["run_id"]
    provenance["config_hash"] = manifest["config_hash"]
    return {
        "symbol": payload["symbol"],
        "bars": payload["bars"],
        "data_quality_status": payload["data_quality_status"],
        "pit_status": payload["pit_status"],
        "findings": payload["findings"],
        "provenance": provenance,
    }


def indicators_view(payload: dict, ids: Optional[list] = None) -> dict:
    """GET /{symbol}/indicators: all indicators, or only `ids` when given. Caller validates
    unknown ids (400) before calling this -- this just filters."""
    indicators = payload["indicators"]
    if ids:
        indicators = {i: indicators[i] for i in ids}
    return {"symbol": payload["symbol"], "indicators": indicators}


def patterns_view(payload: dict) -> dict:
    return {"symbol": payload["symbol"], "patterns": payload.get("patterns", [])}
