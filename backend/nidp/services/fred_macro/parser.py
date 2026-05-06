"""FRED observations parser.

The api.stlouisfed.org/fred/series/observations endpoint (file_type=json)
returns:

    {
      "observations": [
        {"date": "1962-01-02", "value": "4.06", ...},
        {"date": "1962-01-03", "value": "4.03", ...},
        {"date": "1962-01-04", "value": ".",    ...},  # missing
        ...
      ]
    }

Note: '.' (a literal period) is FRED's missing-value sentinel. We
coerce to None — downstream queries treat NULL as "not observed."
"""
from __future__ import annotations

import json
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


def parse_fred_observations(body: bytes, *, series_id: str) -> list[dict[str, Any]]:
    """Parse FRED's JSON observations response into rows for nidp.fred_macro."""
    text = body.decode("utf-8-sig", errors="replace")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"FRED {series_id}: invalid JSON ({e})") from e

    if isinstance(payload, dict) and payload.get("error_code"):
        raise ValueError(
            f"FRED {series_id}: API error "
            f"{payload.get('error_code')}: {payload.get('error_message')}"
        )

    observations = (payload or {}).get("observations") or []
    if not isinstance(observations, list):
        raise ValueError(f"FRED {series_id}: expected list of observations")

    name, units, frequency = SERIES_CATALOG.get(series_id, (series_id, None, None))

    rows: list[dict[str, Any]] = []
    for obs in observations:
        if not isinstance(obs, dict):
            continue
        d = _parse_date_iso(str(obs.get("date") or ""))
        if not d:
            continue
        rows.append({
            "as_of_date":  d,
            "series_id":   series_id,
            "series_name": name,
            "value":       _to_float(str(obs.get("value") or "")),
            "units":       units,
            "frequency":   frequency,
        })
    return rows
