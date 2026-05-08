"""IST market hours utilities for intraday services.

All times are in IST (UTC+5:30).

Intraday ingestion window: 08:30–16:30
  - Pre-market polling starts at 08:30 (NSE pre-open is 09:00)
  - Buffer until 16:30 to catch late filings after close (15:30)

Services that run on 1-min Cloud Scheduler crons should call
`is_intraday_window()` at startup and exit immediately when False.
This keeps Cloud Run costs near zero outside hours while the Scheduler
continues to fire (cheap noop vs stopping/re-creating the cron).

Usage:
    from nidp.shared.market_hours import is_intraday_window
    if not is_intraday_window():
        logger.info("outside market hours — exiting")
        return
"""
from __future__ import annotations

from datetime import datetime, time, timezone, timedelta
from typing import Optional

_IST = timezone(timedelta(hours=5, minutes=30))

# Intraday ingestion window (inclusive)
_INTRADAY_START = time(8, 30)
_INTRADAY_END   = time(16, 30)

# Strict market session (NSE 09:15 – 15:30)
_SESSION_START  = time(9, 15)
_SESSION_END    = time(15, 30)


def ist_now() -> datetime:
    """Current time in IST."""
    return datetime.now(tz=_IST)


def is_intraday_window(dt: Optional[datetime] = None) -> bool:
    """True if within 08:30–16:30 IST on a weekday."""
    t = (dt or ist_now())
    if t.weekday() >= 5:          # Saturday=5, Sunday=6
        return False
    return _INTRADAY_START <= t.time() <= _INTRADAY_END


def is_market_session(dt: Optional[datetime] = None) -> bool:
    """True if within the NSE continuous trading session (09:15–15:30)."""
    t = (dt or ist_now())
    if t.weekday() >= 5:
        return False
    return _SESSION_START <= t.time() <= _SESSION_END


def is_trading_day(dt: Optional[datetime] = None) -> bool:
    """True if today is Mon–Fri (does not account for NSE holidays)."""
    return (dt or ist_now()).weekday() < 5


def minutes_to_open(dt: Optional[datetime] = None) -> int:
    """Minutes until intraday window opens (negative when already open)."""
    t = dt or ist_now()
    open_today = t.replace(
        hour=_INTRADAY_START.hour,
        minute=_INTRADAY_START.minute,
        second=0, microsecond=0,
    )
    return int((open_today - t).total_seconds() / 60)
