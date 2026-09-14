"""What an exchange filing may contribute to a prediction made at 15:30 IST on session T."""
from __future__ import annotations

from datetime import date, datetime, time
from typing import Optional
from zoneinfo import ZoneInfo

import pandas as pd

IST = ZoneInfo("Asia/Kolkata")
CUTOFF = time(15, 30)


def cutoff_ist(T: date) -> datetime:
    return datetime.combine(T, CUTOFF, tzinfo=IST)


def results_flag(events: pd.DataFrame, symbol: str, T: date, event_day: date) -> tuple[Optional[bool], Optional[datetime]]:
    """Whether a results board meeting on `event_day` was known by the 15:30 cutoff on T.

    (True, first intimation time) when intimated at or before the cutoff; (False, None) when no such
    meeting is known by then; (None, None) when the only matching meetings have no intimation time — an
    unknown timestamp stays unknown rather than borrowing a proxy date.
    """
    match = events[(events["symbol"] == symbol) & (events["event_date"] == pd.Timestamp(event_day))]
    if match.empty:
        return False, None
    stamped = match["intimated_at"].dropna()
    known = stamped[stamped <= cutoff_ist(T)]
    if not known.empty:
        return True, known.min()
    if stamped.empty:
        return None, None
    return False, None
