"""§30.1 NI-2 geometry predicates — docs/charting.md §30.1, full rationale in
`.claude/workspace/charting-pattern-engine/ni2-geometry-predicates.md`.

Every predicate here is ATR-normalised (scale-free across symbols) and takes `atr` as an
explicit scalar, never a series: per the NI-2 doc's own notation, "ATR = §10.2 atr_period:
14 ATR at the evaluation bar" — callers decide which bar's ATR is "the evaluation bar" for
their use (e.g. formation_end for a geometry check, the confirmation bar for a breakout
buffer) and pass that one number in. Nothing in this module reads a `bars`/series frame
directly except the small helpers that build a `Touch` from a `Pivot` (they need the pivot's
own OHLCV row) — there is no bar-range slicing here, so this module cannot itself leak
look-ahead; that discipline belongs to the caller (patterns.py), which must always operate
on an already-`t`-truncated view.

Every function returns a small frozen dataclass carrying both the raw observed value and
the boolean/label verdict, per PRD §16: "Store independent component values ... a rule that
fails says *which* clause failed" — nothing here collapses into an opaque score.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal, Sequence

import numpy as np
import pandas as pd

from research.charting.config import CONFIG
from research.charting.swings import Pivot

PivotKind = Literal["HIGH", "LOW"]
LevelKind = Literal["RESISTANCE", "SUPPORT"]
BoundaryDirection = Literal["FLAT", "RISING", "FALLING", "INDETERMINATE"]


def _atr_valid(atr: float | None) -> bool:
    # PERF-DETECT (2026-09-22): `math.isfinite` on a scalar (plain float or numpy float64) is
    # the same finiteness test as `np.isfinite` -- excludes NaN and +/-inf, identically -- but
    # avoids numpy's ufunc-dispatch overhead, which dominates when called this often (this is
    # the single most-called predicate in the hot per-bar walk loops: ~1M+ calls in a full
    # replay). `atr is not None` still short-circuits before either finiteness check runs.
    return atr is not None and math.isfinite(atr) and atr > 0


# ── 1. Boundary drift — flat / rising / falling (§30.1 #1) ──────────────────


@dataclass(frozen=True)
class BoundaryDrift:
    slope: float
    length_bars: int
    atr: float
    drift_atr: float
    direction: BoundaryDirection


def ols_slope(xs: Sequence[float], ys: Sequence[float]) -> float:
    """Ordinary-least-squares slope of `ys` on `xs` (price change per unit of `xs`, e.g. per
    bar). Returns 0.0 for fewer than 2 distinct x values (a flat/degenerate fit, not an
    error) — a single touch or a set of touches all at the same bar index cannot define a
    slope, and "no evidence of drift" is the honest default rather than raising.
    """
    x = np.asarray(xs, dtype=float)
    y = np.asarray(ys, dtype=float)
    if len(x) < 2:
        return 0.0
    x_mean = x.mean()
    denom = float(np.sum((x - x_mean) ** 2))
    if denom == 0.0:
        return 0.0
    y_mean = y.mean()
    return float(np.sum((x - x_mean) * (y - y_mean)) / denom)


def boundary_drift(slope: float, length_bars: int, atr: float, cfg: dict = CONFIG) -> BoundaryDrift:
    """NI-2 #1: `boundary_drift_atr = |slope| * L / ATR`.
    flat     iff drift_atr <= flat_boundary_max_drift_atr
    rising   iff slope > 0 and drift_atr >= sloped_boundary_min_drift_atr
    falling  iff slope < 0 and drift_atr >= sloped_boundary_min_drift_atr
    INDETERMINATE: strictly between the two thresholds, or ATR/length unusable. The PRD/NI-2
    text does not name this middle band — this is a documented interpretation, not a defined
    PRD term — but leaving a gap is deliberately safer than forcing every boundary into
    "flat" or "rising/falling" right up to the opposite threshold.
    """
    if not _atr_valid(atr) or length_bars <= 0:
        return BoundaryDrift(slope=slope, length_bars=length_bars, atr=float("nan"), drift_atr=float("nan"), direction="INDETERMINATE")
    drift = abs(slope) * length_bars / atr
    flat_max = cfg["flat_boundary_max_drift_atr"]
    sloped_min = cfg["sloped_boundary_min_drift_atr"]
    if drift <= flat_max:
        direction: BoundaryDirection = "FLAT"
    elif drift >= sloped_min and slope > 0:
        direction = "RISING"
    elif drift >= sloped_min and slope < 0:
        direction = "FALLING"
    else:
        direction = "INDETERMINATE"
    return BoundaryDrift(slope=slope, length_bars=length_bars, atr=float(atr), drift_atr=drift, direction=direction)


# ── Triangle convergence (§30.1 #1 continued, §13.4/§13.5/§13.10) ───────────


@dataclass(frozen=True)
class Convergence:
    ratio: float
    converging: bool


def convergence_ratio(gap_at_first_bar: float, gap_at_last_bar: float, cfg: dict = CONFIG) -> Convergence:
    """`convergence_ratio = gap_at_last_bar / gap_at_first_bar`; converging iff <= convergence_max_ratio.

    Reserved for triangle/wedge detectors (not yet built) -- this is an owner-approved NI-2
    predicate (review 2026-09-22, defect #5) with no production caller yet. Do not delete: a
    future triangle/wedge family measures its two boundaries' gap at the first and last bar
    of the formation and calls this directly.
    """
    if gap_at_first_bar is None or not np.isfinite(gap_at_first_bar) or gap_at_first_bar <= 0:
        return Convergence(ratio=float("nan"), converging=False)
    ratio = float(gap_at_last_bar) / float(gap_at_first_bar)
    return Convergence(ratio=ratio, converging=ratio <= cfg["convergence_max_ratio"])


# ── 2. Pivot clustering into levels (§30.1 #2) ───────────────────────────────


@dataclass(frozen=True)
class Touch:
    """A single confirmed pivot contributing to a level, enriched with the fields the
    §30.1 #3 strength formula needs (volume and rejection-wick fraction, both read off the
    pivot's own OHLCV row — the row at `pivot_index`, never anything later)."""

    pivot_index: int
    pivot_date: pd.Timestamp
    confirmed_index: int
    confirmed_date: pd.Timestamp
    kind: PivotKind
    price: float
    volume: float
    bar_range: float
    rejection: float  # wick-beyond-body fraction of the bar's range, on the touch side; see _rejection_fraction


def _rejection_fraction(open_: float, high: float, low: float, close: float, kind: PivotKind) -> float:
    """Interpretation of NI-2 #3's "wick beyond level / bar range": the fraction of the
    touch bar's own range that is wick beyond the CANDLE BODY on the side that touched the
    level — the standard candlestick rejection-wick measure. (The PRD/NI-2 text does not
    give a formula for "wick beyond level"; a literal "distance past the level itself" is
    not well-defined once the level is a multi-touch cluster mean rather than this one bar's
    exact price, so this module uses the touch bar's own body as the reference point, which
    is always well-defined per-touch and captures the same "did this bar reject strongly"
    intent. Documented here as the chosen interpretation.)
    """
    rng = high - low
    if rng <= 0:
        return 0.0
    if kind == "HIGH":
        wick_beyond = high - max(open_, close)
    else:
        wick_beyond = min(open_, close) - low
    return max(0.0, float(wick_beyond) / float(rng))


def touch_from_pivot(pivot: Pivot, bars: pd.DataFrame) -> Touch:
    """Build a Touch from a confirmed Pivot, reading only the pivot's own bar row
    (`bars.iloc[pivot.pivot_index]`) — never any bar after it."""
    row = bars.iloc[pivot.pivot_index]
    rng = float(row["high"] - row["low"])
    rejection = _rejection_fraction(float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"]), pivot.kind)
    return Touch(
        pivot_index=pivot.pivot_index,
        pivot_date=pivot.pivot_date,
        confirmed_index=pivot.confirmed_index,
        confirmed_date=pivot.confirmed_date,
        kind=pivot.kind,
        price=pivot.price,
        volume=float(row["volume"]),
        bar_range=rng,
        rejection=rejection,
    )


def _touch_from_arrays(
    pivot: Pivot, opens: np.ndarray, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, volumes: np.ndarray
) -> Touch:
    """Perf-only twin of `touch_from_pivot` (PERF-DETECT): identical value-for-value (same
    float64 reads, same `_rejection_fraction` call with the same four floats in the same
    order), but reads the pivot's own bar from pre-extracted numpy column arrays instead of
    `bars.iloc[pivot.pivot_index]` — a full-row Series fetch is measurably more expensive per
    call than one scalar read from each of five already-built numpy arrays, and
    `cluster_pivots_into_levels` below calls this once per pivot, every `detect_as_of` call.
    `touch_from_pivot` itself is kept byte-for-byte unchanged (it is imported directly by
    test_geometry.py) — this is purely an internal fast path used by this module's own hot
    loop. IEEE-754 double subtraction/arithmetic on the same bit pattern is bit-exact
    regardless of whether the value arrived via `Series.iloc` or a numpy array, so `rng` and
    `rejection` come out identical to `touch_from_pivot`'s own computation."""
    i = pivot.pivot_index
    o, h, l, c, v = float(opens[i]), float(highs[i]), float(lows[i]), float(closes[i]), float(volumes[i])
    rng = h - l
    rejection = _rejection_fraction(o, h, l, c, pivot.kind)
    return Touch(
        pivot_index=pivot.pivot_index,
        pivot_date=pivot.pivot_date,
        confirmed_index=pivot.confirmed_index,
        confirmed_date=pivot.confirmed_date,
        kind=pivot.kind,
        price=pivot.price,
        volume=v,
        bar_range=rng,
        rejection=rejection,
    )


def _weighted_mean(touches: Sequence[Touch]) -> float:
    total_w = sum(t.volume for t in touches)
    if total_w <= 0:
        return float(sum(t.price for t in touches) / len(touches))
    return float(sum(t.price * t.volume for t in touches) / total_w)


@dataclass(frozen=True)
class Level:
    kind: LevelKind
    price: float
    touches: tuple[Touch, ...]


def cluster_pivots_into_levels(
    pivots: Sequence[Pivot], bars: pd.DataFrame, atr: float, cfg: dict = CONFIG, *, kind: PivotKind = "HIGH"
) -> list[Level]:
    """NI-2 #2: cluster same-kind confirmed pivots into levels.

    1. Chain-link clustering by price: sort touches by price, start a new cluster whenever
       the gap from the previous (price-sorted) touch exceeds `level_cluster_width_atr * atr`.
       This is the standard single-linkage 1-D clustering and is equivalent to "within
       level_cluster_width_atr of the level" for a level defined as any point within the
       chain, since every member is within one hop of its neighbour.
    2. Within each price cluster, apply the separation rule chronologically: keep a touch
       only if it is >= touch_min_separation_bars after the last KEPT touch — this is what
       stops "a single three-day chop at one price" (ni2-geometry-predicates.md) from
       inflating the touch count.
    3. level_price = volume-weighted mean of the KEPT touches (NI-2 #2: "volume-weighted
       mean of its member pivots").

    Returns every cluster found, with whatever touch count survives step 2 (including 1) —
    callers apply their own minimum-touch gate (level_min_touches for a standalone level,
    pattern_boundary_min_touches for a pattern boundary), since the two contexts need
    different thresholds on the same clustering.
    """
    same_kind = [p for p in pivots if p.kind == kind]
    if not same_kind or not _atr_valid(atr):
        return []
    # PERF-DETECT: extract the five OHLCV columns to numpy ONCE for this call, then read each
    # pivot's own row via `_touch_from_arrays` (plain array indexing) instead of
    # `touch_from_pivot`'s per-pivot `bars.iloc[...]` (a full-row Series fetch, with pandas'
    # own type/bounds-checking overhead on every call) -- value-for-value identical, see
    # `_touch_from_arrays`'s own docstring.
    opens = bars["open"].to_numpy(dtype=float)
    highs_arr = bars["high"].to_numpy(dtype=float)
    lows_arr = bars["low"].to_numpy(dtype=float)
    closes_arr = bars["close"].to_numpy(dtype=float)
    volumes_arr = bars["volume"].to_numpy(dtype=float)
    touches = sorted(
        (_touch_from_arrays(p, opens, highs_arr, lows_arr, closes_arr, volumes_arr) for p in same_kind),
        key=lambda t: t.price,
    )
    width = cfg["level_cluster_width_atr"] * atr

    price_clusters: list[list[Touch]] = [[touches[0]]]
    for t in touches[1:]:
        if t.price - price_clusters[-1][-1].price <= width:
            price_clusters[-1].append(t)
        else:
            price_clusters.append([t])

    level_kind: LevelKind = "RESISTANCE" if kind == "HIGH" else "SUPPORT"
    min_sep = cfg["touch_min_separation_bars"]
    levels: list[Level] = []
    for cluster in price_clusters:
        chron = sorted(cluster, key=lambda t: t.pivot_index)
        kept: list[Touch] = []
        for t in chron:
            if not kept or (t.pivot_index - kept[-1].pivot_index) >= min_sep:
                kept.append(t)
        if not kept:
            continue
        levels.append(Level(kind=level_kind, price=_weighted_mean(kept), touches=tuple(kept)))
    return levels


# ── 3. Level strength — five stored components (§30.1 #3) ───────────────────


@dataclass(frozen=True)
class LevelStrength:
    touch_c: float
    recency_c: float
    rejection_c: float
    volume_c: float
    time_c: float
    level_strength: float  # composite — DESCRIPTIVE ONLY (PRD §16: not a probability)
    is_probability: bool = False


def level_strength(
    level: Level,
    *,
    as_of_index: int,
    window_start: int,
    window_end: int,
    bars: pd.DataFrame,
    relative_volume: pd.Series,
    atr: float,
    cfg: dict = CONFIG,
) -> LevelStrength:
    """NI-2 #3, each component in [0,1], stored separately; combined by the frozen weights.

    Interpretation notes (PRD/NI-2 under-specify these; documented, not silently assumed):
    - `recency_c` bars_since_last_touch is measured from the touch's own `pivot_index` (when
      price actually touched the level), not its `confirmed_index` (when the detector found
      out) — recency describes the market event, and using pivot_index never leaks the
      future since pivot_index <= confirmed_index <= as_of_index always.
    - `mean_relative_volume_at_touches` reads `relative_volume` at each touch's pivot_index.
    - `time_c`'s "bars closing within band" uses the SAME cluster band width
      (level_cluster_width_atr * atr) around `level.price`, over the caller-supplied
      [window_start, window_end] (inclusive) — the pattern's own formation window for a
      pattern boundary, or an equivalent caller-chosen lookback for a standalone level.
    """
    touches = level.touches
    n = len(touches)
    touch_c = min(n / cfg["strength_touch_saturation"], 1.0) if n else 0.0

    if n:
        last_touch_index = max(t.pivot_index for t in touches)
        bars_since = max(as_of_index - last_touch_index, 0)
        recency_c = 0.5 ** (bars_since / cfg["strength_recency_halflife_bars"])
    else:
        recency_c = 0.0

    rejection_c = float(np.mean([t.rejection for t in touches])) if n else 0.0

    # PERF-DETECT: `np.asarray` on a pd.Series/ndarray is a cheap one-time conversion (a view,
    # not a copy, for an already-numpy-backed Series); reading `rel_arr[i]` in the loop below is
    # then a plain array index instead of `Series.iloc[i]`'s per-call overhead. Same float64
    # values either way -- accepts a Series (every existing caller) or an ndarray unchanged.
    rel_arr = np.asarray(relative_volume, dtype=float)
    rel_vols: list[float] = []
    for t in touches:
        if 0 <= t.pivot_index < len(rel_arr):
            v = rel_arr[t.pivot_index]
            if np.isfinite(v):
                rel_vols.append(float(v))
    volume_c = min((float(np.mean(rel_vols)) / cfg["relative_volume_strong"]), 1.0) if rel_vols else 0.0

    length = max(window_end - window_start + 1, 1)
    if _atr_valid(atr) and window_end >= window_start:
        closes = bars["close"].to_numpy(dtype=float)[window_start : window_end + 1]
        band = cfg["level_cluster_width_atr"] * atr
        within = int(np.sum(np.abs(closes - level.price) <= band))
        time_c = min(within / (cfg["strength_time_fraction"] * length), 1.0)
    else:
        time_c = 0.0

    w = cfg["strength_weights"]
    composite = w[0] * touch_c + w[1] * recency_c + w[2] * rejection_c + w[3] * volume_c + w[4] * time_c
    return LevelStrength(
        touch_c=touch_c, recency_c=recency_c, rejection_c=rejection_c, volume_c=volume_c, time_c=time_c,
        level_strength=composite,
    )


# ── 4. Minimum rectangle range relative to ATR (§30.1 #4) ───────────────────


@dataclass(frozen=True)
class RectangleRange:
    range_atr: float
    valid: bool


def rectangle_range_ok(resistance: float, support: float, atr: float, cfg: dict = CONFIG) -> RectangleRange:
    """NI-2 #4: `rectangle_min_range_atr <= (resistance - support) / ATR <= rectangle_max_range_atr`."""
    if not _atr_valid(atr):
        return RectangleRange(range_atr=float("nan"), valid=False)
    range_atr = (resistance - support) / atr
    valid = cfg["rectangle_min_range_atr"] <= range_atr <= cfg["rectangle_max_range_atr"]
    return RectangleRange(range_atr=range_atr, valid=valid)


# ── 7. Boundary stability (§30.1 #7) ─────────────────────────────────────────


@dataclass(frozen=True)
class BoundaryStability:
    full_level: float
    truncated_level: float
    shift_atr: float
    residual_std_atr: float
    stable: bool
    insufficient_data: bool


def boundary_stability(
    touches: Sequence[Touch], window_start: int, window_end: int, atr: float, cfg: dict = CONFIG
) -> BoundaryStability:
    """NI-2 #7: refit the level on the first `stability_refit_fraction` of [window_start,
    window_end] and require the level to hold. `insufficient_data=True` (and `stable=False`)
    when there are no touches at all, ATR is unusable, or no touch falls within the
    truncated (refit) sub-window — this module never invents a refit level from zero touches.
    """
    if not touches or not _atr_valid(atr) or window_end < window_start:
        return BoundaryStability(float("nan"), float("nan"), float("nan"), float("nan"), False, True)

    full_level = _weighted_mean(touches)
    length = window_end - window_start
    cutoff = window_start + cfg["stability_refit_fraction"] * length
    truncated = [t for t in touches if t.pivot_index <= cutoff]
    if not truncated:
        return BoundaryStability(full_level, float("nan"), float("nan"), float("nan"), False, True)

    truncated_level = _weighted_mean(truncated)
    shift_atr = abs(full_level - truncated_level) / atr

    prices = np.array([t.price for t in touches], dtype=float)
    if len(prices) >= 2:
        residual_std = float(np.std(prices - full_level, ddof=1))
    else:
        residual_std = 0.0
    residual_std_atr = residual_std / atr

    stable = (shift_atr <= cfg["boundary_stability_max_shift_atr"]) and (residual_std_atr <= cfg["boundary_max_residual_atr"])
    return BoundaryStability(
        full_level=full_level, truncated_level=truncated_level, shift_atr=shift_atr,
        residual_std_atr=residual_std_atr, stable=stable, insufficient_data=False,
    )
