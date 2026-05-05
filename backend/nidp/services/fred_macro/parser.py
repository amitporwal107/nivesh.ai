"""FRED CSV parser.

The fredgraph.csv endpoint returns a 2-column CSV:

    DATE,DGS10
    1962-01-02,4.06
    1962-01-03,4.03
    1962-01-04,.
    ...

Note: '.' (a literal period) is FRED's missing-value sentinel. We
coerce to None — downstream queries treat NULL as "not observed."
"""
from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Any, Optional

# Curated catalog: series_id -> (name, units, frequency)
SERIES_CATALOG: dict[str, tuple[str, str, str]] = {
    "DGS10":              ("US 10-year Treasury yield",        "Percent",         "Daily"),
    "DGS2":               ("US 2-year Treasury yield",         "Percent",         "Daily"),
    "DTWEXBGS":           ("USD trade-weighted index",         "Index",           "Daily"),
    "DCOILBRENTEU":       ("Brent crude spot",                 "USD per Barrel",  "Daily"),
    "DCOILWTICO":         ("WTI crude spot",                   "USD per Barrel",  "Daily"),
    "VIXCLS":             ("CBOE VIX",                         "Index",           "Daily"),
    "GOLDAMGBD228NLBM":   ("Gold London PM fix",               "USD per Troy Oz", "Daily"),
    "FEDFUNDS":           ("Fed Funds effective rate",         "Percent",         "Monthly"),
}


def _to_float(s: str) -> Optional[float]:
    s = (s or "").strip()
    if not s or s == "." or s in ("NA", "N/A"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _parse_date_iso(s: str) -> Optional[str]:
    s = (s or "").strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d-%b-%Y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def parse_fred_csv(body: bytes, *, series_id: str) -> list[dict[str, Any]]:
    """Parse FRED's 2-column CSV into rows for nidp.fred_macro."""
    text = body.decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(text))
    headers = next(reader, None)
    if not headers or len(headers) < 2:
        return []

    name, units, frequency = SERIES_CATALOG.get(series_id, (series_id, None, None))

    rows: list[dict[str, Any]] = []
    for raw in reader:
        if not raw or len(raw) < 2:
            continue
        d = _parse_date_iso(raw[0])
        if not d:
            continue
        v = _to_float(raw[1])
        rows.append({
            "as_of_date":  d,
            "series_id":   series_id,
            "series_name": name,
            "value":       v,
            "units":       units,
            "frequency":   frequency,
        })
    return rows
