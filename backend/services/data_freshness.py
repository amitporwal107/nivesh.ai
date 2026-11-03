"""One freshness rule for the inputs a decision depends on (study §6 item 4.3; Phase 1 item 1.4).

Every input that a decision reads from outside its own request is judged the same way and reported as one record:

    {source, as_of, age_sessions, budget, ok, reason}

    source        where the value came from, in words a reviewer can look up
    as_of         the date the value describes (ISO), or None when the source gave none
    age_sessions  NSE sessions between `as_of` and the reference session (0 when as_of is on or after it); None when
                  the value has no date (a classification such as a sector) or no value was read
    budget        the most sessions old the value may be and still be used; None for an undated classification
    ok            True only when a value was read AND (it is undated, or age_sessions <= budget)
    reason        why it is not ok, in words; None when ok

The reference session is the newest session whose end-of-day data must exist when a decision is made: the last weekday
strictly before today in IST. Today's NSE bhavcopy lands in the evening, so until then yesterday's close is the newest
any end-of-day source can hold; counting from today would call every morning's data stale.

The session calendar is weekdays (Monday to Friday). NSE weekday holidays are not subtracted, because the backend has no
holiday list it can read without the data platform (nidp.nse_holidays lives in the warehouse). The effect is one-sided
and stated: on the session after a weekday holiday a value is counted one session older than it is, so a budget of N
sessions is effectively N-1 on that day. Budgets are set with that slack (risk inputs use 2).

Used by the universal risk service (services/risk_gate/service.py) for the last close, the sector, the market state
(India VIX and regime) and the F&O marks of open structures. A later phase extends it to the scanner and regime-fit,
which is why it knows nothing about any one source.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Optional

FRESHNESS_VERSION = "freshness-v1"
IST = timezone(timedelta(hours=5, minutes=30))
CALENDAR_NOTE = ("weekday calendar (Mon-Fri); NSE weekday holidays are not subtracted, so the session after a holiday "
                 "counts one session older")


def ist_today(now: Optional[datetime] = None) -> date:
    return (now or datetime.now(timezone.utc)).astimezone(IST).date()


def previous_session(day: date) -> date:
    """The last weekday strictly before `day`."""
    d = day - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def reference_session(now: Optional[datetime] = None) -> date:
    """The newest session whose end-of-day data must exist now: the last weekday before today (IST)."""
    return previous_session(ist_today(now))


def sessions_after(as_of: date, through: date) -> int:
    """Weekdays d with as_of < d <= through (0 when as_of >= through)."""
    if as_of >= through:
        return 0
    days = (through - as_of).days
    weeks, rest = divmod(days, 7)
    count = weeks * 5
    d = as_of + timedelta(days=weeks * 7)
    for _ in range(rest):
        d += timedelta(days=1)
        if d.weekday() < 5:
            count += 1
    return count


def _day(value: Any) -> Optional[date]:
    if isinstance(value, datetime):
        return value.astimezone(IST).date() if value.tzinfo else value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and len(value) >= 10:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def assess(source: str, as_of: Any, *, budget_sessions: int, now: Optional[datetime] = None,
           have_value: bool = True) -> Dict[str, Any]:
    """A dated input: ok when a value was read and its as-of date is at most `budget_sessions` sessions old."""
    day = _day(as_of)
    out: Dict[str, Any] = {"source": source, "as_of": day.isoformat() if day else None, "age_sessions": None,
                           "budget": budget_sessions, "ok": False, "reason": None, "version": FRESHNESS_VERSION}
    if not have_value:
        out["reason"] = "no value could be read"
        return out
    if day is None:
        out["reason"] = "the source gave no as-of date"
        return out
    ref = reference_session(now)
    age = sessions_after(day, ref)
    out["age_sessions"] = age
    if age > budget_sessions:
        out["reason"] = (f"as of {day.isoformat()}, {age} sessions before {ref.isoformat()}; the budget is "
                         f"{budget_sessions}")
        return out
    out["ok"] = True
    return out


def known(source: str, value: Any, *, as_of: Any = None, reason_missing: str = "no value could be read") -> Dict[str, Any]:
    """An undated classification (a sector): ok when a value was read; its age is not judged."""
    day = _day(as_of)
    ok = value is not None and value != ""
    return {"source": source, "as_of": day.isoformat() if day else None, "age_sessions": None, "budget": None,
            "ok": ok, "reason": None if ok else reason_missing, "version": FRESHNESS_VERSION}


def unavailable(source: str, reason: str, *, budget_sessions: Optional[int] = None) -> Dict[str, Any]:
    """An input whose source could not be read at all."""
    return {"source": source, "as_of": None, "age_sessions": None, "budget": budget_sessions, "ok": False,
            "reason": reason, "version": FRESHNESS_VERSION}
