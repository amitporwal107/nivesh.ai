"""Parser for NSE EQUITY_L.csv (the listed-equity master CSV).

Schema (post-2020 layout):
    SYMBOL, NAME OF COMPANY, SERIES, DATE OF LISTING,
    PAID UP VALUE, MARKET LOT, ISIN NUMBER, FACE VALUE

Trivial CSV — but worth its own module so the validator can hit
parse-level failures early (encoding glitches, header drift).
"""
from __future__ import annotations

import csv
import io
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def parse_equity_master(csv_bytes: bytes) -> List[Dict[str, Any]]:
    if not csv_bytes:
        return []

    text = csv_bytes.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))

    out: List[Dict[str, Any]] = []
    for raw in reader:
        # Header may have trailing whitespace from NSE — normalise
        row = {(k or "").strip().upper(): (v or "").strip() for k, v in raw.items()}
        symbol = row.get("SYMBOL")
        if not symbol:
            continue
        out.append({
            "symbol":        symbol,
            "company_name":  row.get("NAME OF COMPANY"),
            "series":        row.get("SERIES") or None,
            "listing_date":  _parse_listing_date(row.get("DATE OF LISTING")),
            "paid_up_value": _to_float(row.get("PAID UP VALUE")),
            "market_lot":    _to_int(row.get("MARKET LOT")),
            "isin":          row.get("ISIN NUMBER") or None,
            "face_value":    _to_float(row.get("FACE VALUE")),
        })
    return out


def _parse_listing_date(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    s = s.strip()
    for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _to_float(s: Optional[str]) -> Optional[float]:
    if not s:
        return None
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return None


def _to_int(s: Optional[str]) -> Optional[int]:
    if not s:
        return None
    try:
        return int(float(s.replace(",", "")))
    except ValueError:
        return None
