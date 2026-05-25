"""
PortfolioImpactEngine — PRD PI-1..PI-4: Allocation-weighted signal scoring.

Multiplies each signal's base_score by three multipliers:
  PI-1: allocation_multiplier  (<2%=0.4, 2-5%=0.7, 5-10%=1.0, 10-20%=1.3, >20%=1.7)
  PI-2: goal_multiplier        (1.0–1.5x based on worst on_track_pct)
  PI-3: combined multiply      base_score × alloc × goal × risk
  PI-4: risk_multiplier        (1.0–1.3x based on max hard deviation)

Mutates base_score in-place on a copy of each signal; does not modify ctx.
"""
from __future__ import annotations

import logging
from typing import List

from services.recommendation_engine.context import EngineSignal, HoldingWeight, RecommendationContext

logger = logging.getLogger(__name__)


def _alloc_multiplier(weight_pct: float) -> float:
    """PRD PI-1."""
    if weight_pct < 2.0:
        return 0.4
    if weight_pct < 5.0:
        return 0.7
    if weight_pct < 10.0:
        return 1.0
    if weight_pct < 20.0:
        return 1.3
    return 1.7


def _goal_multiplier(goal_evaluations: list) -> float:
    """PRD PI-2: 1.0–1.5x based on worst on-track probability."""
    if not goal_evaluations:
        return 1.0
    worst = min(
        float(getattr(e, "on_track_probability_pct", 100) or 100)
        for e in goal_evaluations
    )
    return 1.0 + (1.0 - min(worst, 100.0) / 100.0) * 0.5


def _risk_multiplier(deviation_result) -> float:
    """PRD PI-4: 1.0–1.3x based on max hard deviation from target."""
    if not deviation_result:
        return 1.0
    rows = getattr(deviation_result, "rows", []) or []
    max_dev = max((abs(float(getattr(r, "hard_pp", 0) or 0)) for r in rows), default=0.0)
    return 1.0 + min(max_dev / 20.0, 1.0) * 0.3


class PortfolioImpactEngine:
    """Apply allocation weighting to all signals. Returns new list with adjusted base_score."""

    def apply(
        self,
        signals: List[EngineSignal],
        ctx: RecommendationContext,
    ) -> List[EngineSignal]:
        if not (ctx.rules_cfg.get("engine_pipeline") or {}).get("portfolio_impact", {}).get("enabled", True):
            return signals

        goal_mult = _goal_multiplier(ctx.goal_evaluations)
        risk_mult = _risk_multiplier(ctx.deviation_result)

        weighted: List[EngineSignal] = []
        for sig in signals:
            # Look up pre-computed allocation weight (keyed by instrument_id or name)
            hw: HoldingWeight | None = None
            if sig.instrument_id:
                hw = ctx.holding_weights.get(sig.instrument_id)
            if hw is None:
                from services.recommendation_engine.helpers import normalize_fund_name
                hw = ctx.holding_weights.get(normalize_fund_name(sig.instrument_name))

            alloc_mult = _alloc_multiplier(hw.weight_pct if hw else 5.0)  # default 5% = 1.0x

            new_score = sig.base_score * alloc_mult * goal_mult * risk_mult
            # Mutate on a shallow copy
            import copy
            wsig = copy.copy(sig)
            wsig.base_score = round(min(new_score, 10.0), 3)
            weighted.append(wsig)

            logger.debug(
                "[PI] %s %.3f → %.3f (alloc=%.2f goal=%.2f risk=%.2f)",
                sig.signal_id[:40], sig.base_score, wsig.base_score,
                alloc_mult, goal_mult, risk_mult,
            )

        return weighted
