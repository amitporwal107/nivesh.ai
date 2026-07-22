"""Parse BSE corporate-announcements JSON into NIDP rows.

Endpoint: https://api.bseindia.com/BseIndiaAPI/api/AnnGetData/w
Date format: YYYYMMDD (NOT DD/MM/YYYY as the doc page implies).
Pagination: 50 rows per page; we fetch sequentially until empty page.

BSE response shape:
    { "Table": [ { NEWSID, SCRIP_CD, XML_NAME, NEWSSUB, DT_TM, NEWS_DT,
                   ANNOUNCEMENT_TYPE, ATTACHMENTNAME, HEADLINE,
                   CATEGORYNAME, CRITICALNEWS, ... }, ... ],
      "Table1": [ ... pagination metadata ... ] }

Notes:
* NEWSID is stable across re-fetches — we still hash for the synthetic
  announcement_id so the (announcement_id, source) PK collision pattern
  matches NSE.
* Attachment URL is constructed from ATTACHMENTNAME — BSE only returns
  the filename, not the full URL.
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

_BSE_ATTACHMENT_BASE = "https://www.bseindia.com/xml-data/corpfiling/AttachLive/"

_DT_FORMATS = (
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S",
    "%d/%m/%Y %H:%M:%S",
)


def _parse_dt_ist(raw: Any) -> datetime | None:
    if not raw:
        return None
    s = str(raw).strip()
    # BSE sometimes returns "/Date(1715079600000)/" Microsoft AJAX format
    if s.startswith("/Date(") and s.endswith(")/"):
        try:
            ms = int(s[6:-2].split("+")[0].split("-")[0] or "0")
            return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
        except ValueError:
            return None
    for fmt in _DT_FORMATS:
        try:
            naive = datetime.strptime(s, fmt)
            return naive.replace(tzinfo=IST).astimezone(timezone.utc)
        except ValueError:
            continue
    return None


def _synthetic_id(source: str, scrip_code: str | None, news_id: str | None,
                  filed_at: datetime, subject: str) -> str:
    h = hashlib.sha1()
    h.update(source.encode())
    h.update(b"|")
    h.update((news_id or scrip_code or "").encode())
    h.update(b"|")
    h.update(filed_at.isoformat().encode())
    h.update(b"|")
    h.update((subject or "").encode())
    return h.hexdigest()


def parse_bse_announcements(body: bytes) -> list[dict]:
    try:
        data = json.loads(body)
    except json.JSONDecodeError as e:
        logger.error("BSE announcements: invalid JSON (%d bytes): %s", len(body), e)
        return []

    if not isinstance(data, dict):
        logger.warning("BSE announcements: expected dict, got %s", type(data))
        return []
    raw_rows = data.get("Table") or []
    if not isinstance(raw_rows, list):
        logger.warning("BSE announcements: 'Table' is not a list")
        return []

    rows: list[dict] = []
    for entry in raw_rows:
        if not isinstance(entry, dict):
            continue
        row = _parse_one_bse(entry)
        if row is not None:
            rows.append(row)
    logger.info("BSE announcements: parsed %d rows from %d entries", len(rows), len(raw_rows))
    return rows


def _parse_one_bse(e: dict) -> dict | None:
    filed_at = (
        _parse_dt_ist(e.get("DT_TM"))
        or _parse_dt_ist(e.get("NEWS_DT"))
    )
    if filed_at is None:
        return None

    scrip_code = str(e.get("SCRIP_CD") or "").strip() or None
    news_id = str(e.get("NEWSID") or "").strip() or None
    # XML_NAME is unreliable as a ticker source: most BSE filings prefix
    # with "ANN_" or other non-ticker codes. Leave ticker_symbol NULL on
    # BSE rows; canonical ticker is resolved at query time via the
    # scrip_code → equity_master join.
    symbol: str | None = None
    subject = (e.get("NEWSSUB") or e.get("HEADLINE") or "").strip()
    headline = (e.get("HEADLINE") or "").strip() or None

    # BSE subjects follow "<Company Name> - <SCRIP_CD> - <Description>" with
    # consistent " - " separators. Extract the company name as a cheap
    # entity-resolution shortcut so we don't need the equity_master join
    # for display.
    company_name: str | None = None
    if subject and " - " in subject:
        parts = subject.split(" - ", 2)
        head_name = parts[0].strip()
        # Sanity: company names are 3–80 chars, contain a letter.
        if 3 <= len(head_name) <= 80 and any(c.isalpha() for c in head_name):
            company_name = head_name
    raw_category = (e.get("CATEGORYNAME") or e.get("ANNOUNCEMENT_TYPE") or "").strip() or None
    # SUBCATNAME comes from the AnnSubCategoryGetData/w endpoint (subcategory
    # sweep); the older AnnGetData/w rows won't carry it → stays NULL. This is
    # the finer Phase-1 filing type (e.g. "Award of Order / Receipt of Order",
    # "Earnings Call Transcript") that drives doc_type + order/M&A detection.
    subcategory = (e.get("SUBCATNAME") or "").strip() or None

    attachment_name = (e.get("ATTACHMENTNAME") or "").strip()
    attachment_url = (_BSE_ATTACHMENT_BASE + attachment_name) if attachment_name else None

    source = "BSE_ANN"
    return {
        "announcement_id": _synthetic_id(source, scrip_code, news_id, filed_at, subject),
        "source": source,
        "ticker_symbol": symbol,
        "isin": None,                              # BSE feed doesn't carry ISIN; resolved later via scrip_code → equity_master
        "scrip_code": scrip_code,
        "company_name": company_name,
        "filed_at": filed_at,
        "broadcast_at": _parse_dt_ist(e.get("NEWS_DT")),
        "subject": subject or None,
        "description": headline if headline != subject else None,
        "raw_category": raw_category,
        "subcategory": subcategory,
        "attachment_url": attachment_url,
        "raw_payload": e,
    }
