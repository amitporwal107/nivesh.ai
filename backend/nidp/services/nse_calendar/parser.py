"""NSE holiday-master JSON parser.

Response shape (current):
    {
      "CM":  [{"tradingDate":"04-Mar-2026","weekDay":"Wednesday","description":"Holi"}, ...],
      "FO":  [...],
      "CD":  [...], ...
    }

Some NSE API variants nest under {"data": {...}}; we tolerate both.
Outputs one row per (date, segment).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


def _parse_date(s: str):
    s = (s or "").strip()
    for fmt in ("%d-%b-%Y", "%d-%B-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def parse_calendar(body: bytes) -> list[dict[str, Any]]:
    try:
        payload = json.loads(body.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as e:
        raise ValueError(f"NSE holiday-master: invalid JSON ({e})") from e
    if isinstance(payload, dict) and "data" in payload and isinstance(payload["data"], dict):
        payload = payload["data"]
    if not isinstance(payload, dict):
        raise ValueError(f"unexpected NSE holiday-master shape: {type(payload).__name__}")

    rows: list[dict[str, Any]] = []
    for segment, entries in payload.items():
        if not isinstance(entries, list):
            continue
        for e in entries:
            if not isinstance(e, dict):
                continue
            d = _parse_date(e.get("tradingDate") or e.get("trading_date") or "")
            if not d:
                continue
            rows.append({
                "holiday_date": d,
                "segment":      segment.upper(),
                "description":  (e.get("description") or e.get("purpose") or "").strip() or None,
            })
    return rows
