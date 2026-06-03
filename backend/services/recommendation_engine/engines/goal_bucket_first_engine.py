"""
GoalBucketFirstEngine — Route new investment to the most behind-target goal bucket.

GBF-1: For each active goal that is at_risk or behind, emit an ADD signal
        for the asset class the goal needs most (equity for long-horizon,
        debt for short-horizon).
GBF-2: When multiple goals compete, sort by (urgency × goal_impact) so the
        most time-sensitive/critical goal wins the ADD slot via AR-1 dedup.

This engine complements AllocationEngine (Rule 5). AllocationEngine handles
the overall debt/equity balance; GoalBucketFirstEngine directs new SIP money
toward whichever goal is furthest behind its trajectory.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from services.recommendation_engine.base_engine import BaseEngine
from services.recommendation_engine.context import EngineSignal, RecommendationContext

logger = logging.getLogger(__name__)

# Horizon-based equity ceiling (same as GoalAlignmentEngine GA-1)
_EQUITY_CEILING = [
    (3.0,  20.0),
    (5.0,  50.0),
    (10.0, 75.0),
    (999.0, 90.0),
]

# Static fallback fund names (used when NIDP DaaS is unavailable)
_DEFAULT_EQUITY_FUND = "Parag Parikh Flexi Cap Fund - Direct Growth"
_DEFAULT_DEBT_FUND   = "HDFC Corporate Bond Fund - Direct Plan - Growth"

_GOAL_EQUITY_FUNDS_FALLBACK: Dict[str, str] = {
    "retirement": "DSP Nifty 50 Index Fund - Direct Growth",
    "education":  "Mirae Asset Large Cap Fund - Direct Growth",
    "wealth":     "Parag Parikh Flexi Cap Fund - Direct Growth",
}
_GOAL_DEBT_FUNDS_FALLBACK: Dict[str, str] = {
    "home":       "HDFC Corporate Bond Fund - Direct Plan - Growth",
    "emergency":  "ICICI Prudential Liquid Fund - Direct Growth",
}


def _equity_ceiling(horizon_years: float) -> float:
    for h, ceil in _EQUITY_CEILING:
        if horizon_years < h:
            return ceil
    return 90.0


def _preferred_fund(
    goal_type: str,
    horizon_years: float,
    top_add_candidates: Optional[Dict[str, List[Dict[str, Any]]]] = None,
) -> tuple[str, str]:
    """Return (fund_name, asset_class) best suited for a goal + horizon.

    Prefers the top-ranked live NIDP DaaS candidate in the relevant category;
    falls back to static defaults when DaaS is unavailable.
    """
    candidates = top_add_candidates or {}

    def _best_from_category(cat: str, fallback: str) -> str:
        rows = candidates.get(cat) or []
        if rows:
            return rows[0].get("scheme_name") or rows[0].get("fund_name") or fallback
        return fallback

    if horizon_years < 3.0:
        fallback = _GOAL_DEBT_FUNDS_FALLBACK.get(goal_type, _DEFAULT_DEBT_FUND)
        return _best_from_category("debt", fallback), "debt"
    if horizon_years < 5.0:
        fallback = "HDFC Balanced Advantage Fund - Direct Growth"
        return _best_from_category("hybrid", fallback), "hybrid"
    fallback = _GOAL_EQUITY_FUNDS_FALLBACK.get(goal_type, _DEFAULT_EQUITY_FUND)
    cat = "large cap" if goal_type in ("retirement", "education") else "flexi cap"
    return _best_from_category(cat, fallback), "equity"


class GoalBucketFirstEngine(BaseEngine):
    """GBF-1/GBF-2: Direct new money to the most behind-target goal bucket."""

    engine_name = "GoalBucketFirstEngine"
    enabled_config_key = "goal_bucket_first.enabled"

    def generate(self, ctx: RecommendationContext) -> List[EngineSignal]:
        if not ctx.goal_evaluations:
            return []

        signals: List[EngineSignal] = []

        for ge in ctx.goal_evaluations:
            # ge is a GoalEvaluation (or dict) — support both
            if isinstance(ge, dict):
                health       = ge.get("health_status", "on_track")
                on_track_pct = float(ge.get("on_track_pct") or 0)
                goal_gap_rs  = float(ge.get("gap_rs") or 0)
                goal_name    = ge.get("goal_name") or "Goal"
                goal_type    = ge.get("goal_type") or "wealth"
                horizon_yrs  = float(ge.get("horizon_years") or 10)
                priority     = ge.get("priority") or "medium"
                monthly_sip  = float(ge.get("monthly_sip_rs") or 0)
            else:
                health       = getattr(ge, "health_status", "on_track")
                on_track_pct = float(getattr(ge, "on_track_pct", 0) or 0)
                goal_gap_rs  = float(getattr(ge, "gap_rs", 0) or 0)
                goal_name    = getattr(ge, "goal_name", "Goal") or "Goal"
                goal_type    = getattr(ge, "goal_type", "wealth") or "wealth"
                horizon_yrs  = float(getattr(ge, "horizon_years", 10) or 10)
                priority     = getattr(ge, "priority", "medium") or "medium"
                monthly_sip  = float(getattr(ge, "monthly_sip_rs", 0) or 0)

            # Only surface for goals that are actually behind
            if health not in ("at_risk", "critical", "behind"):
                continue
            if goal_gap_rs <= 0:
                continue

            fund_name, asset_class = _preferred_fund(goal_type, horizon_yrs, ctx.top_add_candidates)

            # Don't double-emit an ADD for a bucket already added by AllocationEngine
            dedup_key = f"ADD::{asset_class}::goal_bucket::{goal_name[:20]}"
            if dedup_key in {s.dedup_key for s in ctx.signals if isinstance(ctx.signals, list)}:
                continue

            # Compute urgency and goal_impact
            urgency_val = 0.9 if health == "critical" else 0.7 if priority == "high" else 0.5
            goal_impact_val = 1.0 if health == "critical" else 0.7 if health == "at_risk" else 0.5

            # Severity
            shortfall_pct = 100 - on_track_pct
            if shortfall_pct >= 50 or health == "critical":
                severity = "severe"
            elif shortfall_pct >= 25:
                severity = "mismatch"
            else:
                severity = "minor"

            # Suggest a meaningful ADD amount: larger of (monthly SIP × 6) or 10% of gap
            suggest_rs = max(
                monthly_sip * 6 if monthly_sip > 0 else 0,
                goal_gap_rs * 0.10,
                5_000.0,  # minimum meaningful SIP amount
            )
            # Cap at 15% of portfolio value so we don't suggest concentrating
            suggest_rs = min(suggest_rs, ctx.total_value_rs * 0.15)

            equity_cap = _equity_ceiling(horizon_yrs)
            alloc = ctx.portfolio_intelligence.get("asset_allocation") or {}
            current_equity_pct = float(alloc.get("equity_pct") or 0)

            # Don't suggest equity ADD if already at ceiling for this horizon
            if asset_class == "equity" and current_equity_pct >= equity_cap:
                fund_name = _DEFAULT_DEBT_FUND
                asset_class = "debt"

            reason_text = (
                f"Your '{goal_name}' goal is {on_track_pct:.0f}% on track "
                f"({shortfall_pct:.0f}% behind). "
                f"Direct your next SIP (₹{suggest_rs:,.0f}) into {fund_name} — "
                f"this asset class aligns with your {horizon_yrs:.0f}-year horizon."
            )

            signal = EngineSignal(
                signal_id=f"goal_bucket_first::{goal_type}::{goal_name[:20].replace(' ','_')}",
                engine_name=self.engine_name,
                rule_label="GBF-1",
                action_type="ADD",
                instrument_id=None,
                instrument_name=fund_name,
                amount_rs=round(suggest_rs, 2),
                base_score=7.0 + (1.0 if health == "critical" else 0.5 if health == "at_risk" else 0),
                confidence=0.75,
                risk_reduction=0.2,
                diversification_gain=0.2,
                goal_impact=goal_impact_val,
                urgency=urgency_val,
                implementation_ease=0.8,
                reason_codes=["GOAL_BUCKET_FIRST", f"GOAL_{health.upper()}", goal_type.upper()],
                reason_text=reason_text,
                dedup_key=dedup_key,
                severity=severity,
                execution_path="redirect",
                requires_confirmation=False,
            )
            signal.__dict__["_goal_name"] = goal_name
            signal.__dict__["_goal_type"] = goal_type
            signals.append(signal)

        # Sort: most urgent first so AR-1 dedup keeps the highest-impact signal
        signals.sort(key=lambda s: (-s.goal_impact, -s.urgency))
        return signals
