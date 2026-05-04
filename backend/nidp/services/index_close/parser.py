"""ind_close_all CSV parser.

Headers (current):
    Index Name, Index Date, Open Index Value, High Index Value,
    Low Index Value, Closing Index Value, Points Change,
    Change(%), Volume, Turnover (Rs. Cr.), P/E, P/B, Div Yield
"""
from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Any, Optional


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
    for fmt in ("%d-%m-%Y", "%d-%b-%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try: return datetime.strptime(s, fmt).date().isoformat()
        except ValueError: continue
    return None


def parse_index_close(body: bytes) -> list[dict[str, Any]]:
    text = body.decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(text))
    headers = next(reader, None)
    if not headers:
        return []
    idx = {h.strip(): i for i, h in enumerate(headers)}

    def col(*names: str) -> Optional[int]:
        for n in names:
            if n in idx: return idx[n]
        return None

    name_i = col("Index Name", "INDEX NAME")
    date_i = col("Index Date", "INDEX DATE")
    if name_i is None or date_i is None:
        raise ValueError(f"ind_close_all missing core columns: {sorted(idx)}")

    out: list[dict[str, Any]] = []
    for r in reader:
        if not r or all(not c.strip() for c in r):
            continue
        try:
            name = r[name_i].strip()
            d = _date(r[date_i])
        except IndexError:
            continue
        if not (name and d):
            continue
        def g(i: Optional[int]) -> Optional[str]:
            return r[i] if i is not None and i < len(r) else None
        out.append({
            "as_of_date":  d,
            "index_name":  name,
            "open_price":  _f(g(col("Open Index Value", "OPEN INDEX VALUE"))),
            "high_price":  _f(g(col("High Index Value", "HIGH INDEX VALUE"))),
            "low_price":   _f(g(col("Low Index Value",  "LOW INDEX VALUE"))),
            "close_price": _f(g(col("Closing Index Value", "CLOSING INDEX VALUE"))),
            "pts_change":  _f(g(col("Points Change", "POINTS CHANGE"))),
            "pct_change":  _f(g(col("Change(%)", "CHANGE(%)"))),
            "volume":      _i(g(col("Volume", "VOLUME"))),
            "turnover":    _f(g(col("Turnover (Rs. Cr.)", "Turnover (Rs Cr)", "TURNOVER (RS. CR.)"))),
            "pe_ratio":    _f(g(col("P/E", "PE"))),
            "pb_ratio":    _f(g(col("P/B", "PB"))),
            "div_yield":   _f(g(col("Div Yield", "DIV YIELD"))),
        })
    return out
