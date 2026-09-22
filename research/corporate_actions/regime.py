"""regime_break_mask() and regime_segments() -- PRD §37.5.

These are the two helpers other packages (research.charting, research.costs, ...) call so
that no rolling window, pattern, or validation run spans a confirmed demerger:

  regime_break_mask(symbol, dates)
      Which of `dates` fall within T-5..T+5 TRADING SESSIONS of a confirmed demerger's
      ex_date, counted on the symbol's OWN bar dates (not the calendar and not any other
      symbol's session count -- two symbols can have different missing dates, see
      research.charting.bars). Used to exclude the buffer from "ordinary validation"
      (§37.5) even in code that does not otherwise care about regime segmentation.

  regime_segments(symbol, bars)
      Splits `bars` into pre/post regimes at each confirmed demerger's ex_date, so a
      caller that iterates the returned list and computes within each segment separately
      can never have a rolling window or pattern straddle the event -- a stronger,
      structural version of the same rule.

Both default to the on-disk confirmed event list (data/demergers.csv via events.py) but
accept an explicit `events` argument so callers/tests can supply a synthetic list without
touching the stored CSV. Only confirmed demergers (category == "DEMERGER", verified ==
True) are ever used -- see events.events_for_symbol.

Note on the OTHER sealed window: research.charting.research_window's 2023-01-01..
2024-07-31 out-of-sample block is a different rule (blocks RESEARCH EVALUATION from
touching that period) and is not enforced here. Several confirmed demergers fall inside
it (e.g. RELIANCE 2023-07-20) -- that is fine: this module answers "did a demerger happen
here", not "may this window be used for a backtest", and a caller doing research
evaluation already goes through research_window's own guard for that separate question.
"""
from __future__ import annotations

from typing import Iterable, Sequence

import numpy as np
import pandas as pd

from research.corporate_actions.config import CONFIG
from research.corporate_actions.events import DemergerEvent, events_for_symbol


def _unique_sorted_timestamps(dates: Sequence) -> np.ndarray:
    ts = pd.to_datetime(pd.Series(list(dates))).dt.normalize()
    return np.array(sorted(ts.unique()))


def _anchor_index(unique_dates: np.ndarray, ex_date_ts: pd.Timestamp) -> int:
    """Index into `unique_dates` (sorted, ascending) to treat as session T0 for an event
    whose ex_date is `ex_date_ts`. Exact match wins; otherwise anchors to whichever of the
    nearest available sessions before/after ex_date is closer (a symbol can be suspended
    or simply have no bar exactly on the exchange's ex-date -- see e.g. UEL 2024-05-22,
    whose next bar is 2024-05-27)."""
    pos = int(np.searchsorted(unique_dates, ex_date_ts))
    if pos < len(unique_dates) and unique_dates[pos] == ex_date_ts:
        return pos
    if pos == 0:
        return 0
    if pos >= len(unique_dates):
        return len(unique_dates) - 1
    before, after = unique_dates[pos - 1], unique_dates[pos]
    return pos - 1 if (ex_date_ts - before) <= (after - ex_date_ts) else pos


def regime_break_mask(
    symbol: str,
    dates: Sequence,
    *,
    events: Iterable[DemergerEvent] | None = None,
    config: dict | None = None,
) -> np.ndarray:
    """Boolean array, same length and order as `dates` (duplicates and out-of-order input
    preserved -- research.charting.bars does not sort or dedup), True where that date falls
    within the configured T-5..T+5 session window of any confirmed demerger for `symbol`.
    A symbol with no confirmed demerger returns an all-False array of the same length.
    """
    cfg = CONFIG if config is None else config
    before = cfg["regime_break_sessions_before"]
    after = cfg["regime_break_sessions_after"]

    relevant = events_for_symbol(symbol, events)
    input_ts = pd.to_datetime(pd.Series(list(dates))).dt.normalize()
    if not relevant:
        return np.zeros(len(input_ts), dtype=bool)

    unique_dates = _unique_sorted_timestamps(dates)
    break_dates: set = set()
    for event in relevant:
        ex_ts = pd.Timestamp(event.ex_date)
        anchor = _anchor_index(unique_dates, ex_ts)
        lo = max(0, anchor - before)
        hi = min(len(unique_dates) - 1, anchor + after)
        break_dates.update(unique_dates[lo:hi + 1].tolist())

    return input_ts.isin(break_dates).to_numpy()


def regime_segments(
    symbol: str,
    bars: pd.DataFrame,
    *,
    events: Iterable[DemergerEvent] | None = None,
    date_column: str = "date",
) -> list[pd.DataFrame]:
    """Split `bars` into chronological pre/post regimes at each confirmed demerger's
    ex_date for `symbol`: N confirmed events produce N+1 segments (each `reset_index
    (drop=True)`, together they reconstitute `bars` exactly with no row duplicated or
    dropped). A symbol with no confirmed demerger returns `[bars]` unchanged (one regime).
    The split boundary is ex_date itself (bars before ex_date are "pre", bars from ex_date
    onward are "post") -- narrower than the T-5..T+5 buffer regime_break_mask excludes from
    ordinary validation; a caller wanting both structural separation AND the buffer
    excluded combines this with regime_break_mask.
    """
    relevant = events_for_symbol(symbol, events)
    if not relevant:
        return [bars.reset_index(drop=True)]

    col = pd.to_datetime(bars[date_column]).dt.normalize()
    boundaries = [pd.Timestamp(e.ex_date) for e in relevant]

    segments: list[pd.DataFrame] = []
    lower = None
    for boundary in boundaries:
        seg_mask = (col < boundary) if lower is None else ((col >= lower) & (col < boundary))
        segments.append(bars.loc[seg_mask].reset_index(drop=True))
        lower = boundary
    segments.append(bars.loc[col >= lower].reset_index(drop=True))
    return segments
