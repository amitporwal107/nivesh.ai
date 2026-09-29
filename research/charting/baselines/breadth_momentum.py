"""Breadth CHANGE, not breadth level (owner, 2026-09-29).

    Day -10   20DMA breadth = 42%
    Day -5                    48%
    Day -1                    57%
    Today                     63%

is a completely different market from 63% flat for weeks -- and the model currently cannot tell
them apart, because B4 carries only the level. This adds the derivative.

THE TRAP THIS MODULE EXISTS TO AVOID
------------------------------------
The breadth series has a HOLE. `BREADTH_UNIVERSE.csv` jumps 2022-12-30 -> 2024-08-01: the sealed
block contains zero rows, by construction. A naive "value now minus value 10 rows ago" across that
boundary computes a NINETEEN-MONTH change and labels it a 10-session move. It would not error, it
would not look wrong, and it would be the single largest "breadth momentum" reading in the
dataset -- landing exactly at the start of the post-sealed segment, where a model would happily
learn it.

So every lookback is checked in CALENDAR days as well as rows. A window whose span exceeds
`MAX_SESSION_GAP_DAYS` is UNAVAILABLE, never a number.
"""
from __future__ import annotations

import csv
from datetime import date, timedelta
from pathlib import Path
from typing import Mapping, Optional

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "index_history" / "data" / "BREADTH_UNIVERSE.csv"

#: A 10-session lookback should span ~14 calendar days. Anything past this means the window
#: crossed a gap -- a holiday cluster is fine, the sealed block is not.
MAX_SESSION_GAP_DAYS = 2.5

#: Lookbacks, in trading rows.
WINDOWS = (5, 10, 20)

#: The level fields worth differencing. Counts (advancers, new highs) are universe-size dependent;
#: the normalised shares and the ratio are comparable across time.
LEVELS = ("pct_above_sma50", "pct_above_sma200", "advance_decline_ratio")


def _f(v) -> Optional[float]:
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def load_series(path=None) -> list:
    """`[{date, pct_above_sma50, ...}, ...]` in date order, blanks preserved as None.

    A blank cell is NOT zero. `breadth.py` leaves `pct_above_sma200` blank until 200 names have a
    full trailing window; reading that as 0% would say "no stock in the market is above its
    200-day average", which is a dramatic and false claim.
    """
    rows = []
    with open(path or DEFAULT_PATH) as fh:
        for r in csv.DictReader(fh):
            d = r.get("date")
            if not d:
                continue
            rec = {"date": d}
            for k in LEVELS:
                rec[k] = _f(r.get(k))
            rows.append(rec)
    rows.sort(key=lambda r: r["date"])
    return rows


def _days_between(a: str, b: str) -> int:
    ya, ma, da = int(a[:4]), int(a[5:7]), int(a[8:10])
    yb, mb, db = int(b[:4]), int(b[5:7]), int(b[8:10])
    return abs((date(yb, mb, db) - date(ya, ma, da)).days)


def build_index(path=None) -> dict:
    """`{date: {feature: value}}` — momentum and acceleration per date, gap-guarded.

    momentum_N      = level(t) - level(t-N)        "how much has participation changed"
    acceleration_N  = momentum_N(t) - momentum_N(t-N)   "is that change speeding up or fading"
    """
    series = load_series(path)
    by_date: dict = {}
    mom_history: dict = {}

    for i, row in enumerate(series):
        out: dict = {}
        for field in LEVELS:
            cur = row.get(field)
            for w in WINDOWS:
                mname = f"{field}_mom_{w}"
                aname = f"{field}_accel_{w}"
                out[mname] = None
                out[aname] = None
                if cur is None or i < w:
                    continue
                prev_row = series[i - w]
                prev = prev_row.get(field)
                if prev is None:
                    continue
                span = _days_between(prev_row["date"], row["date"])
                if span > w * MAX_SESSION_GAP_DAYS:
                    continue          # the window crossed a gap -- UNAVAILABLE, never a number
                out[mname] = cur - prev
                # acceleration compares this momentum with the momentum one window ago
                prior = mom_history.get((field, w, i - w))
                if prior is not None:
                    out[aname] = out[mname] - prior
            mom_history[(field, w, i)] = out.get(f"{field}_mom_{w}")
        by_date[row["date"]] = out
    return by_date


def feature_names() -> list:
    return [f"{f}_{kind}_{w}" for f in LEVELS for w in WINDOWS for kind in ("mom", "accel")]


def features_for(signal_date: Optional[str], index: Mapping) -> dict:
    """The B4b block for one row. A date absent from the series yields all-None, which the ladder
    imputes to the column mean -- not to zero, which would assert 'breadth did not change'."""
    rec = index.get((signal_date or "")[:10]) or {}
    return {name: rec.get(name) for name in feature_names()}
