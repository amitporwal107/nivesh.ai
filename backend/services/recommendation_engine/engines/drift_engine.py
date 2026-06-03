"""
DriftEngine — Wraps decision_engine_actions.generate_actions().

Converts the existing drift/cap actions (from the target_allocator →
deviation_engine pipeline) into EngineSignals so they participate in
the unified arbitration and impact-weighting pipeline.

These signals carry lower base_score (5.0) as they are advisory;
they won't override strong rule-based signals (confidence=0.5).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from services.recommendation_engine.base_engine import BaseEngine
from services.recommendation_engine.context import EngineSignal, RecommendationContext

logger = logging.getLogger(__name__)


class DriftEngine(BaseEngine):
    """Emit advisory signals from the target_allocator → deviation pipeline."""

    engine_name = "DriftEngine"

    def generate(self, ctx: RecommendationContext) -> List[EngineSignal]:
        if not ctx.deviation_result:
            # Emit explicit telemetry so ops can distinguish "no target" from "no drift".
            # Silent return here was masking how often this engine was actually skipped.
            logger.info("[DriftEngine] skipped:no_target for user context (deviation_result is None)")
            ctx.telemetry["skipped:no_target"] = True
            return []

        signals: List[EngineSignal] = []
        try:
            dev_rows = getattr(ctx.deviation_result, "rows", []) or []
            for row in dev_rows:
                hard_pp = float(getattr(row, "hard_pp", 0) or 0)
                asset_class = getattr(row, "asset_class", "") or ""
                if abs(hard_pp) < 1.0:
                    continue  # minor drift — skip

                action_type = "ADD" if hard_pp < 0 else "EXIT"  # negative = underweight
                instrument_name = f"{asset_class} rebalance"
                suggested_amount_rs = abs(hard_pp / 100.0) * ctx.total_value_rs

                reason_text = (
                    f"{asset_class} is {'under' if hard_pp < 0 else 'over'}weight "
                    f"by {abs(hard_pp):.1f}pp vs target. "
                    f"{'Adding' if action_type == 'ADD' else 'Trimming'} ≈ ₹{suggested_amount_rs:,.0f}."
                )

                sig = EngineSignal(
                    signal_id=f"drift::{action_type}::{asset_class}",
                    engine_name=self.engine_name,
                    rule_label="Drift",
                    action_type=action_type,
                    instrument_id=None,
                    instrument_name=instrument_name,
                    amount_rs=suggested_amount_rs,
                    base_score=5.0,
                    confidence=0.5,
                    risk_reduction=0.3 if action_type == "EXIT" else 0.2,
                    diversification_gain=0.4,
                    urgency=min(abs(hard_pp) / 20.0, 1.0),
                    implementation_ease=0.5,
                    reason_codes=["DRIFT_REBALANCE"],
                    reason_text=reason_text,
                    dedup_key=f"{action_type}::drift::{asset_class}",
                )
                signals.append(sig)

        except Exception as exc:
            logger.exception("[DriftEngine] error building drift signals: %s", exc)

        return signals
