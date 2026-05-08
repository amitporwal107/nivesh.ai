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
    # Results / earnings — check before "board meeting" so a board meeting
    # called to approve results is classified as quarterly_results, not board_meeting.
    if any(k in p for k in (
        "quarterly result", "financial result",
        "unaudited result", "audited result",
        "q1", "q2", "q3", "q4",
        "half year", "half-year", "nine month",
    )):
        return "quarterly_results"
    # Annual results (PSU banks, full-year filings)
    if any(k in p for k in ("annual result", "annual account", "year ended", "full year result")):
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


def _extract_period(purpose: str, bm_desc: str = "") -> str | None:
    """Extract period label like 'Q4 FY26' from purpose or bm_desc strings."""
    import re
    from datetime import date as _date

    text = f"{purpose} {bm_desc}"

    # Explicit Q1-Q4 + year — highest confidence
    m = re.search(r'\b(Q[1-4])\s*(?:FY)?[^A-Z0-9]*(\d{2,4})\b', text, re.IGNORECASE)
    if m:
        q, yr = m.group(1).upper(), m.group(2)
        yr = yr if len(yr) == 4 else "20" + yr
        fy = int(yr)
        return f"{q} FY{str(fy)[2:]}"

    # "quarter ended <Month> <Year>" or "period ended <Month> <Year>"
    # → derive Q from month (Indian FY: Apr-Jun=Q1, Jul-Sep=Q2, Oct-Dec=Q3, Jan-Mar=Q4)
    _MONTH_Q = {
        1: "Q4", 2: "Q4", 3: "Q4",   # Jan-Mar  → Q4
        4: "Q1", 5: "Q1", 6: "Q1",   # Apr-Jun  → Q1
        7: "Q2", 8: "Q2", 9: "Q2",   # Jul-Sep  → Q2
        10: "Q3", 11: "Q3", 12: "Q3", # Oct-Dec  → Q3
    }
    _MONTH_NAMES = {
        "january": 1, "february": 2, "march": 3, "april": 4,
        "may": 5, "june": 6, "july": 7, "august": 8,
        "september": 9, "october": 10, "november": 11, "december": 12,
        "jan": 1, "feb": 2, "mar": 3, "apr": 4,
        "jun": 6, "jul": 7, "aug": 8, "sep": 9,
        "oct": 10, "nov": 11, "dec": 12,
    }
    m2 = re.search(
        r'(?:quarter|period|year|half.?year)\s+ended\s+(\w+)\s+\d{1,2}[,\s]+(\d{4})',
        text, re.IGNORECASE,
    )
    if m2:
        mon_str = m2.group(1).lower()
        yr = int(m2.group(2))
        mon = _MONTH_NAMES.get(mon_str)
        if mon:
            q = _MONTH_Q[mon]
            # Indian FY: FY ends March, so "period ended March 2026" → FY26
            fy = yr if mon >= 4 else yr  # April 2025 → FY26; March 2026 → FY26
            return f"{q} FY{str(fy)[2:]}"

    # "nine months ended" / "six months ended" / "half year ended <Month>"
    m3 = re.search(r'(?:nine|6|six|half)[- ](?:months?|year)\s+ended\s+(\w+)\s+\d{1,2}[,\s]+(\d{4})',
                   text, re.IGNORECASE)
    if m3:
        mon_str = m3.group(1).lower()
        yr = int(m3.group(2))
        mon = _MONTH_NAMES.get(mon_str)
        if mon:
            q = _MONTH_Q[mon]
            return f"{q} FY{str(yr)[2:]}"

    # "annual" / "year ended" without a specific month → just Annual + FY
    m4 = re.search(r'(?:annual|year ended|fy\s*20(\d{2}))', text, re.IGNORECASE)
    if m4:
        yr_match = re.search(r'20(\d{2})', text)
        suffix = yr_match.group(1) if yr_match else ""
        return f"Annual FY{suffix}" if suffix else "Annual"

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
        purpose  = row.get("purpose") or row.get("bm_purpose") or ""
        bm_desc  = row.get("bm_desc") or row.get("description") or ""
        ev_date  = _parse_date(row.get("date") or row.get("bm_date"))
        symbol   = (row.get("symbol") or "").strip().upper()
        if not symbol or not ev_date:
            continue
        # Use bm_desc as fallback for event type when purpose is generic
        event_type = _normalise_event_type(purpose) or _normalise_event_type(bm_desc)
        events.append({
            "symbol":       symbol,
            "company_name": row.get("companyName") or row.get("company") or row.get("company_name") or "",
            "event_type":   event_type,
            "event_date":   ev_date,
            "period":       _extract_period(purpose, bm_desc),
            "purpose":      bm_desc or purpose,   # store the richer description
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
