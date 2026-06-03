"""Normalization utility functions.

All functions return float scores in [0, 100].
None input → 50.0 (neutral — doesn't skew the composite score when data is missing).
"""
from __future__ import annotations

import math
import statistics
from typing import Optional, Sequence


def hib(value: Optional[float], floor: float, ceiling: float) -> float:
    """Higher-Is-Better: linearly maps value → [0, 100].

    floor  → 0    (worst)
    ceiling → 100  (best)
    """
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return 50.0
    if floor >= ceiling:
        return 50.0
    if value <= floor:
        return 0.0
    if value >= ceiling:
        return 100.0
    return round((value - floor) / (ceiling - floor) * 100.0, 2)


def lib(value: Optional[float], floor: float, ceiling: float) -> float:
    """Lower-Is-Better: linearly maps value → [0, 100].

    floor  → 100  (best — low value is good)
    ceiling → 0    (worst)
    """
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return 50.0
    if floor >= ceiling:
        return 50.0
    if value <= floor:
        return 100.0
    if value >= ceiling:
        return 0.0
    return round((ceiling - value) / (ceiling - floor) * 100.0, 2)


def weighted(scores: list[tuple[float, float]]) -> float:
    """Weighted average of (score, weight) pairs. Weights need not sum to 100."""
    total_w = sum(w for _, w in scores)
    if total_w <= 0:
        return 50.0
    return round(sum(s * w for s, w in scores) / total_w, 2)


def sector_percentile(
    value: Optional[float],
    peer_values: Sequence[Optional[float]],
    higher_is_better: bool = True,
) -> float:
    """Rank value within peer_values and return percentile score (0–100).

    Returns 50.0 if value is None or fewer than 3 peers available.
    """
    if value is None:
        return 50.0
    peers = [v for v in peer_values if v is not None]
    if len(peers) < 3:
        return 50.0
    rank = sum(1 for p in peers if p < value)
    pct = rank / len(peers) * 100.0
    return round(pct if higher_is_better else 100.0 - pct, 2)


def own_history_percentile(
    current: Optional[float],
    history: Sequence[Optional[float]],
    higher_is_better: bool = True,
) -> float:
    """Compute where current sits in its own historical range.

    Returns 50.0 if fewer than 8 historical points available.
    For valuation (PE, PB) — lower current vs history = higher score when
    higher_is_better=False.
    """
    if current is None:
        return 50.0
    hist = [v for v in history if v is not None]
    if len(hist) < 8:
        return 50.0
    rank = sum(1 for h in hist if h < current)
    pct = rank / len(hist) * 100.0
    # For valuation: current in bottom 20th percentile of history → score 80 (cheap)
    return round(100.0 - pct if not higher_is_better else pct, 2)


def stability_score(
    series: Sequence[Optional[float]],
    n: int = 8,
) -> float:
    """Score the stability of a series: lower coefficient of variation = higher score.

    Returns 50.0 if fewer than 4 non-null values in last n periods.
    """
    vals = [v for v in list(series)[-n:] if v is not None]
    if len(vals) < 4:
        return 50.0
    mean = statistics.mean(vals)
    if mean <= 0:
        return 20.0  # negative or zero mean = unstable
    try:
        stdev = statistics.stdev(vals)
    except statistics.StatisticsError:
        return 50.0
    cov = stdev / abs(mean)
    return round(max(0.0, min(100.0, 100.0 - cov * 200.0)), 2)


def trend_score_linear(
    series: Sequence[Optional[float]],
    n: int = 8,
    higher_is_better: bool = True,
) -> float:
    """Score the trend direction using linear regression slope over last n points.

    Returns 50.0 if insufficient data. 100 = strong uptrend, 0 = strong downtrend.
    """
    vals = [(i, v) for i, v in enumerate(list(series)[-n:]) if v is not None]
    if len(vals) < 4:
        return 50.0
    xs = [x for x, _ in vals]
    ys = [y for _, y in vals]
    n_pts = len(xs)
    mean_x = sum(xs) / n_pts
    mean_y = sum(ys) / n_pts
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    den = sum((x - mean_x) ** 2 for x in xs)
    if den == 0:
        return 50.0
    slope = num / den
    # Normalise slope: compare to mean_y to get relative slope
    if mean_y == 0:
        return 50.0
    rel_slope = slope / abs(mean_y) * 100.0  # % change per period
    # Map: slope of +3%/period → 100; slope of -3%/period → 0
    score = 50.0 + rel_slope * (50.0 / 3.0)
    score = max(0.0, min(100.0, score))
    return round(score if higher_is_better else 100.0 - score, 2)
