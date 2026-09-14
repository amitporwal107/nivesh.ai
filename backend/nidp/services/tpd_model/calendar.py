"""NSE cash-market session arithmetic for 'the next session after T'."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable, Mapping, Optional


class CalendarUnknownError(RuntimeError):
    """The holiday calendar does not reach far enough to name the next session."""


def cm_holidays(rows: Iterable[Mapping]) -> set[date]:
    """Holidays for the cash market only. nse_holidays carries every segment, and a commodity or
    currency holiday is an ordinary equity session."""
    return {r["holiday_date"] for r in rows if r["segment"] == "CM"}


def next_trading_day(
    d: date,
    holidays: set[date],
    special_sessions: frozenset[date] | set[date] = frozenset(),
    muhurat_sessions: frozenset[date] | set[date] = frozenset(),
    known_until: Optional[date] = None,
) -> tuple[date, list[date]]:
    """First session after `d`, plus the weekday holidays skipped on the way.

    Weekend special sessions (Budget days) count as sessions. Muhurat sessions are never a target: an
    hour-long evening session is not comparable to a full day. Past `known_until` the calendar is not
    trusted to say a weekday is a session, so this refuses rather than guessing.
    """
    skipped: list[date] = []
    cur = d
    while True:
        cur += timedelta(days=1)
        if known_until is not None and cur > known_until:
            raise CalendarUnknownError(f"holiday calendar ends {known_until}; cannot name the session after {d}")
        if cur in muhurat_sessions:
            if cur.weekday() < 5:
                skipped.append(cur)
            continue
        if cur in special_sessions:
            return cur, skipped
        if cur.weekday() >= 5:
            continue
        if cur in holidays:
            skipped.append(cur)
            continue
        return cur, skipped
