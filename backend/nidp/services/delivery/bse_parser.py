"""Parser for BSE's daily delivery-position file.

Source: https://www.bseindia.com/BSEDATA/gross/{yyyy}/SCBSEALL{ddmm}.zip
        -> SCBSEALL{ddmm}.TXT, pipe-delimited:

    DATE|SCRIP CODE|DELIVERY QTY|DELIVERY VAL|DAY'S VOLUME|DAY'S TURNOVER|DELV. PER.
    17082026|936400|0000000000000064|0000000000068608|0000000000000064|0000000000068608|100.00

Quirks this handles:
  * quantities are zero-padded fixed width ("0000000000000064" -> 64)
  * the percentage is zero-padded too ("095.45" -> 95.45)
  * the date is DDMMYYYY, not ISO
  * rows are identified by BSE scrip code only — mapping to the NSE
    symbol/series used by nidp.delivery_data is the caller's job
    (see delivery.service._fetch_bse).

Pure function — no I/O.
"""
from __future__ import annotations

import io
import logging
import zipfile
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)

_EXPECTED_COLS = 7


def _int(s: str) -> Optional[int]:
    s = (s or "").strip().lstrip("0")
    if not s:
        return 0 if (s == "" and (s is not None)) else None
    try:
        return int(s)
    except ValueError:
        return None


def _pct(s: str) -> Optional[float]:
    s = (s or "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def unzip_delivery(body: bytes) -> bytes:
    """BSE ships the TXT inside a ZIP; pass plain bodies straight through."""
    if body[:2] != b"PK":
        return body
    with zipfile.ZipFile(io.BytesIO(body)) as zf:
        names = zf.namelist()
        for n in names:
            if n.upper().endswith(".TXT"):
                return zf.read(n)
        return zf.read(max(names, key=lambda n: zf.getinfo(n).file_size))


def parse_bse_delivery(body: bytes) -> list[dict[str, Any]]:
    """Parse the BSE delivery TXT into scrip-code-keyed rows.

    Returns dicts with: as_of_date, scrip_code, traded_qty,
    deliverable_qty, deliverable_pct.
    """
    text = unzip_delivery(body).decode("latin-1", errors="replace")
    out: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('"') or "SCRIP CODE" in line.upper():
            continue                                   # header / quoted header
        parts = line.split("|")
        if len(parts) < _EXPECTED_COLS:
            continue
        raw_date = parts[0].strip()
        try:
            as_of = datetime.strptime(raw_date, "%d%m%Y").date().isoformat()
        except ValueError:
            continue
        scrip = parts[1].strip()
        if not scrip:
            continue
        out.append({
            "as_of_date":      as_of,
            "scrip_code":      scrip,
            "deliverable_qty": _int(parts[2]),
            "traded_qty":      _int(parts[4]),
            "deliverable_pct": _pct(parts[6]),
        })
    if not out:
        logger.warning("BSE delivery: no rows parsed (%d bytes)", len(body))
    return out
