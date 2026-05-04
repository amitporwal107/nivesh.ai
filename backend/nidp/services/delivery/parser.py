"""sec_bhavdata_full CSV parser.

Headers (current):
    SYMBOL, SERIES, DATE1, PREV_CLOSE, OPEN_PRICE, HIGH_PRICE,
    LOW_PRICE, LAST_PRICE, CLOSE_PRICE, AVG_PRICE, TTL_TRD_QNTY,
    TURNOVER_LACS, NO_OF_TRADES, DELIV_QTY, DELIV_PER

Trims whitespace in headers (NSE leaves stray spaces, e.g. " DATE1").
DELIV_QTY and DELIV_PER can be "-" when delivery data is unavailable
for a series (e.g. T-segment) — we coerce to None.
"""
from __future__ import annotations

import csv
import io
import logging
import re
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _f(s: Optional[str]) -> Optional[float]:
    if s is None: return None
    s = s.strip().replace(",", "")
    if not s or s in ("-", "—"): return None
    try: return float(s)
    except ValueError: return None


def _i(s: Optional[str]) -> Optional[int]:
    f = _f(s)
    return int(f) if f is not None else None


def _date(s: str) -> Optional[str]:
    s = s.strip()
    for fmt in ("%d-%b-%Y", "%d-%B-%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try: return datetime.strptime(s, fmt).date().isoformat()
        except ValueError: continue
    return None


def parse_delivery(body: bytes) -> list[dict[str, Any]]:
    text = body.decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(text))
    headers = next(reader, None)
    if not headers:
        return []
    idx = {h.strip(): i for i, h in enumerate(headers)}
    needed = {"SYMBOL", "SERIES", "DATE1", "TTL_TRD_QNTY", "DELIV_QTY", "DELIV_PER"}
    if not needed.issubset(idx.keys()):
        raise ValueError(
            f"sec_bhavdata_full missing columns. Have {sorted(idx.keys())}, need {sorted(needed)}"
        )

    out: list[dict[str, Any]] = []
    for r in reader:
        if not r or all(not c.strip() for c in r):
            continue
        try:
            sym = r[idx["SYMBOL"]].strip().upper()
            series = r[idx["SERIES"]].strip().upper()
            d = _date(r[idx["DATE1"]])
        except (IndexError, KeyError):
            continue
        if not (sym and series and d):
            continue
        out.append({
            "as_of_date":      d,
            "symbol":          sym,
            "series":          series,
            "traded_qty":      _i(r[idx["TTL_TRD_QNTY"]]),
            "deliverable_qty": _i(r[idx["DELIV_QTY"]]),
            "deliverable_pct": _f(r[idx["DELIV_PER"]]),
        })
    return out
