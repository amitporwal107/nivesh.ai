"""NSE sessions for the desk: weekdays that are not NSE cash-market (CM) holidays, from the data platform's holiday list
(services/positional_engine/session_calendar.py reads it; a year without a list is CalendarUnavailable, never a guess).

The holiday lists of the years in use are loaded into this module (`load_years`) so that the point-in-time view can
answer `latest_session` without a network call. Special sessions on a weekend (e.g. a Budget-day Sunday) are not in the
calendar and are not replayed — a stated limitation of the simulator.
"""
from __future__ import annotations

import logging
import time as _time
from datetime import date, datetime, time, timedelta
from typing import Iterable

from services.positional_engine import session_calendar as sc

from .view import IST, DataUnavailable, published_at

logger = logging.getLogger(__name__)

SESSION_CLOSE_IST = time(15, 30)
CalendarUnavailable = sc.CalendarUnavailable

_HOLIDAYS: dict[int, dict[date, str]] = {}
_LOADED_AT: dict[int, float] = {}
RELOAD_S = 3600          # NSE occasionally adds a special holiday mid-year


async def load_years(years: Iterable[int], *, required: Iterable[int] = ()) -> dict[int, str]:
    """Load the CM holiday lists of `years`. A year in `required` that cannot be read raises CalendarUnavailable; the
    others are logged and skipped. Returns {year: "ok" | reason}."""
    req = set(required)
    out: dict[int, str] = {}
    for y in sorted(set(years) | req):
        if y in _HOLIDAYS and _time.monotonic() - _LOADED_AT.get(y, 0) < RELOAD_S:
            out[y] = "ok"
            continue
        try:
            _HOLIDAYS[y] = await sc.holidays_for_year(y)
            _LOADED_AT[y] = _time.monotonic()
            out[y] = "ok"
        except sc.CalendarUnavailable as e:
            if y in _HOLIDAYS:                       # a failed refresh keeps the list already loaded
                logger.warning("autodesk calendar: refresh of %s failed, keeping the loaded list: %s", y, e)
                out[y] = "ok (refresh failed)"
                continue
            out[y] = str(e)
            if y in req:
                raise
            logger.info("autodesk calendar: %s", e)
    return out


def loaded_years() -> list[int]:
    return sorted(_HOLIDAYS)


def set_holidays(year: int, holidays: dict[date, str]) -> None:
    """For tests and scenarios: install a year's list without the network."""
    _HOLIDAYS[year] = dict(holidays)
    _LOADED_AT[year] = _time.monotonic()


def is_session(d: date) -> bool:
    if d.weekday() >= 5:
        return False
    h = _HOLIDAYS.get(d.year)
    if h is None:
        raise CalendarUnavailable(f"the NSE holiday list for {d.year} is not loaded")
    return d not in h


def holiday_name(d: date) -> str | None:
    return (_HOLIDAYS.get(d.year) or {}).get(d)


def _days(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


async def sessions_between(start: date, end: date) -> list[date]:
    """Sessions in [start, end]. Loads the years it needs (the year before `start` best-effort, for look-backs)."""
    if end < start:
        return []
    await load_years([start.year - 1], required=range(start.year, end.year + 1))
    return [d for d in _days(start, end) if is_session(d)]


async def next_session_for(now: datetime) -> date:
    """The session a desk run at `now` prepares for: today if today is a session and the market has not closed yet,
    otherwise the next session."""
    t = now.astimezone(IST)
    d = t.date()
    await load_years([d.year + 1], required=[d.year])
    if is_session(d) and t.time() < SESSION_CLOSE_IST:
        return d
    for _ in range(30):
        d += timedelta(days=1)
        if d.year not in _HOLIDAYS:
            await load_years([], required=[d.year])
        if is_session(d):
            return d
    raise CalendarUnavailable(f"no session within 30 days after {t.date()}")


def latest_published(as_of: datetime, kind: str = "cash") -> date:
    """The latest session whose `kind` end-of-day data is published at `as_of` (cash 19:30 IST, F&O 22:45 IST)."""
    d = as_of.astimezone(IST).date()
    for _ in range(20):
        try:
            if is_session(d) and published_at(d, kind) <= as_of:
                return d
        except CalendarUnavailable as e:
            raise DataUnavailable(str(e)) from e
        d -= timedelta(days=1)
    raise DataUnavailable(f"no {kind} session published in the 20 days before {as_of.isoformat()}")
