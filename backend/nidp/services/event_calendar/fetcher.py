"""NSE event calendar + corporate filings fetcher.

Hits two NSE endpoints:
  1. /api/event-calendar          — board meetings, results, AGMs, dividends
  2. /api/corporates-financial-results  — recently filed financial results

Returns normalized event dicts ready for upsert into nidp.event_calendar.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from nidp.shared.sources.nse_fetcher import fetch_text
import json

logger = logging.getLogger(__name__)

_NSE_API = "https://www.nseindia.com"
_CALENDAR_URL = f"{_NSE_API}/api/event-calendar"
_RESULTS_URL  = f"{_NSE_API}/api/corporates-financial-results?index=equities"


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            from datetime import datetime
            return datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _normalise_event_type(purpose: str) -> str:
    p = purpose.lower()
    if any(k in p for k in ("quarterly result", "financial result", "q1", "q2", "q3", "q4")):
        return "quarterly_results"
    if "board meeting" in p:
        return "board_meeting"
    if "agm" in p or "annual general" in p:
        return "agm"
    if "dividend" in p:
        return "dividend"
    if "bonus" in p:
        return "bonus"
    if "split" in p or "sub-division" in p:
        return "split"
    if "buyback" in p or "buy back" in p:
        return "buyback"
    if "rights" in p:
        return "rights"
    return "other"


def _extract_period(purpose: str) -> str | None:
    """Extract period label like 'Q4 FY25' from purpose string."""
    import re
    m = re.search(r'(Q[1-4])[^A-Z0-9]*(\d{2,4})', purpose, re.IGNORECASE)
    if m:
        q, yr = m.group(1).upper(), m.group(2)
        yr = yr if len(yr) == 4 else "20" + yr
        fy = int(yr)
        return f"{q} FY{str(fy)[2:]}"
    # Annual result
    m2 = re.search(r'(annual|year ended|fy\s*20\d{2})', purpose, re.IGNORECASE)
    if m2:
        return "Annual"
    return None


async def fetch_event_calendar(
    from_date: date | None = None,
    to_date:   date | None = None,
) -> list[dict[str, Any]]:
    """Fetch NSE event calendar for a date range (default: today ± 90 days)."""
    today = date.today()
    from_date = from_date or (today - timedelta(days=7))
    to_date   = to_date   or (today + timedelta(days=90))

    url = (
        f"{_CALENDAR_URL}"
        f"?index=equities"
        f"&from_date={from_date.strftime('%d-%m-%Y')}"
        f"&to_date={to_date.strftime('%d-%m-%Y')}"
    )
    try:
        text, status = await fetch_text(url, referer=f"{_NSE_API}/companies-listing/corporate-filings-event-calendar")
    except Exception as e:
        logger.error("event_calendar fetch failed: %s", e)
        return []

    try:
        data = json.loads(text)
    except Exception:
        logger.error("event_calendar: invalid JSON (status=%s)", status)
        return []

    events: list[dict] = []
    for row in (data if isinstance(data, list) else data.get("data", [])):
        purpose = row.get("purpose") or row.get("bm_purpose") or ""
        ev_date = _parse_date(row.get("date") or row.get("bm_date"))
        symbol  = (row.get("symbol") or "").strip().upper()
        if not symbol or not ev_date:
            continue
        events.append({
            "symbol":       symbol,
            "company_name": row.get("companyName") or row.get("company_name") or "",
            "event_type":   _normalise_event_type(purpose),
            "event_date":   ev_date,
            "period":       _extract_period(purpose),
            "purpose":      purpose,
            "ex_date":      _parse_date(row.get("exDate") or row.get("ex_date")),
            "record_date":  _parse_date(row.get("recordDate") or row.get("record_date")),
            "source":       "nse",
        })
    logger.info("event_calendar: fetched %d events (%s → %s)", len(events), from_date, to_date)
    return events


async def fetch_recent_results(days_back: int = 3) -> list[dict[str, Any]]:
    """Fetch recently filed financial results from NSE."""
    try:
        text, status = await fetch_text(
            _RESULTS_URL,
            referer=f"{_NSE_API}/companies-listing/corporate-filings-financial-results",
        )
        data = json.loads(text)
    except Exception as e:
        logger.error("fetch_recent_results failed: %s", e)
        return []

    cutoff = date.today() - timedelta(days=days_back)
    events = []
    for row in (data if isinstance(data, list) else data.get("data", [])):
        filed = _parse_date(row.get("xbrlAttachment") or row.get("pdfLink") or "")
        broadcast = _parse_date(row.get("broadcastDateTime") or row.get("date"))
        if broadcast and broadcast < cutoff:
            continue
        symbol = (row.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        purpose = row.get("typeOfMeeting") or row.get("resultType") or "Quarterly Results"
        events.append({
            "symbol":       symbol,
            "company_name": row.get("companyName") or "",
            "event_type":   "quarterly_results",
            "event_date":   broadcast or date.today(),
            "period":       _extract_period(purpose),
            "purpose":      purpose,
            "ex_date":      None,
            "record_date":  None,
            "source":       "nse",
            "_xbrl_url":    row.get("xbrlAttachment"),
            "_pdf_url":     row.get("pdfLink"),
            "_broadcast_at": row.get("broadcastDateTime"),
        })
    return events
