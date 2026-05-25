"""
DataValidationEngine — DV-1..DV-3: Data quality gate.

DV-1: If portfolio price coverage < threshold (default 90%) emit an informational
      HOLD signal so the user knows recommendations may be less accurate.
DV-2: (handled upstream) — instrument_id resolution failures, no signal needed.
DV-3: Holdings without buy_price / average_cost are listed in
      ctx.tax_suppressed_instrument_ids (populated in orchestrator.build_context());
      this engine emits no signal but the set is consumed by ArbitrationEngine to
      suppress EXIT signals where we can't compute STCG/LTCG correctly.

Rule book §10.1
"""
from __future__ import annotations

import logging
from typing import List

from services.recommendation_engine.base_engine import BaseEngine
from services.recommendation_engine.context import EngineSignal, RecommendationContext

logger = logging.getLogger(__name__)


class DataValidationEngine(BaseEngine):
    """DV-1: Coverage warning when price data is incomplete."""

    engine_name = "DataValidationEngine"
    enabled_config_key = "data_validation.enabled"

    def generate(self, ctx: RecommendationContext) -> List[EngineSignal]:
        cfg = ctx.rules_cfg.get("data_validation") or {}
        if not cfg.get("enabled", True):
            return []

        signals: List[EngineSignal] = []
        coverage_threshold = float(cfg.get("coverage_threshold_pct", 90.0))

        # DV-1: Low price coverage → suppress allocation recommendations
        if ctx.portfolio_coverage_pct < coverage_threshold:
            coverage = round(ctx.portfolio_coverage_pct, 1)
            signals.append(EngineSignal(
                signal_id="dv1::coverage_low",
                engine_name=self.engine_name,
                rule_label="DV-1",
                action_type="HOLD",
                instrument_id=None,
                instrument_name="Portfolio",
                amount_rs=0.0,
                base_score=2.0,
                confidence=0.9,
                urgency=0.2,
                reason_codes=["DV1_COVERAGE_LOW"],
                reason_text=(
                    f"Price data coverage is {coverage}% (below the {coverage_threshold:.0f}% threshold). "
                    f"Some recommendations may be less accurate until all holdings have current prices."
                ),
                dedup_key="HOLD::dv1_coverage",
            ))
            logger.info(
                "[DataValidationEngine] DV-1 fired: coverage %.1f%% < %.0f%%",
                coverage, coverage_threshold,
            )

        # DV-2: Stale price/NAV check — per-instrument staleness
        # as_of_date available from ctx.v3_scores[iid]["v3_primitives"]["as_of_date"] (stocks)
        # or ctx.v3_scores[iid]["v3_primitives"]["latest_nav_date"] (MFs)
        from datetime import date, timedelta

        today = date.today()

        def _is_stale(as_of_str: str | None) -> bool:
            if not as_of_str:
                return False  # no date → don't know, don't suppress
            try:
                d = date.fromisoformat(str(as_of_str)[:10])
                # Approx market days: 7 calendar days ≈ 5 market days (ignores holidays)
                return (today - d).days > 7
            except (ValueError, TypeError):
                return False

        stale_ids = set()
        for iid, v3 in ctx.v3_scores.items():
            prims = v3.get("v3_primitives") or {}
            as_of = prims.get("as_of_date") or prims.get("latest_nav_date")
            if _is_stale(as_of):
                stale_ids.add(iid)

        if stale_ids:
            # Attach to context for downstream engines (best effort — ctx is mutable by convention)
            ctx.__dict__.setdefault("_dv2_stale_ids", set()).update(stale_ids)
            logger.info(
                "[DataValidationEngine] DV-2: %d instrument(s) have stale price/NAV data",
                len(stale_ids),
            )
            for iid in list(stale_ids)[:3]:  # sample in log
                logger.debug("[DataValidationEngine] DV-2 stale: %s", iid)

        # DV-3: Log suppressed holdings (no signal — ArbitrationEngine uses the set)
        n_suppressed = len(ctx.tax_suppressed_instrument_ids)
        if n_suppressed:
            logger.info(
                "[DataValidationEngine] DV-3: %d holding(s) missing cost basis — "
                "tax-aware EXIT signals suppressed for them.",
                n_suppressed,
            )

        return signals
