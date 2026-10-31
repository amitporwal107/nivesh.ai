"""Forward outcomes of a signal, the cost model and the time splits."""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional, Sequence, Tuple

HORIZONS = (1, 3, 5, 10, 20)

# An ASSUMED research cost, percent of notional for a round trip in a stock future (one entry and one exit). It is a stand-in until the
# strategy engine's cost model is completed: it is NOT a tax computation. Base: statutory charges (STT on the sell side, exchange fees, stamp
# duty, GST on fees) about 0.03%, brokerage about 0.02%, slippage and spread about 0.10%. Stress doubles it.
COSTS = {
    "version": "research-cost-v0", "round_trip_pct_base": 0.15, "round_trip_pct_stress": 0.30,
    "basis": "assumed percent of notional per round trip in a stock future; statutory about 0.03, brokerage about 0.02, slippage and spread about 0.10; not a tax computation",
}


def price_index(adj_rows: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Dict[str, Tuple[float, float]]]:
    """symbol -> {YYYY-MM-DD: (adjusted open, adjusted close)}. A row with a missing or non-positive price is left out, never zero-filled."""
    out: Dict[str, Dict[str, Tuple[float, float]]] = {}
    for sym, rows in adj_rows.items():
        d: Dict[str, Tuple[float, float]] = {}
        for r in rows:
            o, c, day = r.get("adj_open"), r.get("adj_close"), str(r.get("as_of_date") or "")[:10]
            if isinstance(o, (int, float)) and isinstance(c, (int, float)) and o > 0 and c > 0 and day:
                d[day] = (float(o), float(c))
        out[sym.upper()] = d
    return out


def forward_return(index: Dict[str, Dict[str, Tuple[float, float]]], symbol: str, sessions: Sequence[str], i: int, h: int) -> Optional[float]:
    """Percent return of a LONG entered at the OPEN of session i+1 (the first executable price after an end-of-day signal on session i) and
    exited at the CLOSE of session i+h. None when the window runs past the data or either price is missing."""
    if h < 1 or i + h >= len(sessions):
        return None
    px = index.get(symbol.upper())
    if not px:
        return None
    entry, exit_ = px.get(sessions[i + 1]), px.get(sessions[i + h])
    if not entry or not exit_:
        return None
    return (exit_[1] / entry[0] - 1.0) * 100.0


def point_in_time_row(rows: Sequence[Dict[str, Any]], day: str) -> Optional[Dict[str, Any]]:
    """The newest feature row dated on or before `day` (rows ascending by `as_of_date`). Never a later one."""
    best = None
    for r in rows:
        d = str(r.get("as_of_date") or "")[:10]
        if d and d <= day:
            best = r
        elif d > day:
            break
    return best


def split_bounds(first: int, last: int, fractions: Tuple[float, float, float] = (0.6, 0.2, 0.2)) -> Dict[str, Tuple[int, int]]:
    """Signal-session index ranges [start, end) for discovery, validation and test, in time order, over indices first..last inclusive."""
    n = last - first + 1
    a = first + int(round(n * fractions[0]))
    b = a + int(round(n * fractions[1]))
    return {"discovery": (first, a), "validation": (a, b), "test": (b, last + 1)}


def split_of(i: int, h: int, bounds: Dict[str, Tuple[int, int]], last_session_index: int) -> Optional[str]:
    """The split a signal on session i with horizon h belongs to, or None if its forward window (sessions i+1 .. i+h) leaves that split. The
    test split's window may run to the end of the data; the earlier splits' windows must stay inside them, so no outcome peeks into the next split."""
    for name, (lo, hi) in bounds.items():
        if lo <= i < hi:
            end = last_session_index if name == "test" else hi - 1
            return name if i + h <= end else None
    return None
