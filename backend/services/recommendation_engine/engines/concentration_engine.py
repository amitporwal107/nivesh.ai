"""
ConcentrationEngine — PRD §6.2 single-holding and single-sector caps.

CC-1: Any holding exceeding persona's max_single_holding_pct → TRIM.
CC-2: CategoryConcentrationEngine fires at rules_cfg threshold; this engine
      enforces the persona-specific max_single_sector_pct.

These two rules are universal (§4, "master rules") and must fire even when
the holding is high quality — concentration is a risk constraint, not a
quality judgment.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from services.recommendation_engine.base_engine import BaseEngine
from services.recommendation_engine.context import EngineSignal, RecommendationContext

logger = logging.getLogger(__name__)


class ConcentrationEngine(BaseEngine):
    """CC-1/CC-2: persona-calibrated single-holding and single-sector caps."""

    engine_name = "ConcentrationEngine"
    enabled_config_key = "concentration_engine.enabled"

    def generate(self, ctx: RecommendationContext) -> List[EngineSignal]:
        if not ctx.persona_profile or ctx.total_value_rs <= 0:
            return []

        pp = ctx.persona_profile
        signals: List[EngineSignal] = []

        # ── CC-1: Single-holding concentration ───────────────────────────────
        for h in ctx.holdings:
            iid = h.get("instrument_id")
            value = float(h.get("quantity", 0)) * float(h.get("current_price", 0))
            if value <= 0:
                continue
            weight_pct = value / ctx.total_value_rs * 100.0

            if weight_pct <= pp.max_single_holding_pct:
                continue

            fund_name = h.get("name") or h.get("scheme_name") or ""
            excess_pct = weight_pct - pp.max_single_holding_pct
            trim_rs = ctx.total_value_rs * (excess_pct / 100.0)

            # Severity: 2× cap → severe; otherwise mismatch
            severity = "severe" if weight_pct >= pp.max_single_holding_pct * 2 else "mismatch"

            sig = EngineSignal(
                signal_id=f"concentration::cc1::holding::{iid or fund_name[:20]}",
                engine_name=self.engine_name,
                rule_label="CC-1",
                action_type="TRIM",
                instrument_id=iid,
                instrument_name=fund_name,
                amount_rs=round(trim_rs, 2),
                base_score=7.0,
                confidence=0.85,
                risk_reduction=0.5,
                diversification_gain=0.4,
                urgency=0.6 if severity == "severe" else 0.4,
                implementation_ease=0.7,
                reason_codes=["SINGLE_HOLDING_CONCENTRATION", "CC1"],
                reason_text=(
                    f"{fund_name[:40]} is {weight_pct:.1f}% of your portfolio — "
                    f"above your {pp.persona_type.value} cap of {pp.max_single_holding_pct:.0f}%. "
                    f"Trim ₹{trim_rs:,.0f} and redirect to an underweight category."
                ),
                dedup_key=f"TRIM::concentration::{iid or fund_name[:30]}",
                severity=severity,
                execution_path="redirect",
                requires_confirmation=trim_rs > pp.confirmation_threshold_rs,
            )
            signals.append(sig)

        # ── CC-2: Single-sector concentration (persona-calibrated) ────────────
        # Group holdings by sector from portfolio_intelligence
        sector_exposure = ctx.portfolio_intelligence.get("sector_exposure") or []
        equity_value = ctx.total_value_rs * (
            float((ctx.portfolio_intelligence.get("asset_allocation") or {}).get("equity_pct") or 0) / 100.0
        )
        if equity_value <= 0:
            return signals

        for sector in sector_exposure:
            sector_name = sector.get("sector") or sector.get("name") or ""
            pct = float(sector.get("pct") or sector.get("weight_pct") or 0)
            if pct <= pp.max_single_sector_pct:
                continue

            excess_pct = pct - pp.max_single_sector_pct
            trim_rs = equity_value * (excess_pct / 100.0)
            severity = "severe" if pct >= pp.max_single_sector_pct * 1.5 else "mismatch"

            sig = EngineSignal(
                signal_id=f"concentration::cc2::sector::{sector_name[:20]}",
                engine_name=self.engine_name,
                rule_label="CC-2",
                action_type="TRIM",
                instrument_id=None,
                instrument_name=f"{sector_name} sector",
                amount_rs=round(trim_rs, 2),
                base_score=6.5,
                confidence=0.8,
                risk_reduction=0.4,
                diversification_gain=0.5,
                urgency=0.5 if severity == "severe" else 0.3,
                implementation_ease=0.6,
                reason_codes=["SINGLE_SECTOR_CONCENTRATION", "CC2"],
                reason_text=(
                    f"{sector_name} is {pct:.1f}% of your equity — "
                    f"above your {pp.persona_type.value} cap of {pp.max_single_sector_pct:.0f}%. "
                    f"Trim this sector exposure to reduce single-sector risk."
                ),
                dedup_key=f"TRIM::sector::{sector_name[:30]}",
                severity=severity,
                execution_path="harvest",
            )
            signals.append(sig)

        return signals
