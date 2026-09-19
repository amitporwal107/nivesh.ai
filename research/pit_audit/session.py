"""Timestamps, precision, NSE trading calendar and decision-time semantics (plan §3).

- NSE timestamps are parsed in IST with an explicit precision ("second", "minute", "day"). A date without a time is
  never promoted to a time of day.
- The trading calendar is built from certified Kite Nifty 500 index daily bars; dates outside it are UNKNOWN,
  never assumed to be trading days.
- Decision cutoffs: eod → session 15:30 IST; next_open → session 09:14 IST; intraday / bar_5m → the close time of the
  last completed bar used.
"""
from __future__ import annotations

import csv
import datetime as dt
import re
from typing import Optional

from contracts import IST

CALENDAR_FILE = "/app/research/phase1/nifty500_index_daily.csv"
_FORMATS = (("%d-%b-%Y %H:%M:%S", "second"), ("%d-%b-%Y %H:%M", "minute"), ("%d-%m-%Y %H:%M:%S", "second"),
            ("%d-%m-%Y %H:%M", "minute"), ("%d-%b-%Y", "day"), ("%d-%m-%Y", "day"), ("%Y-%m-%d", "day"))
_FILENAME_TS = re.compile(r"_(\d{2})(\d{2})(\d{4})(\d{2})(\d{2})(\d{2})[_.]")
EOD_CUTOFF, NEXT_OPEN_CUTOFF = dt.time(15, 30), dt.time(9, 14)


def parse_nse_ts(s) -> tuple[Optional[dt.datetime], Optional[str]]:
    """'31-Oct-2024 20:36:01' → (aware IST datetime, 'second'); '20-AUG-2026' → (midnight IST, 'day')."""
    if s is None:
        return None, None
    txt = str(s).strip()
    if not txt or txt in ("-", "null", "None"):
        return None, None
    for fmt, precision in _FORMATS:
        try:
            t = dt.datetime.strptime(txt.title() if "%b" in fmt else txt, fmt)
            return t.replace(tzinfo=IST), precision
        except ValueError:
            continue
    return None, None


def filename_ts(url: Optional[str]) -> Optional[dt.datetime]:
    """NSE document names embed a creation time as _ddmmyyyyHHMMSS_ / _ddmmyyyyHHMMSS.xml, returned AS WRITTEN.

    F-3: the XBRL .xml names use a 12-hour clock with no AM/PM marker (35,135 listed filings: hour never > 12, equal
    to the broadcast time or exactly 12 h earlier), so the value is ambiguous unless `filename_ts_precision` says
    "second". Never use it as a public-availability time.
    """
    if not url:
        return None
    m = _FILENAME_TS.search(url)
    if not m:
        return None
    d, mo, y, H, M, S = (int(x) for x in m.groups())
    try:
        return dt.datetime(y, mo, d, H, M, S, tzinfo=IST)
    except ValueError:
        return None


def filename_ts_precision(url: Optional[str]) -> Optional[str]:
    """"second" only when the hour proves a 24-hour clock (13-23 or 00); otherwise "ambiguous_12h"."""
    t = filename_ts(url)
    if t is None:
        return None
    return "second" if t.hour > 12 or t.hour == 0 else "ambiguous_12h"


def filename_ts_candidates(url: Optional[str]) -> list[dt.datetime]:
    """Every clock reading the name is consistent with (one if unambiguous, two if 12-hour)."""
    t = filename_ts(url)
    if t is None:
        return []
    if filename_ts_precision(url) == "second":
        return [t]
    return [t, t + dt.timedelta(hours=12)] if t.hour < 12 else [t - dt.timedelta(hours=12), t]


class TradingCalendar:
    def __init__(self, sessions: list[dt.date]):
        self.sessions = sorted(set(sessions))
        self._set = set(self.sessions)
        self.first, self.last = (self.sessions[0], self.sessions[-1]) if self.sessions else (None, None)

    @classmethod
    def from_kite_index(cls, path: str = CALENDAR_FILE) -> "TradingCalendar":
        with open(path) as f:
            return cls([dt.date.fromisoformat(r["date"][:10]) for r in csv.DictReader(f)])

    def covers(self, d: dt.date) -> bool:
        return self.first is not None and self.first <= d <= self.last

    def is_session(self, d: dt.date) -> Optional[bool]:
        return (d in self._set) if self.covers(d) else None  # None = unknown, outside the certified calendar

    def next_session(self, d: dt.date, inclusive: bool = False) -> Optional[dt.date]:
        for s in self.sessions:
            if s > d or (inclusive and s == d):
                return s
        return None  # beyond the calendar: unknown


def decision_at(frequency: str, session: dt.date, bar_close: Optional[dt.datetime] = None) -> dt.datetime:
    """Default decision timestamp for a model decision in `session`."""
    if frequency == "eod":
        return dt.datetime.combine(session, EOD_CUTOFF, tzinfo=IST)
    if frequency == "next_open":
        return dt.datetime.combine(session, NEXT_OPEN_CUTOFF, tzinfo=IST)
    if frequency in ("intraday", "bar_5m"):
        if bar_close is None or bar_close.tzinfo is None:
            raise ValueError("intraday decisions need the aware close time of the last completed bar")
        return bar_close
    raise ValueError(f"unknown feature_frequency {frequency!r}")


def first_usable_session(available_at: dt.datetime, frequency: str, cal: TradingCalendar,
                         margin: dt.timedelta = dt.timedelta(minutes=5)) -> Optional[dt.date]:
    """The first session in which a decision of `frequency` may use information available at `available_at`.

    eod / next_open: the first session whose default decision time is >= available_at + margin (inclusive).
    intraday / bar_5m: the same session if available_at + margin falls before that session's 15:30 close
    (usable from the first bar closing after it), otherwise the next session. None = beyond the calendar (unknown).
    """
    if available_at.tzinfo is None:
        raise ValueError("naive availability timestamp")
    t = available_at.astimezone(IST) + margin
    if frequency in ("eod", "next_open"):
        d = cal.next_session(t.date(), inclusive=True)
        while d is not None and t > decision_at(frequency, d):
            d = cal.next_session(d)
        return d
    if frequency in ("intraday", "bar_5m"):
        d = cal.next_session(t.date(), inclusive=True)
        if d == t.date() and t.time() >= EOD_CUTOFF:
            d = cal.next_session(d)
        return d
    raise ValueError(f"unknown feature_frequency {frequency!r}")
