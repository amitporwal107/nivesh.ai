"""NSE cash-market sessions for the AI scanner's bar store (`stock_ohlcv`).

Two authorities, both read through the data platform (DaaS), the path services/kite_live_feed/config.py and
services/copilot_tools/market_research.py already use (the app database has no `nidp` schema):

* **The NSE holiday list, segment CM** (`nidp.nse_holidays`, DaaS `/holidays`). It is known in advance, so it decides
  whether a date is a session before that day's data exists: the evening run's own date.
* **The warehouse's loaded sessions** (`nidp.prices_eod`, DaaS `/prices/eod?on=`). They decide whether a past date was
  a session. The study's acceptance test is "scanner sessions minus warehouse sessions = 0 rows, both ways".

A weekday is never assumed to be a session: a year the holiday list has no CM rows for, or a list that cannot be read,
is `CalendarUnavailable`, and the caller refuses with that reason.

Readiness (owner decision 2026-10-27: do not wait for 1 Jan to find out). From a lead date (default 1 Dec, set with
SCANNER_CALENDAR_LEAD=MM-DD or the runner's --calendar-lead) the NEXT year's CM list must be loaded too; `readiness`
says which year is missing so the evening run can log an ERROR and record an alert while it still scores the day.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import date, timedelta
from typing import Dict, Iterable, Set, Tuple

logger = logging.getLogger(__name__)

DEFAULT_LEAD = "12-01"         # from 1 Dec the next year's holiday list must be loaded
HOLIDAY_TTL_S = 3600            # NSE adds an occasional special holiday mid-year; a long-lived process re-reads hourly
SESSION_READ_CONCURRENCY = 8    # warehouse reads in flight

_holiday_cache: Dict[int, Tuple[float, Dict[date, str]]] = {}


class CalendarUnavailable(RuntimeError):
    """The session calendar could not be read or does not cover the date: nothing may be assumed."""


async def _get(path: str, params: dict):
    from services.copilot_tools import daas_client
    try:
        status, body = await daas_client.get_raw(path, params)
    except daas_client.DaasError as e:
        raise CalendarUnavailable(f"{path}: {e}") from e
    if status != 200 or not isinstance(body, dict) or not isinstance(body.get("data"), list):
        raise CalendarUnavailable(f"{path}: HTTP {status}")
    return body


async def holidays_for_year(year: int) -> Dict[date, str]:
    """{date: description} of the NSE cash-market (CM) holidays in `year`. Raises CalendarUnavailable when the list
    cannot be read or holds no CM row for the year (NSE publishes the whole year's list, so an empty year means the
    list was never loaded, not that the year has no holidays)."""
    hit = _holiday_cache.get(year)
    if hit and time.monotonic() - hit[0] < HOLIDAY_TTL_S:
        return hit[1]
    body = await _get("/holidays", {"segment": "CM", "from": f"{year}-01-01", "to": f"{year}-12-31", "limit": 1000})
    out: Dict[date, str] = {}
    for r in body["data"]:
        try:
            out[date.fromisoformat(str(r.get("holiday_date"))[:10])] = str(r.get("description") or "holiday")
        except (TypeError, ValueError):
            continue
    if not out:
        raise CalendarUnavailable(f"the NSE holiday list (segment CM) has no rows for {year}")
    _holiday_cache[year] = (time.monotonic(), out)
    return out


def classify(d: date, holidays: Dict[date, str]) -> Tuple[bool, str]:
    """(is_session, reason) from the weekday and the year's CM holiday list."""
    if d.weekday() >= 5:
        return False, "weekend"
    if d in holidays:
        return False, f"NSE holiday: {holidays[d]}"
    return True, "weekday, not an NSE CM holiday"


async def check_session(d: date) -> Tuple[bool, str]:
    """(is_session, reason) for `d`. Raises CalendarUnavailable when that cannot be established."""
    if d.weekday() >= 5:
        return False, "weekend"
    return classify(d, await holidays_for_year(d.year))


async def warehouse_has_session(d: date) -> bool:
    """True when the warehouse (nidp.prices_eod) holds EQ rows on `d`."""
    body = await _get("/prices/eod", {"on": d.isoformat(), "series": "EQ", "limit": 1})
    return bool(body["data"])


async def warehouse_rows(d: date) -> int:
    """EQ + BE rows the warehouse holds on `d` (the two series the scanner keeps)."""
    total = 0
    for series in ("EQ", "BE"):
        body = await _get("/prices/eod", {"on": d.isoformat(), "series": series, "limit": 5000})
        total += len(body["data"])
    return total


async def warehouse_sessions(start: date, end: date, extra: Iterable[date] = ()) -> Set[date]:
    """The warehouse sessions among every weekday in [start, end] plus `extra` (e.g. the store's own dates, so a
    weekend date in the store is checked too). Raises CalendarUnavailable when any read fails."""
    days = {start + timedelta(days=i) for i in range((end - start).days + 1)}
    days = {d for d in days if d.weekday() < 5} | {d for d in extra if start <= d <= end}
    gate = asyncio.Semaphore(SESSION_READ_CONCURRENCY)

    async def one(d: date):
        async with gate:
            return d, await warehouse_has_session(d)

    found = await asyncio.gather(*(one(d) for d in sorted(days)))
    return {d for d, ok in found if ok}


def parse_lead(text: str = "") -> Tuple[int, int]:
    """(month, day) from "MM-DD" (default SCANNER_CALENDAR_LEAD, else 12-01). Raises ValueError on a bad value."""
    raw = (text or os.environ.get("SCANNER_CALENDAR_LEAD") or DEFAULT_LEAD).strip()
    month, day = (int(x) for x in raw.split("-"))
    date(2001, month, day)            # validates; 2001 is not a leap year, so 02-29 is refused
    return month, day


async def readiness(today: date, lead: Tuple[int, int] = (12, 1)) -> Dict:
    """Is the CM holiday list loaded for every year the coming sessions need? Always this year; from the lead date
    also next year. {ready, missing_year, checked_years, reason}; never raises for a missing year."""
    need = [today.year] + ([today.year + 1] if (today.month, today.day) >= lead else [])
    for year in need:
        try:
            await holidays_for_year(year)
        except CalendarUnavailable as e:
            return {"ready": False, "missing_year": year, "checked_years": need, "reason": str(e)}
    return {"ready": True, "missing_year": None, "checked_years": need, "reason": None}
