"""Confirmed swing (fractal) pivot detection — PRD §10.1 "Swing Point Detection",
§10.2 `swing_left_bars` / `swing_right_bars`.

Point-in-time rule (PRD §2.2, this package's own contract — see
`research/charting/__init__.py`): a swing pivot at bar `i` requires `right_bars`
bars AFTER it to even be evaluated as a candidate, and is only CONFIRMED once those
bars exist. `swings_as_of(bars, t)` is the PIT-safe entry point every other package
must use: it slices `bars` to `[0, t]` FIRST and only then runs detection, so a
pivot near the end of the visible window that lacks its right-bar context is simply
never produced — not produced-then-filtered, which would already have let the
detector's internal state see bars beyond `t`.

Tie rule (equal highs/lows): when two or more bars in a candidate's window share the
extreme value, the LATEST (right-most / most recent) of those bars is the pivot. A
bar's LEFT neighbours may tie it (`>=` for a high, `<=` for a low); its RIGHT
neighbours must be strictly worse (`>` beaten for a high, `<` beaten for a low). This
means an earlier bar in a tied plateau always loses to a later one (its right window
contains an equal value, which fails the strict-right test), so a plateau never
produces two overlapping pivots for the same extreme. See `test_swings.py`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

from research.charting.config import CONFIG

PivotKind = Literal["HIGH", "LOW"]


@dataclass(frozen=True)
class Pivot:
    """A confirmed swing pivot. Every record carries both the bar it occurred on
    (`pivot_index`/`pivot_date`) and the bar it became knowable at
    (`confirmed_index`/`confirmed_date` = `pivot_index + right_bars`)."""

    kind: PivotKind
    pivot_index: int
    pivot_date: pd.Timestamp
    price: float
    confirmed_index: int
    confirmed_date: pd.Timestamp


def _resolve(left_bars: int | None, right_bars: int | None) -> tuple[int, int]:
    left = CONFIG["swing_left_bars"] if left_bars is None else left_bars
    right = CONFIG["swing_right_bars"] if right_bars is None else right_bars
    if left < 1 or right < 1:
        raise ValueError(f"left_bars/right_bars must be >= 1, got left={left} right={right}")
    return left, right


def find_swings(
    bars: pd.DataFrame,
    *,
    left_bars: int | None = None,
    right_bars: int | None = None,
) -> list[Pivot]:
    """All CONFIRMED swing highs/lows in `bars` (ascending by date, as given).

    Only positions with a full `left_bars`/`right_bars` window inside `bars` are
    even considered — a candidate near either edge of `bars` that lacks enough
    context is not returned. This is what makes `swings_as_of` PIT-safe: it slices
    `bars` down to `[0, t]` and calls this function on the SLICE, so the slice's own
    edge naturally excludes anything not yet confirmable at `t`. This function must
    never be called on a wider frame and have its output filtered afterward — that
    already leaks (the detector would have "seen" the excluded bars while deciding
    ties/extrema even if the final filter discards the record).

    left_bars/right_bars default to `CONFIG["swing_left_bars"]` /
    `CONFIG["swing_right_bars"]`; pass overrides only for tests exercising other
    windows.
    """
    left, right = _resolve(left_bars, right_bars)
    n = len(bars)
    if n == 0:
        return []

    highs = bars["high"].to_numpy(dtype=float)
    lows = bars["low"].to_numpy(dtype=float)
    dates = bars["date"].to_numpy()

    pivots: list[Pivot] = []
    for i in range(left, n - right):
        left_hi = highs[i - left : i]
        right_hi = highs[i + 1 : i + right + 1]
        if highs[i] >= left_hi.max() and highs[i] > right_hi.max():
            pivots.append(_pivot("HIGH", i, right, dates, highs[i]))

        left_lo = lows[i - left : i]
        right_lo = lows[i + 1 : i + right + 1]
        if lows[i] <= left_lo.min() and lows[i] < right_lo.min():
            pivots.append(_pivot("LOW", i, right, dates, lows[i]))

    return pivots


def _pivot(kind: PivotKind, pivot_i: int, right: int, dates: np.ndarray, price: float) -> Pivot:
    confirmed_i = pivot_i + right
    return Pivot(
        kind=kind,
        pivot_index=pivot_i,
        pivot_date=pd.Timestamp(dates[pivot_i]),
        price=float(price),
        confirmed_index=confirmed_i,
        confirmed_date=pd.Timestamp(dates[confirmed_i]),
    )


def swings_as_of(
    bars: pd.DataFrame,
    t: int,
    *,
    left_bars: int | None = None,
    right_bars: int | None = None,
) -> list[Pivot]:
    """Point-in-time swings knowable using only `bars[0..t]` (PRD §2.2).

    Slices `bars` to `bars.iloc[:t+1]` FIRST, then runs `find_swings` on that slice
    alone — never on the full `bars` frame with a post-hoc filter. Every returned
    pivot therefore satisfies `confirmed_index <= t` by construction, and nothing
    about bars after `t` can have influenced which pivots were even considered
    (ties, extrema) let alone returned.
    """
    if t < 0 or t >= len(bars):
        raise ValueError(f"t={t} out of range for bars of length {len(bars)}")
    truncated = bars.iloc[: t + 1]
    return find_swings(truncated, left_bars=left_bars, right_bars=right_bars)
