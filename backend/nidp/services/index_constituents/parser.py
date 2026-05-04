"""NSE constituent-list CSV parser.

Headers (current):
    Company Name, Industry, Symbol, Series, ISIN Code

Older variants ship `INDUSTRY` / `SYMBOL` upper-case. We tolerate both.
"""
from __future__ import annotations

import csv
import io
from typing import Any


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

    sym_i = col("Symbol", "SYMBOL")
    name_i = col("Company Name", "COMPANY NAME")
    ind_i = col("Industry", "INDUSTRY")
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
            "industry":     (r[ind_i].strip() if ind_i is not None and ind_i < len(r) else None) or None,
            "weight_pct":   None,    # Not in standard NSE constituent CSV; fed by separate weight file
        })
    return out
