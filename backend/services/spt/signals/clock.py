"""Time rules shared by slice A (signals, opportunities, outcomes). Pure: no I/O; `now` is always passed in.

Session: NSE cash market, 09:15–15:30 IST, Monday to Friday. NSE weekday holidays are NOT subtracted (the backend has no
holiday list it can read without the data platform; services/data_freshness.py states the same limit), so a window counted
in sessions runs one calendar day longer across a weekday holiday.

Windows (DESIGN.md §4 consolidation_key):
    intraday     the signal's own IST day, until its close (session_close: 15:31 IST, the end of the 15:30 minute)
    positional   from the first signal to the close of the Nth weekday after its IST day
                 (N = SPT_POSITIONAL_WINDOW_SESSIONS, default 5: a Wednesday signal's window ends the next Wednesday)
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, Optional

IST = timezone(timedelta(hours=5, minutes=30))
OPEN, CLOSE = time(9, 15), time(15, 30)
SESSION_END = time(15, 31)
DEFAULT_WINDOW_SESSIONS = 5


def _settings_env() -> Dict[str, str]:
    """os.environ with the admin's market-wide SPT settings written over it (services/spt/settings.overlay)."""
    from services.spt import settings
    return settings.overlay()


def window_sessions(env: Optional[Dict[str, str]] = None) -> int:
    """SPT_POSITIONAL_WINDOW_SESSIONS (1–60), else DEFAULT_WINDOW_SESSIONS."""
    raw = (_settings_env() if env is None else env).get("SPT_POSITIONAL_WINDOW_SESSIONS")
    try:
        n = int(raw) if raw not in (None, "") else DEFAULT_WINDOW_SESSIONS
    except ValueError:
        return DEFAULT_WINDOW_SESSIONS
    return n if 1 <= n <= 60 else DEFAULT_WINDOW_SESSIONS


def parse_ts(value: Any) -> Optional[datetime]:
    """An aware datetime from an ISO string (or datetime); None when missing, unparsable or without a timezone."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str) and value:
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return dt if dt.tzinfo is not None else None


def utc_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def ist_day(dt: datetime) -> date:
    return dt.astimezone(IST).date()


def in_session(dt: datetime) -> bool:
    """09:15:00–15:30:59 IST on a weekday (the scan loop's own minute rule, scan_builder.signals.in_session)."""
    ist = dt.astimezone(IST)
    return ist.weekday() < 5 and (OPEN.hour, OPEN.minute) <= (ist.hour, ist.minute) <= (CLOSE.hour, CLOSE.minute)


def session_close(day: date) -> datetime:
    """The end of `day`'s session, aware: 15:31:00 IST, the end of the 15:30 minute in which the scan loop still records."""
    return datetime.combine(day, SESSION_END, tzinfo=IST)


def add_sessions(day: date, n: int) -> date:
    """The Nth weekday after `day` (n ≥ 0; n = 0 → `day`)."""
    d = day
    for _ in range(max(0, n)):
        d += timedelta(days=1)
        while d.weekday() >= 5:
            d += timedelta(days=1)
    return d


def sessions_between(a: date, b: date) -> int:
    """Weekdays d with a < d ≤ b (negative when b < a)."""
    if b < a:
        return -sessions_between(b, a)
    n, d = 0, a
    while d < b:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return n


def window_until(day: date, horizon: str, sessions: int) -> datetime:
    """The end of the consolidation window that starts on `day` (see the module docstring)."""
    return session_close(day if horizon == "intraday" else add_sessions(day, sessions))
