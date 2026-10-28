"""What counts as current market data on a screen: today's, or the previous NSE trading session's. Nothing older.

Owner rule (2026-10-28): stale F&O or stock data is never shown, in any form; it is today's data or the T-1 snapshot.
Why a rule is needed rather than "the latest row": the data platform answers /fno/{symbol} with that symbol's OWN latest
day, so a stock that left the F&O list (EXIDEIND, last listed 2026-07-28) came back with its July chain as "the latest".
The previous session also still lists the contracts that expired at its close, and NSE's bhavcopy carries the previous
close forward as the `close` of a contract that did not trade that day.

    floor   the previous NSE trading session before today (IST): weekends and NSE CM holidays are skipped, using the data
            platform's holiday list (routes/markets._nse_holiday, cached there). A day before the floor is stale.
            When the holiday list cannot be read a weekday counts as a session, which can only put the floor later
            (stricter): an older day is never let through.
    today   the IST calendar day. A contract expiring before it has expired.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Optional, Tuple

IST = timezone(timedelta(hours=5, minutes=30))
# Days walked back to find the previous session. NSE has never closed for more than four days in a row.
MAX_WALK = 10

HolidayReader = Callable[[date], Awaitable[Tuple[bool, Optional[str]]]]


def _day(v: Any) -> Optional[date]:
    if isinstance(v, datetime):
        return v.astimezone(IST).date() if v.tzinfo else v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, str) and len(v) >= 10:
        try:
            return date.fromisoformat(v[:10])
        except ValueError:
            return None
    return None


@dataclass(frozen=True)
class Window:
    today: date
    floor: date
    calendar_checked: bool

    def current(self, day: Any) -> bool:
        """True for data dated on or after the floor. A missing or unreadable day is never current."""
        d = _day(day)
        return d is not None and d >= self.floor

    def live_expiry(self, expiry: Any) -> bool:
        """True for a contract that has not expired: its expiry is today or later."""
        d = _day(expiry)
        return d is not None and d >= self.today

    def stale_reason(self, what: str, day: Any) -> str:
        d = _day(day)
        last = d.isoformat() if d else "unknown"
        return (f"No current data for {what}: the latest is {last}, older than the previous session "
                f"({self.floor.isoformat()}). Older figures are not shown.")


async def _platform_holiday(day: date) -> Tuple[bool, Optional[str]]:
    from routes.markets import _nse_holiday  # lazy: the route module imports the app's services
    return await _nse_holiday(day)


async def window(now: Optional[datetime] = None, holiday: Optional[HolidayReader] = None) -> Window:
    """Today (IST) and the previous NSE trading session before it."""
    today = (now or datetime.now(IST)).astimezone(IST).date()
    read_holiday = holiday or _platform_holiday
    checked = True
    d = today
    for _ in range(MAX_WALK):
        d -= timedelta(days=1)
        if d.weekday() >= 5:
            continue
        read, name = await read_holiday(d)
        checked = checked and read
        if not name:
            return Window(today=today, floor=d, calendar_checked=checked)
    return Window(today=today, floor=d, calendar_checked=checked)
