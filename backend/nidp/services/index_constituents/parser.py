"""NSE constituent-list CSV parser + JSON weight parser.

CSV format (standard INDEX_CONSTITUENT_URLS):
    Company Name, Industry, Symbol, Series, ISIN Code
    weight_pct is None from CSV (not published in this file).

JSON format (INDEX_WEIGHT_API_URLS — NSE equity-stockIndices API):
    Returns {data: [{symbol, weightPercentOfIndex, meta: {isin}}]} or
    older variant with a bare "weight" field. parse_weights_json() extracts
    {symbol → weight_pct} for the merge step.
"""
from __future__ import annotations

import csv
import io
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def parse_constituents(body: bytes) -> list[dict[str, Any]]:
    text = body.decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(text))
    headers = next(reader, None)
    if not headers:
        return []
    norm = [h.strip() for h in headers]

    def col(*names: str):
        for n in names:
            if n in norm:
                return norm.index(n)
        return None

    sym_i  = col("Symbol", "SYMBOL")
    name_i = col("Company Name", "COMPANY NAME")
    ind_i  = col("Industry", "INDUSTRY")
    isin_i = col("ISIN Code", "ISIN CODE", "ISIN")

    if sym_i is None:
        raise ValueError(f"constituent CSV missing Symbol column. headers={norm}")

    out: list[dict[str, Any]] = []
    for r in reader:
        if not r or all(not c.strip() for c in r):
            continue
        try:
            sym = r[sym_i].strip().upper()
        except IndexError:
            continue
        if not sym:
            continue
        out.append({
            "symbol":       sym,
            "isin":         (r[isin_i].strip() if isin_i is not None and isin_i < len(r) else None) or None,
            "company_name": (r[name_i].strip() if name_i is not None and name_i < len(r) else None) or None,
            "industry":     (r[ind_i].strip()  if ind_i  is not None and ind_i  < len(r) else None) or None,
            "weight_pct":   None,    # populated by merge_weights() when weight API succeeds
        })
    return out


def parse_weights_json(body: bytes) -> dict[str, float]:
    """Parse NSE equity-stockIndices JSON response into {symbol: weight_pct}.

    Handles both "weightPercentOfIndex" (current) and "weight" (older) field names.
    Returns empty dict on any parse error so callers degrade gracefully.
    """
    try:
        payload = json.loads(body.decode("utf-8", errors="replace"))
    except (ValueError, UnicodeDecodeError):
        logger.debug("parse_weights_json: JSON decode failed")
        return {}

    data = payload.get("data") or []
    if not isinstance(data, list):
        return {}

    result: dict[str, float] = {}
    for entry in data:
        if not isinstance(entry, dict):
            continue
        sym = (entry.get("symbol") or "").strip().upper()
        if not sym:
            continue
        raw = entry.get("weightPercentOfIndex") or entry.get("weight")
        if raw is None:
            continue
        try:
            w = float(raw)
        except (TypeError, ValueError):
            continue
        if w > 0:
            result[sym] = round(w, 4)

    return result


def merge_weights(rows: list[dict[str, Any]], weights: dict[str, float]) -> list[dict[str, Any]]:
    """Merge symbol-keyed weight_pct into constituent rows from parse_constituents()."""
    if not weights:
        return rows
    for row in rows:
        sym = row.get("symbol", "")
        if sym in weights:
            row["weight_pct"] = weights[sym]
    return rows
