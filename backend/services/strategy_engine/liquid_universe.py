"""Point-in-time liquid EQ universe, rule `liquid-eq-v1` (Phase 4.2: a survivorship-free backtest universe).

On each session d, a symbol is a MEMBER when all of these hold, read from data up to and including d only:

  1. it has a series-EQ bar on d with a close and a volume (it was priced on d), and that raw close is at least
     MIN_CLOSE_RS (₹20);
  2. among the WINDOW_SESSIONS (30) sessions of the calendar ending at d, it has at least BARS (20) EQ bars with a close
     and a volume, and the MEDIAN of close × volume (₹ traded value) over its latest BARS of them is at least
     MIN_MEDIAN_TRADED_VALUE_RS (₹10 crore);
  3. its symbol does not name an ETF (ends in BEES or ETF).

Why this shape (docs/ai_research/P4_POINT_IN_TIME_UNIVERSE.md):
  * The liquidity floor and the price floor are the Phase 4.3 study's (docs/ai_research/P4_ADX_RS_PREREGISTRATION.md §3:
    a 20-session median traded value of ₹10 crore, a close of ₹20, series EQ, ETFs out). The study's "220 prior sessions"
    was a feature warm-up for its own scorer; a DSL backtest reads stored features, so it is not part of this rule.
  * The median is over the symbol's own last 20 bars (as in the study), bounded to the last 30 sessions so one missing
    price session, or a short suspension, does not empty the universe, and membership on d never depends on where a
    backtest window starts. A symbol with fewer than 20 bars in those 30 sessions (a new listing, a long suspension) is out.
  * Survivorship: a symbol is a member on every date it traded and passed, including symbols that were later delisted,
    merged or renamed; nothing is read from today's lists. Traded value is close × volume on the RAW bar, which a split or
    bonus does not change (the price falls by the factor the volume rises by), so no adjustment is needed.
  * ETFs are excluded by name only: the warehouse's per-date ETF flag (nidp.security_reference_daily.is_etf) is not
    served by the data API per date. An ETF whose symbol does not end in BEES or ETF is not caught (counted on staging in
    the PR's data test).

Pure: no I/O. The providers (market_data.py) fetch the bars and call `membership`.
"""
from __future__ import annotations

import statistics
from collections import deque
from datetime import date
from typing import Any, Deque, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

VERSION = "liquid-eq-v1"
REF = "LIQUID_EQ"                       # the DSL universe {"type": "market", "ref": "LIQUID_EQ"}
SERIES = "EQ"
MIN_CLOSE_RS = 20.0
MIN_MEDIAN_TRADED_VALUE_RS = 1e8        # ₹10 crore
BARS = 20
WINDOW_SESSIONS = 30
LOOKBACK_SESSIONS = WINDOW_SESSIONS - 1  # sessions before the first wanted date that a provider must also read
ETF_SUFFIXES = ("BEES", "ETF")

LABEL = "All liquid NSE stocks (point-in-time)"
DESCRIPTION = ("Every NSE EQ stock priced on the date with a 20-session median traded value of at least ₹10 crore and a close of "
               "at least ₹20, from data up to that date (liquid-eq-v1). Includes stocks later delisted: no survivorship bias.")


def rule() -> Dict[str, Any]:
    """The rule as recorded on a backtest run (metrics.universe_rule)."""
    return {"version": VERSION, "ref": REF, "series": SERIES, "min_close_rs": MIN_CLOSE_RS,
            "min_median_traded_value_rs": MIN_MEDIAN_TRADED_VALUE_RS, "bars": BARS, "window_sessions": WINDOW_SESSIONS,
            "traded_value": "raw close x volume", "etf_exclusion": "symbol ends in " + " or ".join(ETF_SUFFIXES),
            "point_in_time": "each date's members are computed from bars on or before that date only",
            "source": "services/strategy_engine/liquid_universe.py"}


def is_etf_name(symbol: str) -> bool:
    s = (symbol or "").upper()
    return any(s.endswith(x) for x in ETF_SUFFIXES)


def _num(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        out = float(v)
    except (TypeError, ValueError):
        return None
    return out if out == out and out not in (float("inf"), float("-inf")) else None


def _bar(row: Mapping[str, Any]) -> Optional[Tuple[str, float, float]]:
    """(symbol, close, traded value) of a usable EQ bar, else None."""
    if str(row.get("series") or SERIES).upper() != SERIES:
        return None
    sym = row.get("symbol")
    close = _num(row.get("close_price", row.get("close")))
    vol = _num(row.get("volume"))
    if not sym or close is None or close <= 0 or vol is None or vol < 0:
        return None
    return str(sym).upper(), close, close * vol


def membership(sessions: Sequence[date], bars_by_session: Mapping[date, Iterable[Mapping[str, Any]]],
               wanted: Optional[Iterable[date]] = None) -> Tuple[Dict[date, Set[str]], Dict[str, Any]]:
    """({session: members} for each wanted session, report).

    `sessions` is the trading calendar, ascending, covering at least LOOKBACK_SESSIONS before the first wanted date (fewer
    only at the start of the data). `bars_by_session[d]` holds that session's bhavcopy rows: {symbol, series, close_price
    (or close), volume}; rows of other series are ignored, a duplicate EQ row for a symbol keeps the first. `wanted`
    defaults to every session. The report lists sessions inside a wanted window that had no rows at all."""
    sessions = sorted(set(sessions))
    want = set(sessions if wanted is None else wanted)
    hist: Dict[str, Deque[Tuple[int, float]]] = {}
    out: Dict[date, Set[str]] = {}
    empty: List[date] = []
    first_wanted = min((i for i, d in enumerate(sessions) if d in want), default=None)
    for i, d in enumerate(sessions):
        today: Dict[str, float] = {}
        rows = bars_by_session.get(d) or []
        any_row = False
        for row in rows:
            any_row = True
            b = _bar(row)
            if b is None or b[0] in today:
                continue
            sym, close, tv = b
            today[sym] = close
            hist.setdefault(sym, deque()).append((i, tv))
        if not any_row and first_wanted is not None and i >= first_wanted - LOOKBACK_SESSIONS:
            empty.append(d)
        if d not in want:
            continue
        lo = i - WINDOW_SESSIONS + 1
        members: Set[str] = set()
        for sym, close in today.items():
            if close < MIN_CLOSE_RS or is_etf_name(sym):
                continue
            dq = hist[sym]
            while dq and dq[0][0] < lo:
                dq.popleft()
            if len(dq) < BARS:
                continue
            last = [tv for _, tv in list(dq)[-BARS:]]
            if statistics.median(last) >= MIN_MEDIAN_TRADED_VALUE_RS:
                members.add(sym)
        out[d] = members
    sizes = [len(v) for v in out.values()]
    report = {"sessions_without_prices": [d.isoformat() for d in empty],
              "members_per_session": ({"min": min(sizes), "median": statistics.median(sizes), "max": max(sizes)} if sizes else None),
              "distinct_members": len(set().union(*out.values())) if out else 0}
    return out, report


def calendar_with_lookback(all_sessions: Sequence[date], from_date: date, to_date: date) -> Tuple[List[date], List[date]]:
    """(the sessions to read: LOOKBACK_SESSIONS before from_date plus the window, the window's sessions)."""
    ordered = sorted(set(all_sessions))
    window = [d for d in ordered if from_date <= d <= to_date]
    before = [d for d in ordered if d < from_date][-LOOKBACK_SESSIONS:]
    return before + window, window
