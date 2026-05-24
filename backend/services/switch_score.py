"""Switch-score computation for v4 SWITCH recommendations.

Option A (Nivesh-side): exit_score × (1 + replacement_advantage_pp / 100)
Per docs/api-changes.md Decision — approved 2026-05-24.

Screens served: all 6 dashboard recommendation cards where verb=SWITCH.
"""
from __future__ import annotations

import time
import logging
from typing import Optional

logger = logging.getLogger(__name__)

_CACHE_TTL_S = 86_400  # 24 hours
_cache: dict[str, tuple[Optional[float], float]] = {}


def compute_switch_score(
    exit_score: float,
    replacement_advantage_pp: float,
    source_category: Optional[str] = None,
    target_category: Optional[str] = None,
    source_expense_ratio: Optional[float] = None,
    target_expense_ratio: Optional[float] = None,
    source_return_3y_pct: Optional[float] = None,
    target_return_3y_pct: Optional[float] = None,
    source_isin: Optional[str] = None,
    target_isin: Optional[str] = None,
) -> Optional[float]:
    """Return switch_score ∈ [0, 100] or None when switching is not meaningful.

    Args:
        exit_score: 0-100 exit score from NIDP/scoring engine for source fund
        replacement_advantage_pp: how much better (pp) the target is vs source
        source_category / target_category: fund category strings (must match)
        source_expense_ratio / target_expense_ratio: annual TER in %
        source_return_3y_pct / target_return_3y_pct: 3-year CAGR in %
        source_isin / target_isin: ISIN strings for same-fund guard + cache key

    Returns:
        switch_score (clamped 0-100) or None
    """
    # Check cache
    cache_key = f"{source_isin or ''}:{target_isin or ''}"
    if source_isin and target_isin and cache_key in _cache:
        score, expires = _cache[cache_key]
        if time.time() < expires:
            return score

    result = _compute_uncached(
        exit_score, replacement_advantage_pp,
        source_category, target_category,
        source_expense_ratio, target_expense_ratio,
        source_return_3y_pct, target_return_3y_pct,
        source_isin, target_isin,
    )

    if source_isin and target_isin:
        _cache[cache_key] = (result, time.time() + _CACHE_TTL_S)

    return result


def _compute_uncached(
    exit_score: float,
    replacement_advantage_pp: float,
    source_category: Optional[str],
    target_category: Optional[str],
    source_expense_ratio: Optional[float],
    target_expense_ratio: Optional[float],
    source_return_3y_pct: Optional[float],
    target_return_3y_pct: Optional[float],
    source_isin: Optional[str],
    target_isin: Optional[str],
) -> Optional[float]:
    # Guard 1: same fund
    if source_isin and target_isin and source_isin == target_isin:
        return None

    # Guard 2: category mismatch
    if source_category and target_category:
        if source_category.lower() != target_category.lower():
            logger.debug(
                "switch_score: category mismatch %s vs %s → None",
                source_category, target_category,
            )
            return None

    # Guard 3: cost-leak — higher cost, lower return → switching makes things worse
    if (
        source_expense_ratio is not None
        and target_expense_ratio is not None
        and source_return_3y_pct is not None
        and target_return_3y_pct is not None
    ):
        if target_expense_ratio > source_expense_ratio and target_return_3y_pct < source_return_3y_pct:
            logger.debug("switch_score: cost-leak guard triggered → 0")
            return 0.0

    raw = exit_score * (1 + replacement_advantage_pp / 100)
    return round(min(max(raw, 0.0), 100.0), 2)
