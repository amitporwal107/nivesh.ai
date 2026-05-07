"""Parse NSE corporate-announcements JSON into NIDP rows.

Endpoint shape (as of 2026):
    GET https://www.nseindia.com/api/corporate-announcements
        ?index=equities&from_date=DD-MM-YYYY&to_date=DD-MM-YYYY
    → [ { symbol, isin, sm_name, desc, attchmntFile, attchmntText,
          an_dt, dissemDT, csvName, exchdisstime, ... }, ... ]

NSE rotates field naming under the hood; we read defensively and fall
back to a synthetic id (sha1 over stable fields) so re-fetches dedupe
cleanly via the (announcement_id, source) primary key.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")

# NSE timestamps come back in IST without offset, in mixed formats.
_DT_FORMATS = (
    "%d-%b-%Y %H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%d-%m-%Y %H:%M:%S",
    "%d-%b-%Y",
)


def _parse_dt_ist(raw: Any) -> datetime | None:
    if not raw:
        return None
    s = str(raw).strip()
    for fmt in _DT_FORMATS:
        try:
            naive = datetime.strptime(s, fmt)
            return naive.replace(tzinfo=IST).astimezone(timezone.utc)
        except ValueError:
            continue
    logger.debug("could not parse NSE timestamp: %r", raw)
    return None


def _synthetic_id(source: str, symbol: str | None, filed_at: datetime, subject: str) -> str:
    h = hashlib.sha1()
    h.update(source.encode())
    h.update(b"|")
    h.update((symbol or "").encode())
    h.update(b"|")
    h.update(filed_at.isoformat().encode())
    h.update(b"|")
    h.update((subject or "").encode())
    return h.hexdigest()


def parse_nse_announcements(body: bytes) -> list[dict]:
    """Return list of NIDP rows from raw NSE JSON body. Tolerant of shape drift."""
    try:
        data = json.loads(body)
    except json.JSONDecodeError as e:
        logger.error("NSE announcements: invalid JSON (%d bytes): %s", len(body), e)
        return []

    # NSE sometimes wraps the array in {"data": [...]} or {"announcements": [...]}.
    if isinstance(data, dict):
        for key in ("data", "announcements", "result"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
        else:
            logger.warning("NSE announcements: unexpected dict shape: keys=%s", list(data.keys()))
            return []
    if not isinstance(data, list):
        logger.warning("NSE announcements: expected list, got %s", type(data))
        return []

    rows: list[dict] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        row = _parse_one_nse(entry)
        if row is not None:
            rows.append(row)
    logger.info("NSE announcements: parsed %d rows from %d entries", len(rows), len(data))
    return rows


def _parse_one_nse(e: dict) -> dict | None:
    # Filing time: prefer dissemDT (when NSE published), fall back to an_dt (when company filed),
    # fall back to exchdisstime. If none parse, drop the record — no timestamp = unusable.
    filed_at = (
        _parse_dt_ist(e.get("dissemDT"))
        or _parse_dt_ist(e.get("exchdisstime"))
        or _parse_dt_ist(e.get("an_dt"))
        or _parse_dt_ist(e.get("sort_date"))
    )
    if filed_at is None:
        return None

    broadcast_at = _parse_dt_ist(e.get("an_dt")) or _parse_dt_ist(e.get("exchdisstime"))

    symbol = (e.get("symbol") or "").strip().upper() or None
    isin = (e.get("sm_isin") or e.get("isin") or "").strip().upper() or None
    company = (e.get("sm_name") or e.get("companyName") or "").strip() or None
    subject = (e.get("desc") or e.get("subject") or e.get("smIndustry") or "").strip()
    description = (e.get("attchmntText") or e.get("description") or "").strip() or None
    raw_category = (e.get("smIndustry") or e.get("category") or e.get("subcategory") or "").strip() or None
    attachment_raw = (e.get("attchmntFile") or e.get("attachment") or "").strip()
    # NSE sometimes returns sentinels like "-" or "NA" instead of a URL.
    attachment = attachment_raw if attachment_raw.lower().startswith(("http://", "https://")) else None

    source = "NSE_ANN"
    return {
        "announcement_id": _synthetic_id(source, symbol, filed_at, subject),
        "source": source,
        "ticker_symbol": symbol,
        "isin": isin,
        "scrip_code": None,
        "company_name": company,
        "filed_at": filed_at,
        "broadcast_at": broadcast_at,
        "subject": subject or None,
        "description": description,
        "raw_category": raw_category,
        "attachment_url": attachment,
        "raw_payload": e,
    }
