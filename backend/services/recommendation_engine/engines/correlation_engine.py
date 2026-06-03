"""
CorrelationEngine — CR-1: Behaviourally redundant fund pairs.

CR-1: When two funds in the portfolio have a rolling 90-day Pearson correlation
      > 0.85, they are behaviourally redundant — one can be safely exited.
      The fund with the lower OV-3-style Keep Score is the exit candidate.

Correlation data is pre-fetched in orchestrator.run_engine_pipeline() via
daas_client.get_portfolio_correlations() and stored in ctx.portfolio_correlations.

Rule book §10.6
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from services.recommendation_engine.base_engine import BaseEngine
from services.recommendation_engine.context import EngineSignal, RecommendationContext

logger = logging.getLogger(__name__)

# Reuse OV-3 Keep Score formula (same quality ranking, different trigger)
def _keep_score(iid: Optional[str], v3_scores: Dict[str, Any]) -> float:
    v3 = v3_scores.get(iid or "", {})
    if not v3:
        return 5.0
    prims = v3.get("v3_primitives") or {}
    nidp = (v3.get("quality_score") or 0) / 10.0
    consistency = float(prims.get("consistency_score") or 5.0)
    sharpe = prims.get("sharpe")
    risk_adj = max(0.0, min(10.0, 5.0 + float(sharpe) * 2.0)) if sharpe is not None else 5.0
    ter = float(prims.get("expense_ratio_direct") or 1.0)
    expense = max(0.0, min(10.0, 10.0 - (ter - 0.3) * 4.0))
    tenure = float(prims.get("manager_tenure_years") or 2.0)
    manager = min(10.0, tenure * 2.0)
    return round(0.35 * nidp + 0.20 * consistency + 0.15 * risk_adj
                 + 0.10 * expense + 0.10 * manager + 0.10 * 5.0, 2)


class CorrelationEngine(BaseEngine):
    """CR-1: Emit EXIT for the weaker fund in behaviourally redundant pairs."""

    engine_name = "CorrelationEngine"
    enabled_config_key = "correlation.enabled"

    def generate(self, ctx: RecommendationContext) -> List[EngineSignal]:
        cfg = ctx.rules_cfg.get("correlation") or {}
        if not cfg.get("enabled", True):
            return []

        min_abs_corr = float(cfg.get("min_abs_correlation", 0.85))

        if not ctx.portfolio_correlations:
            return []

        signals: List[EngineSignal] = []
        emitted_victims: set = set()

        for row in ctx.portfolio_correlations:
            abs_corr = float(row.get("abs_correlation") or 0)
            if abs_corr < min_abs_corr:
                continue

            left_id = row.get("left_security_id") or ""
            right_id = row.get("right_security_id") or ""

            if not left_id or not right_id:
                continue

            # Skip if either already marked for exit
            if (left_id in ctx.exited_ids or right_id in ctx.exited_ids):
                continue

            # Choose victim: exit the fund with the lower keep score
            keep_left = _keep_score(left_id, ctx.v3_scores)
            keep_right = _keep_score(right_id, ctx.v3_scores)

            victim_id = left_id if keep_left <= keep_right else right_id
            partner_id = right_id if victim_id == left_id else left_id

            if victim_id in emitted_victims:
                continue

            # Look up fund names from v3_scores or mf_investments
            v3_victim = ctx.v3_scores.get(victim_id) or {}
            v3_partner = ctx.v3_scores.get(partner_id) or {}

            # Try to get fund name from mf_investments
            mf_investments = ctx.portfolio_intelligence.get("mf_investments") or []
            victim_name = next(
                (m.get("scheme_name", "") for m in mf_investments if m.get("instrument_id") == victim_id),
                victim_id[:20],
            )
            partner_name = next(
                (m.get("scheme_name", "") for m in mf_investments if m.get("instrument_id") == partner_id),
                partner_id[:20],
            )

            # Find holding and exit candidate
            from services.recommendation_engine.helpers import fuzzy_match_holding
            h = fuzzy_match_holding(victim_name, ctx.mf_holdings)
            if not h:
                continue

            amount_rs = float(h.get("quantity", 0)) * float(h.get("current_price", 0))
            cand = next(
                (c for c in ctx.exit_candidates if c.get("instrument_id") == victim_id), None
            )
            exit_score = float((cand or {}).get("exit_score") or v3_victim.get("exit_score") or 5.0)

            sig = EngineSignal(
                signal_id=f"correlation::cr1::{victim_id[:20]}::{partner_id[:20]}",
                engine_name=self.engine_name,
                rule_label="CR-1",
                action_type="EXIT",
                instrument_id=victim_id,
                instrument_name=victim_name,
                amount_rs=amount_rs,
                base_score=exit_score,
                confidence=0.7,
                risk_reduction=0.4,
                diversification_gain=0.7,
                urgency=0.3,
                implementation_ease=0.5,
                estimated_tax_rs=float(((cand or {}).get("tax_impact") or {}).get("tax_liability") or 0),
                reason_codes=["CR1_BEHAVIOURAL_REDUNDANCY"],
                reason_text=(
                    f"'{victim_name}' and '{partner_name}' have a rolling 90-day correlation of "
                    f"{abs_corr:.2f} (≥ {min_abs_corr:.2f}) — they behave like the same fund. "
                    f"Exiting the weaker fund (keep score {keep_left if victim_id == left_id else keep_right:.1f} "
                    f"vs {keep_right if victim_id == left_id else keep_left:.1f}) improves diversification."
                ),
                dedup_key=f"EXIT::{victim_id}",
            )
            sig.__dict__["_holding"] = h
            if cand:
                sig.__dict__["_candidate"] = cand
            signals.append(sig)
            emitted_victims.add(victim_id)

        if signals:
            logger.info("[CorrelationEngine] %d CR-1 signals emitted", len(signals))

        return signals
