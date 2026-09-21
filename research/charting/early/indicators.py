"""§34.4 early indicators not yet computed anywhere in `research/charting/early/` — CHART-S25/Y-2.

docs/charting.md §34.4 lists 12 "early indicators to capture". Cross-referencing that table
against `early/scoring.py`'s actual code (not a summary of it) at the time this module was
written:

| # | §34.4 indicator                | Status before this module                                            |
|---|---------------------------------|------------------------------------------------------------------------|
| 1 | Range compression               | COVERED — `scoring._volatility_compression` via `series.range_compression` |
| 2 | Bollinger Band Width             | GAP — `series.bb_width_percentile` exists but nothing in `early/` calls it |
| 3 | Higher lows / lower highs        | GAP — no swing-structure-direction classifier existed anywhere         |
| 4 | Support/resistance stability     | GAP — `geometry.boundary_stability` (NI-2 #7) exists, fully built and tested in `test_geometry.py`, but nothing in `early/` calls it. `scoring._structural_quality` uses `geometry.level_strength` instead, which measures touch count/recency/rejection/volume/time — a materially different question ("how many good touches") from boundary_stability's ("has the level's own price held still under refit") |
| 5 | Distance to breakout level       | COVERED — `scoring._distance_to_trigger` |
| 6 | Volume contraction               | COVERED — `scoring._volume_behaviour` (latest-bar relative volume, below-baseline scores high) |
| 7 | Volume accumulation              | GAP — a *trend* ("gradually increasing") is a different question from a snapshot ratio at the latest bar; nothing computed this |
| 8 | Relative strength                | GAP, OUT OF SCOPE — needs a benchmark/sector price feed (`research/charting/context.py`); see note below |
| 9 | Momentum slope                   | COVERED — `scoring._momentum_relative_strength` via `series.momentum_slope` |
| 10| ATR expansion risk               | COVERED — `scoring._failure_risk`'s `expansion_risk` term |
| 11| Failed breakout attempts         | GAP — no rejection-count indicator existed; `geometry.Touch.rejection` is a per-touch wick fraction on confirmed swing pivots only, not a scan for intrabar piercings of a level that closed back inside |
| 12| Market/sector alignment          | GAP, OUT OF SCOPE — same benchmark/sector feed as #8; `scoring.py` already reports this honestly as `ScoreValue(None, "UNAVAILABLE")` (component `market_sector_context`) rather than fabricating a number |

**Discrepancy from the brief handed to this ticket**: the brief's shortlist ("Bollinger
band-width compression/percentile, higher-lows/lower-highs structure, S/R stability, volume
accumulation, and failed-breakout-attempt count") matches gaps #2/#3/#4/#7/#11 exactly — this
module implements precisely those five. Two more §34.4 rows (#8 Relative strength, #12
Market/sector alignment) are ALSO not computed anywhere, but both need
`research/charting/context.py`'s benchmark/sector feed, which this ticket's file ownership
does not include (context.py is owned by a different, concurrently in-progress ticket) —
`scoring.py`'s existing `test_early_module_never_imports_a_context_module` test statically
forbids any `early/*.py` file from importing it, and `test_market_sector_context_is_...`
requires that gap stay an honest `UNAVAILABLE`, not a fabricated number. This module does not
touch either of those two rows; wiring them in is a separate ticket's job once `context.py`
is ready for early/ to depend on.

Point-in-time contract: every public function here takes the FULL `bars` frame and an
explicit `t`, and truncates to `bars.iloc[:t+1]` FIRST, before computing anything — exactly
`swings.swings_as_of`'s and `patterns.detect_as_of`'s own documented contract (see their
module docstrings). No function here accepts a pre-truncated view as its own PIT boundary;
`t` is always the single source of truth for "how much of `bars` is visible". `scoring.py`'s
component functions already receive an outer-truncated `view` — they call these functions as
`fn(view, len(view) - 1, ...)`, which re-slices to the same bound (a no-op given the input is
already `bars.iloc[:t+1]`) rather than skip the contract for an "already truncated" caller.

Every function follows `geometry.py`'s own documented convention (see its module docstring):
"returns a small frozen dataclass carrying both the raw observed value and the ... verdict" —
nothing here collapses straight to an opaque float. `scoring.py` reads the `.score` field
(`None` when there is not enough data yet, honest, never a fabricated 0.0/0.5) to fold into
its own six-component blend; the raw fields alongside it are what PRD §16 calls "independent
component values" for storage/debugging.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

from research.charting.config import CONFIG
from research.charting.geometry import (
    BoundaryStability,
    boundary_drift,
    boundary_stability,
    cluster_pivots_into_levels,
    ols_slope,
)
from research.charting.series import bb_width_percentile, relative_volume
from research.charting.swings import find_swings

Direction = Literal["BULLISH", "BEARISH"]
StructureDirectionLabel = Literal["FLAT", "RISING", "FALLING", "INDETERMINATE"]

# v1 local periods/scales — documented choices, not PRD-frozen (mirrors early/scoring.py's
# own "_SHORT_RANGE_PERIOD etc." note: this package's windows must be small enough to say
# something inside a pattern as young as CONFIG["minimum_pattern_length"] (15) bars).
BB_PERIOD = 10
BB_PCTILE_LOOKBACK = 15  # warmup = BB_PERIOD + BB_PCTILE_LOOKBACK - 1 = 24 bars, vs.
# series.py's own defaults (period=20, lookback=126 -> 145-bar warmup), which would never
# finish warming up inside a typical early-formation window.

VOLUME_TREND_BARS = 5
_VOLUME_SLOPE_SCALE = 5.0  # mirrors scoring._readiness_score's own "-slope * 5.0" v1 scale

FAILED_BREAKOUT_BUFFER_ATR = 0.10  # how far beyond the level (in ATR) counts as a genuine
# intrabar piercing rather than noise — deliberately smaller than breakout_buffer_atr (0.25,
# CONFIG's own confirmed-breakout buffer): a "failed attempt" during formation is a shallower,
# more easily rejected poke than a full confirmed breakout would need to clear.
FAILED_BREAKOUT_SATURATION = 3  # attempt count at which the score saturates at 1.0


def _clip01(x: float) -> float:
    return float(np.clip(x, 0.0, 1.0))


def _truncate(bars: pd.DataFrame, t: int) -> pd.DataFrame:
    if t < 0 or t >= len(bars):
        raise ValueError(f"t={t} out of range for bars of length {len(bars)}")
    return bars.iloc[: t + 1].reset_index(drop=True)


def _atr_valid(atr: float | None) -> bool:
    return atr is not None and np.isfinite(atr) and atr > 0


# ── §34.4 #2 "Bollinger Band Width" ──────────────────────────────────────────


@dataclass(frozen=True)
class BBWidthCompression:
    percentile: float | None  # bb_width's own trailing percentile (0-100); None = insufficient warmup
    score: float | None  # None = insufficient; else in [0,1], LOW percentile (tight bands) -> HIGH score


def bb_width_compression_as_of(
    bars: pd.DataFrame, t: int, *, bb_period: int = BB_PERIOD, lookback: int = BB_PCTILE_LOOKBACK
) -> BBWidthCompression:
    """§34.4 "Bollinger Band Width": reuses `series.bb_width_percentile` verbatim (no
    Bollinger math is reimplemented here) and maps its percentile to a compression score —
    a band sitting at the bottom of its own trailing-`lookback` history (percentile near 0)
    is the "volatility contraction before a potential expansion" the PRD asks for."""
    view = _truncate(bars, t)
    pct_series = bb_width_percentile(view, bb_period=bb_period, lookback=lookback)
    pct = float(pct_series.iloc[-1])
    if not np.isfinite(pct):
        return BBWidthCompression(percentile=None, score=None)
    return BBWidthCompression(percentile=pct, score=_clip01(1.0 - pct / 100.0))


# ── §34.4 #3 "Higher lows / lower highs" ─────────────────────────────────────


@dataclass(frozen=True)
class StructureDirection:
    direction: StructureDirectionLabel | None  # None = insufficient (fewer than 2 same-kind pivots)
    drift_atr: float | None
    score: float | None  # None = insufficient; else in [0,1], 0.5 = neutral (flat/indeterminate)


def structure_direction_as_of(
    bars: pd.DataFrame,
    t: int,
    direction: Direction,
    atr_now: float | None,
    cfg: dict = CONFIG,
    *,
    left_bars: int | None = None,
    right_bars: int | None = None,
) -> StructureDirection:
    """§34.4 "Higher lows / lower highs": for a BULLISH candidate, checks whether confirmed
    swing LOWS are rising (higher lows); for BEARISH, whether confirmed swing HIGHS are
    falling (lower highs) — §34.3's own Stage-1 description groups exactly this with
    "support/resistance" and "improving structure" as the early structural signals to
    detect. Reuses `geometry.ols_slope` (fit) and `geometry.boundary_drift` (the SAME
    flat/rising/falling/indeterminate classification NI-2 already uses for pattern
    boundaries) applied to the OPPOSITE side's pivots from what a boundary check would use
    — support pivots for a bullish structure, resistance pivots for a bearish one.
    """
    if not _atr_valid(atr_now):
        return StructureDirection(direction=None, drift_atr=None, score=None)
    view = _truncate(bars, t)
    pivots = find_swings(view, left_bars=left_bars, right_bars=right_bars)
    kind = "LOW" if direction == "BULLISH" else "HIGH"
    same = sorted((p for p in pivots if p.kind == kind), key=lambda p: p.pivot_index)
    if len(same) < 2:
        return StructureDirection(direction=None, drift_atr=None, score=None)

    xs = [float(p.pivot_index) for p in same]
    ys = [p.price for p in same]
    slope = ols_slope(xs, ys)
    length_bars = int(xs[-1] - xs[0])
    drift = boundary_drift(slope, length_bars, atr_now, cfg)

    wanted: StructureDirectionLabel = "RISING" if direction == "BULLISH" else "FALLING"
    opposite: StructureDirectionLabel = "FALLING" if direction == "BULLISH" else "RISING"
    threshold = cfg["sloped_boundary_min_drift_atr"]

    if drift.direction == wanted:
        strength = min(drift.drift_atr / (2.0 * threshold), 1.0) if np.isfinite(drift.drift_atr) else 0.0
        score = _clip01(0.5 + 0.5 * strength)
    elif drift.direction == opposite:
        strength = min(drift.drift_atr / (2.0 * threshold), 1.0) if np.isfinite(drift.drift_atr) else 0.0
        score = _clip01(0.5 - 0.5 * strength)
    else:  # FLAT or INDETERMINATE — genuinely neutral, not a fabricated lean either way
        score = 0.5

    drift_atr_out = float(drift.drift_atr) if np.isfinite(drift.drift_atr) else None
    return StructureDirection(direction=drift.direction, drift_atr=drift_atr_out, score=score)


# ── §34.4 #4 "Support/resistance stability" ──────────────────────────────────


@dataclass(frozen=True)
class SRStability:
    high: BoundaryStability | None  # None if there is no resistance level with any touches
    low: BoundaryStability | None  # None if there is no support level with any touches
    score: float | None  # None = insufficient; else in [0,1], stable (small shift/residual) -> high


def sr_stability_as_of(bars: pd.DataFrame, t: int, atr_now: float | None, cfg: dict = CONFIG) -> SRStability:
    """§34.4 "Support/resistance stability": wraps `geometry.boundary_stability` (NI-2 #7 —
    already built and tested in `test_geometry.py`, but never called from `early/`) for
    whichever resistance/support level currently has the most confirmed touches. This is a
    genuinely different question from `scoring._structural_quality`'s existing
    `geometry.level_strength` read: level_strength asks "how many good touches does this
    level have"; boundary_stability asks "has the level's OWN PRICE held still" under a
    refit on the first `stability_refit_fraction` of the window — a level that has drifted
    materially between an early refit and the full window is not "stable" even if both
    slices individually have plenty of touches.
    """
    if not _atr_valid(atr_now):
        return SRStability(high=None, low=None, score=None)
    view = _truncate(bars, t)
    pivots = find_swings(view)
    if not pivots:
        return SRStability(high=None, low=None, score=None)
    highs = cluster_pivots_into_levels(pivots, view, atr_now, cfg, kind="HIGH")
    lows = cluster_pivots_into_levels(pivots, view, atr_now, cfg, kind="LOW")
    if not highs or not lows:
        return SRStability(high=None, low=None, score=None)

    best_high = max(highs, key=lambda l: len(l.touches))
    best_low = max(lows, key=lambda l: len(l.touches))
    window_start = min(
        min(tt.pivot_index for tt in best_high.touches),
        min(tt.pivot_index for tt in best_low.touches),
    )
    window_end = t

    high_result = boundary_stability(best_high.touches, window_start, window_end, atr_now, cfg)
    low_result = boundary_stability(best_low.touches, window_start, window_end, atr_now, cfg)

    per_side_scores = []
    for result in (high_result, low_result):
        if result.insufficient_data:
            continue
        shift_frac = min(result.shift_atr / cfg["boundary_stability_max_shift_atr"], 2.0) / 2.0
        residual_frac = min(result.residual_std_atr / cfg["boundary_max_residual_atr"], 2.0) / 2.0
        per_side_scores.append(_clip01(1.0 - 0.5 * shift_frac - 0.5 * residual_frac))

    score = float(np.mean(per_side_scores)) if per_side_scores else None
    return SRStability(high=high_result, low=low_result, score=score)


# ── §34.4 #7 "Volume accumulation" ───────────────────────────────────────────


@dataclass(frozen=True)
class VolumeAccumulation:
    slope: float | None  # None = insufficient trailing data
    score: float | None  # None = insufficient; else in [0,1], rising volume -> HIGH score


def volume_accumulation_as_of(
    bars: pd.DataFrame, t: int, *, n: int, trend_bars: int = VOLUME_TREND_BARS
) -> VolumeAccumulation:
    """§34.4 "Volume accumulation — gradual increase in volume before a move": the OLS
    slope of the trailing `relative_volume` series over `trend_bars`, independent of
    whether the LATEST bar's ratio is itself below or above baseline (that snapshot is
    `scoring._volume_behaviour`'s existing "volume contraction" read). The two are not
    contradictory: the textbook pattern is an overall-quiet baseline (low `relative_volume`
    most days) with a gentle recent uptick heading into a potential move — contraction and
    accumulation describe different time-scales of the same volume series.
    """
    view = _truncate(bars, t)
    rv = relative_volume(view, n=n)
    trail = rv.tail(trend_bars).dropna()
    if len(trail) < 2:
        return VolumeAccumulation(slope=None, score=None)
    slope = ols_slope(list(range(len(trail))), trail.tolist())
    return VolumeAccumulation(slope=slope, score=_clip01(0.5 + slope * _VOLUME_SLOPE_SCALE))


# ── §34.4 #11 "Failed breakout attempts" ─────────────────────────────────────


@dataclass(frozen=True)
class FailedBreakoutAttempts:
    attempt_count: int | None  # None = insufficient (no valid level/ATR/window)
    score: float | None  # None = insufficient; else in [0,1], saturating at FAILED_BREAKOUT_SATURATION


def failed_breakout_attempts_as_of(
    bars: pd.DataFrame,
    t: int,
    level_price: float | None,
    level_kind: Literal["HIGH", "LOW"],
    atr_now: float | None,
    window_start: int,
    cfg: dict = CONFIG,
    *,
    buffer_atr: float = FAILED_BREAKOUT_BUFFER_ATR,
    saturation: int = FAILED_BREAKOUT_SATURATION,
) -> FailedBreakoutAttempts:
    """§34.4 "Failed breakout attempts — repeated rejection near the boundary": counts bars
    in `[window_start, t]` whose HIGH (`level_kind="HIGH"`, resistance) pierced
    `level_price + buffer_atr * atr` intrabar but whose CLOSE fell back below `level_price`
    (mirror image, LOW < `level_price - buffer` and CLOSE above it, for `level_kind="LOW"`).
    Distinct from `geometry.Touch.rejection`: that field is a per-touch wick-vs-body
    fraction defined only on CONFIRMED swing pivots; this scans every bar in the window
    (pivot or not) for an actual piercing of the LEVEL itself that got rejected — closer to
    the plain-English "attempt", and able to fire on a bar that never becomes (or is not yet
    confirmed as) a swing pivot at all.
    """
    if level_price is None or not _atr_valid(atr_now):
        return FailedBreakoutAttempts(attempt_count=None, score=None)
    view = _truncate(bars, t)
    if window_start < 0 or window_start > t:
        return FailedBreakoutAttempts(attempt_count=None, score=None)

    window = view.iloc[window_start : t + 1]
    buffer = buffer_atr * atr_now
    if level_kind == "HIGH":
        pierced = window["high"] > (level_price + buffer)
        rejected = window["close"] < level_price
    else:
        pierced = window["low"] < (level_price - buffer)
        rejected = window["close"] > level_price

    count = int((pierced & rejected).sum())
    return FailedBreakoutAttempts(attempt_count=count, score=_clip01(count / saturation))
