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
from numpy.lib.stride_tricks import sliding_window_view

from research.charting.config import CONFIG

PivotKind = Literal["HIGH", "LOW"]

# Review 2026-09-22 (defect #4, "unhashed behaviour switches"): the tie-breaking rule below
# used to be bare code with no CONFIG knob at all, so changing it would not have changed
# config_hash(). It now lives in CONFIG["swing_tie_rule"]; this module still only ever
# IMPLEMENTS the one rule described below, so any other value is a hard error rather than a
# silently-ignored setting.
_SUPPORTED_SWING_TIE_RULES = ("latest_bar_wins",)


def _validate_tie_rule() -> str:
    rule = CONFIG["swing_tie_rule"]
    if rule not in _SUPPORTED_SWING_TIE_RULES:
        raise ValueError(
            f"unsupported CONFIG['swing_tie_rule']: {rule!r} -- only {_SUPPORTED_SWING_TIE_RULES} "
            "is implemented by research.charting.swings.find_swings"
        )
    return rule


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
    _validate_tie_rule()  # only "latest_bar_wins" (below) is implemented -- raises otherwise
    left, right = _resolve(left_bars, right_bars)
    n = len(bars)
    if n == 0:
        return []

    highs = bars["high"].to_numpy(dtype=float)
    lows = bars["low"].to_numpy(dtype=float)
    dates = bars["date"].to_numpy()

    lo, hi = left, n - right  # candidate positions i in [lo, hi) -- same range as `range(left, n - right)`
    if lo >= hi:
        return []

    # PERF-DETECT (2026-09-22): vectorised equivalent of the per-i `highs[i-left:i].max()` /
    # `highs[i+1:i+right+1].max()` slice-and-reduce (and the LOW mirror) the loop below used to
    # do fresh on every single `i` -- called once per bar on the ever-growing view from
    # `detect_as_of`, this was O(n) numpy reduce calls per call, O(n^2) reduce calls across a
    # full replay. `sliding_window_view(highs, left)` is every length-`left` window of `highs`
    # at once (`[j].max()` == `highs[j:j+left].max()`, for every valid `j`); reducing each
    # window with `.max(axis=1)`/`.min(axis=1)` computes every `i`'s left/right window
    # max/min in a handful of vectorised calls instead of one Python-level call per `i`. `max`/
    # `min` are comparison-only (no floating-point accumulation order to preserve, unlike
    # sum/mean), so this is byte-for-byte the same value `highs[i-left:i].max()` would have
    # produced -- verified by direct differential comparison against the original per-`i` loop
    # across real symbols (various lengths, left/right windows) and edge cases (n=0, n<left,
    # n<right, ties, NaN-containing, monotonic, flat, alternating) before this change landed.
    # `lo >= hi` (checked above) is exactly the condition under which `left`/`right` could
    # otherwise exceed the array length that `sliding_window_view` requires.
    left_high_max = sliding_window_view(highs, left).max(axis=1)
    left_low_min = sliding_window_view(lows, left).min(axis=1)
    right_high_max = sliding_window_view(highs, right).max(axis=1)
    right_low_min = sliding_window_view(lows, right).min(axis=1)

    idx = np.arange(lo, hi)
    lhm = left_high_max[idx - left]  # == highs[i-left:i].max(), for i = idx
    llm = left_low_min[idx - left]
    rhm = right_high_max[idx + 1]  # == highs[i+1:i+right+1].max(), for i = idx
    rlm = right_low_min[idx + 1]

    # CONFIG["swing_tie_rule"] == "latest_bar_wins": left neighbours may tie (non-strict
    # >=/<=), right neighbours must be strictly worse (>/<) -- see module docstring.
    high_hits = (highs[idx] >= lhm) & (highs[idx] > rhm)
    low_hits = (lows[idx] <= llm) & (lows[idx] < rlm)

    pivots: list[Pivot] = []
    for k in range(len(idx)):
        i = int(idx[k])
        # Per-i order preserved exactly: HIGH checked (and appended) before LOW, ascending i --
        # identical to the original loop's own append order.
        if high_hits[k]:
            pivots.append(_pivot("HIGH", i, right, dates, highs[i]))
        if low_hits[k]:
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
