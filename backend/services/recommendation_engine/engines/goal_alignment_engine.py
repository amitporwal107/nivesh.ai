"""
GoalAlignmentEngine — NEW: Goal-critical signals win arbitration.

For each GoalEvaluation with goal_health in ("critical", "at_risk"):
  - Emit EXIT for the highest exit_score candidate
  - Emit ADD for the missing asset class (from deviation_result)

These signals carry goal_impact=1.0 for critical goals, so ArbitrationEngine
(AR-1) will prefer them over competing signals for the same holding.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from services.recommendation_engine.base_engine import BaseEngine
from services.recommendation_engine.context import EngineSignal, RecommendationContext

logger = logging.getLogger(__name__)

# Debt fund suggestion for goal-based ADD signals
_GOAL_DEBT_FUND = "HDFC Corporate Bond Fund - Direct Plan - Growth"
_GOAL_EQUITY_FUND = "Parag Parikh Flexi Cap Fund - Direct Growth"


class GoalAlignmentEngine(BaseEngine):
    """Emit goal-critical EXIT + ADD signals; these win over competing signals (AR-1)."""

    engine_name = "GoalAlignmentEngine"

    def generate(self, ctx: RecommendationContext) -> List[EngineSignal]:
        if not ctx.goal_evaluations:
            return []

        signals: List[EngineSignal] = []
        local_exited_ids: set = set()

        for eval_ in ctx.goal_evaluations:
            health = getattr(eval_, "goal_health", None) or ""
            if health not in ("critical", "at_risk"):
                continue

            on_track_pct = float(getattr(eval_, "on_track_probability_pct", 50.0) or 50.0)
            goal_impact_val = 1.0 - on_track_pct / 100.0
            urgency_val = 1.0 if health == "critical" else 0.7
            confidence_val = 0.8 if health == "critical" else 0.6

            goal_name = getattr(eval_, "goal_name", "") or getattr(eval_, "name", "") or "Goal"
            goal_gap_rs = float(getattr(eval_, "gap_rs", 0) or 0)

            # EXIT: highest exit_score candidate not already marked
            best_candidate: Optional[Dict] = None
            for cand in ctx.exit_candidates:
                iid = cand.get("instrument_id")
                if iid in ctx.exited_ids or iid in local_exited_ids:
                    continue
                if best_candidate is None or cand["exit_score"] > best_candidate["exit_score"]:
                    best_candidate = cand

            if best_candidate:
                iid = best_candidate.get("instrument_id")
                fund_name = (
                    best_candidate.get("instrument_name")
                    or best_candidate.get("mf_investment", {}).get("scheme_name", "")
                    or ""
                )
                # Find holding value
                from services.recommendation_engine.helpers import fuzzy_match_holding
                h = fuzzy_match_holding(fund_name, ctx.mf_holdings)
                amount_rs = (
                    float(h.get("quantity", 0)) * float(h.get("current_price", 0)) if h else 0.0
                )

                exit_sig = EngineSignal(
                    signal_id=f"goal_alignment::exit::{goal_name[:20]}::{iid or fund_name[:20]}",
                    engine_name=self.engine_name,
                    rule_label="Goal Alignment",
                    action_type="EXIT",
                    instrument_id=iid,
                    instrument_name=fund_name,
                    amount_rs=amount_rs,
                    base_score=float(best_candidate.get("exit_score") or 5.0),
                    confidence=confidence_val,
                    risk_reduction=0.3,
                    diversification_gain=0.2,
                    goal_impact=goal_impact_val,
                    urgency=urgency_val,
                    implementation_ease=0.6,
                    estimated_tax_rs=float(
                        (best_candidate.get("tax_impact") or {}).get("tax_liability") or 0
                    ),
                    reason_codes=["GOAL_ALIGNMENT", health.upper()],
                    reason_text=(
                        f"Goal '{goal_name}' is {health} (on-track probability: {on_track_pct:.0f}%). "
                        f"Freeing up ₹{amount_rs:,.0f} by exiting this underperforming fund "
                        f"and redeploying toward your goal."
                    ),
                    dedup_key=f"EXIT::{iid or fund_name[:30]}",
                )
                exit_sig.__dict__["_holding"] = h
                exit_sig.__dict__["_candidate"] = best_candidate
                signals.append(exit_sig)
                if iid:
                    local_exited_ids.add(iid)

            # ADD: suggest a fund aligned with the goal's missing asset class
            if goal_gap_rs > 0 and ctx.deviation_result:
                # Pick the asset class with the biggest hard deviation
                try:
                    dev_rows = getattr(ctx.deviation_result, "rows", [])
                    largest_dev = max(
                        dev_rows, key=lambda r: abs(getattr(r, "hard_pp", 0) or 0), default=None
                    )
                    if largest_dev:
                        missing_class = getattr(largest_dev, "asset_class", "")
                        fund_name = (
                            _GOAL_DEBT_FUND if "debt" in missing_class.lower() else _GOAL_EQUITY_FUND
                        )
                        add_sig = EngineSignal(
                            signal_id=f"goal_alignment::add::{goal_name[:20]}::{missing_class}",
                            engine_name=self.engine_name,
                            rule_label="Goal Alignment",
                            action_type="ADD",
                            instrument_id=None,
                            instrument_name=fund_name,
                            amount_rs=min(goal_gap_rs, ctx.total_value_rs * 0.15),
                            base_score=8.0,
                            confidence=confidence_val,
                            goal_impact=goal_impact_val,
                            urgency=urgency_val,
                            diversification_gain=0.3,
                            implementation_ease=0.7,
                            reason_codes=["GOAL_ALIGNMENT", "ALLOCATION_GAP", health.upper()],
                            reason_text=(
                                f"Goal '{goal_name}' needs ₹{goal_gap_rs:,.0f} more. "
                                f"Adding {fund_name} aligned with {missing_class} target."
                            ),
                            dedup_key=f"ADD::{missing_class}::goal",
                        )
                        signals.append(add_sig)
                except Exception as e:
                    logger.debug("[GoalAlignmentEngine] deviation traversal failed: %s", e)

        return signals
