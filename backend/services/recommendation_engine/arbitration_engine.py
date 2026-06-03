"""
ArbitrationEngine — PRD AR-1, AR-2, AR-3: Conflict resolution.

AR-2: Suppress signals where tax cost > threshold % of exit amount
      (unless is_tax_harvesting=True).
AR-3: Downgrade signals below confidence threshold to LOW severity.
      Rule book §10.11: "Downgrade by one level — do NOT drop silently."
AR-1: Deduplicate by dedup_key; GoalAlignmentEngine wins; else highest base_score.
AR-3 priority rank: 0.30×risk_reduction + 0.25×diversification_gain
                  + 0.20×goal_impact + 0.15×urgency + 0.10×implementation_ease
                  × base_score (final sort key for output ordering)
"""
from __future__ import annotations

import logging
from typing import Dict, List

from services.recommendation_engine.context import EngineSignal, RecommendationContext

logger = logging.getLogger(__name__)

_GOAL_ENGINE = "GoalAlignmentEngine"


class ArbitrationEngine:
    """Suppress, deduplicate, and rank EngineSignals."""

    def arbitrate(
        self,
        signals: List[EngineSignal],
        ctx: RecommendationContext,
    ) -> List[EngineSignal]:
        ep_cfg = (ctx.rules_cfg.get("engine_pipeline") or {})
        arb_cfg = ep_cfg.get("arbitration") or {}
        confidence_threshold = float(arb_cfg.get("confidence_threshold", 0.4))
        tax_threshold_pct = float(arb_cfg.get("tax_suppression_threshold_pct", 15.0))

        active: List[EngineSignal] = []

        for sig in signals:
            # DV-4: ELSS lock-in hard stop — suppress EXIT/TRIM for locked instruments.
            # DataValidationEngine populates ctx.tax_suppressed_instrument_ids with locked IDs.
            if (
                sig.action_type in ("EXIT", "TRIM")
                and sig.instrument_id
                and sig.instrument_id in ctx.tax_suppressed_instrument_ids
            ):
                sig = _suppress(sig, "ELSS lock-in or missing cost basis — EXIT/TRIM blocked")
                active.append(sig)
                continue

            # AR-2: tax suppression
            if (
                sig.action_type == "EXIT"
                and not sig.is_tax_harvesting
                and sig.estimated_tax_rs > 0
                and sig.amount_rs > 0
            ):
                tax_pct = sig.estimated_tax_rs / sig.amount_rs * 100
                if tax_pct > tax_threshold_pct:
                    sig = _suppress(sig, f"Tax cost {tax_pct:.1f}% > {tax_threshold_pct:.0f}% threshold")
                    active.append(sig)
                    continue

            # AR-3: confidence below threshold — downgrade to LOW, do NOT suppress.
            # Rule book §10.11: "Downgrade by one level — do NOT drop silently. Record in trace."
            if sig.confidence < confidence_threshold:
                import copy as _copy
                s = _copy.copy(sig)
                note = f"[AR-3 downgraded: confidence {sig.confidence:.2f} → LOW (< {confidence_threshold:.2f})]"
                s.confidence = min(s.confidence, 0.3)
                s.reason_text = (f"{note} {s.reason_text}").strip()
                active.append(s)
                continue

            active.append(sig)

        # AR-1: dedup by dedup_key — GoalAlignmentEngine wins; else highest base_score
        best_by_key: Dict[str, EngineSignal] = {}
        for sig in active:
            if sig.suppressed:
                continue
            key = sig.dedup_key
            existing = best_by_key.get(key)
            if existing is None:
                best_by_key[key] = sig
            elif sig.engine_name == _GOAL_ENGINE and existing.engine_name != _GOAL_ENGINE:
                best_by_key[key] = sig  # goal engine always wins
            elif sig.base_score > existing.base_score and existing.engine_name != _GOAL_ENGINE:
                best_by_key[key] = sig

        deduped = list(best_by_key.values())
        suppressed = [s for s in active if s.suppressed]

        # PRD §8: severity ordering — severe → mismatch → minor → aligned, then by AR-3 priority
        _SEV_RANK = {"severe": 0, "mismatch": 1, "minor": 2, "aligned": 3}
        deduped.sort(
            key=lambda s: (_SEV_RANK.get(s.severity or "minor", 2), -s.ar3_priority),
        )

        logger.info(
            "[Arbitration] %d signals → %d active, %d suppressed",
            len(signals), len(deduped), len(suppressed),
        )

        return deduped + suppressed  # suppressed kept at end for audit trail


def _suppress(sig: EngineSignal, reason: str) -> EngineSignal:
    import copy
    s = copy.copy(sig)
    s.suppressed = True
    s.suppression_reason = reason
    return s
