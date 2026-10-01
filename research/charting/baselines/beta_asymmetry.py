"""Directional beta: how a stock behaves when the market rises versus when it falls.

    Nifty +1% -> Stock +1.8%        Nifty +1% -> Stock +0.5%
    Nifty -1% -> Stock -0.3%        Nifty -1% -> Stock -1.7%

CONVENTIONAL BETA SCORES THESE IDENTICALLY. Both are roughly beta 1.05 on a single regression, and
they are opposite animals: the first captures upside and shrugs off drawdowns, the second does the
reverse. One regression through the origin cannot see the difference, so it is fitted twice --
once on up-market days, once on down-market days.

POINT-IN-TIME. Every window ends at the session BEFORE the signal date. A window that includes t
itself would use the very bar whose outcome is being predicted.

THE SEALED HOLE, AGAIN. The index series jumps 2022-12-30 -> 2024-08-01. A 60-session window whose
rows straddle that boundary spans nineteen months of real time, and the regression would silently
mix two unrelated market epochs. Windows are checked in calendar days as well as rows, exactly as
`breadth_momentum` does, and return UNAVAILABLE rather than a number.
"""
from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
from typing import Mapping, Optional, Sequence

INDEX_PATH = Path(__file__).resolve().parents[2] / "index_history" / "data" / "NIFTY_500.csv"

#: Trailing sessions for the regression.
WINDOWS = (60, 120)

#: A 60-session window should span ~90 calendar days. Past this multiple the window crossed a gap.
MAX_SPAN_MULTIPLE = 2.5

#: Each leg needs enough observations to be a regression rather than a line through two points.
MIN_LEG_OBS = 10

#: Maximum days between the end of the estimation window and the date it is applied to. A long
#: weekend or a holiday cluster is fine; the sealed block is not.
MAX_STALENESS_DAYS = 10


def _d(s: str) -> date:
    return date(int(s[:4]), int(s[5:7]), int(s[8:10]))


def load_index_returns(path=None) -> list:
    """`[(date, return), ...]` in date order. The first row has no prior close and is dropped --
    never given a 0.0 return, which would assert the market was flat on a day we cannot measure."""
    rows = []
    with open(path or INDEX_PATH) as fh:
        for r in csv.DictReader(fh):
            try:
                rows.append((r["date"][:10], float(r["close"])))
            except (KeyError, TypeError, ValueError):
                continue
    rows.sort()
    out = []
    for i in range(1, len(rows)):
        prev_c, cur_c = rows[i - 1][1], rows[i][1]
        if prev_c > 0:
            out.append((rows[i][0], cur_c / prev_c - 1.0))
    return out


def _ols_slope(xs: Sequence[float], ys: Sequence[float]) -> Optional[float]:
    """Slope of y on x. Returns None when x has no spread — a vertical scatter has no slope, and
    reporting 0.0 would claim the stock ignores the market."""
    n = len(xs)
    if n < 2:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx <= 1e-18:
        return None
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return sxy / sxx


def _corr(xs: Sequence[float], ys: Sequence[float]) -> Optional[float]:
    n = len(xs)
    if n < 2:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 1e-18 or syy <= 1e-18:
        return None
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return sxy / ((sxx ** 0.5) * (syy ** 0.5))


def rolling_betas(stock_returns: Sequence[tuple], index_by_date: Mapping[str, float]) -> dict:
    """`{date: {beta_up_N, beta_down_N, beta_asym_N, beta_N, corr_N}}` for one symbol.

    `stock_returns` is `[(date, return), ...]` in date order. Only dates present in BOTH series are
    used, so a stock that did not trade on an index day contributes nothing for that day rather
    than a fabricated zero.
    """
    paired = [(d, r, index_by_date[d]) for d, r in stock_returns if d in index_by_date]
    out: dict = {}
    for i in range(len(paired)):
        rec: dict = {}
        for w in WINDOWS:
            for k in ("beta_up", "beta_down", "beta_asym", "beta", "corr"):
                rec[f"{k}_{w}"] = None
            if i < w:
                continue
            win = paired[i - w:i]          # ENDS at i-1: never includes the signal bar itself
            span = (_d(win[-1][0]) - _d(win[0][0])).days
            if span > w * MAX_SPAN_MULTIPLE:
                continue                    # the window itself crossed the sealed gap
            # AND the window must be ADJACENT to the signal date. Checking only the window's own
            # span misses the worse case: at the first post-gap row the window is 60 clean
            # pre-gap sessions, so it passes that check -- and then gets applied to a date
            # NINETEEN MONTHS later. A beta that stale is not a stale beta, it is a different
            # market's beta. Caught by test_a_window_across_the_sealed_gap_is_unavailable.
            if (_d(paired[i][0]) - _d(win[-1][0])).days > MAX_STALENESS_DAYS:
                continue
            sx = [m for _d_, _s, m in win]
            sy = [s for _d_, s, _m in win]
            rec[f"beta_{w}"] = _ols_slope(sx, sy)
            rec[f"corr_{w}"] = _corr(sx, sy)
            up = [(m, s) for _d_, s, m in win if m > 0]
            dn = [(m, s) for _d_, s, m in win if m < 0]
            bu = _ols_slope([m for m, _s in up], [s for _m, s in up]) if len(up) >= MIN_LEG_OBS else None
            bd = _ols_slope([m for m, _s in dn], [s for _m, s in dn]) if len(dn) >= MIN_LEG_OBS else None
            rec[f"beta_up_{w}"] = bu
            rec[f"beta_down_{w}"] = bd
            # The whole point: positive means it captures more upside than downside.
            rec[f"beta_asym_{w}"] = (bu - bd) if (bu is not None and bd is not None) else None
        out[paired[i][0]] = rec
    return out


def feature_names() -> list:
    return [f"{k}_{w}" for w in WINDOWS
            for k in ("beta_up", "beta_down", "beta_asym", "beta", "corr")]


def features_for(symbol: str, signal_date: Optional[str], index: Mapping) -> dict:
    rec = (index.get(symbol) or {}).get((signal_date or "")[:10]) or {}
    return {name: rec.get(name) for name in feature_names()}
