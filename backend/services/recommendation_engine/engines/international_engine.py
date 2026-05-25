"""
InternationalEngine — Rule 10: Add international fund when exposure < target.

Pure engine: no I/O. Reads international_funds_cache from context
(pre-fetched by orchestrator.build_context()).
"""
from __future__ import annotations

import logging
from typing import List

from services.recommendation_engine.base_engine import BaseEngine
from services.recommendation_engine.context import EngineSignal, RecommendationContext

logger = logging.getLogger(__name__)


class InternationalEngine(BaseEngine):
    """Rule 10 (P2): International fund gap → ADD global exposure when below target %."""

    engine_name = "InternationalEngine"
    enabled_config_key = "rule_10_international_fund_gap.enabled"

    def generate(self, ctx: RecommendationContext) -> List[EngineSignal]:
        from services import international_funds as _intl

        r10_cfg = ctx.rules_cfg.get("rule_10_international_fund_gap", {})
        params = r10_cfg.get("params", {})
        min_gap_pct = float(params.get("min_intl_gap_pct", 2.0))
        min_portfolio = float(params.get("min_portfolio_value_rs", 500000))
        total_value = ctx.total_value_rs

        if total_value < min_portfolio:
            logger.debug(
                "[InternationalEngine] portfolio ₹%.0f < min ₹%.0f — skipping",
                total_value, min_portfolio,
            )
            return []

        # Compute current international exposure
        intl_value = 0.0
        for m in ctx.mf_holdings:
            name = m.get("name") or m.get("scheme_name") or ""
            cat = m.get("category") or ""
            if _intl.classify_international(name, cat) is not None:
                qty = float(m.get("quantity") or 0)
                cp = float(m.get("current_price") or 0)
                intl_value += qty * cp
        current_intl_pct = (intl_value / total_value * 100.0) if total_value > 0 else 0.0

        risk = ctx.risk_profile.lower()
        target_info = _intl.compute_target_international_pct(risk_profile=risk)
        target_pct = float(target_info.get("pct", 0))
        gap_pct = target_pct - current_intl_pct

        logger.debug(
            "[InternationalEngine] current=%.1f%% target=%.1f%% gap=%.1f%%",
            current_intl_pct, target_pct, gap_pct,
        )

        if gap_pct < min_gap_pct or target_pct <= 0:
            return []

        gap_rs = total_value * (gap_pct / 100.0)

        # Pick best fund from pre-fetched cache (core quality band only)
        best_fund = None
        for f in ctx.international_funds_cache:
            if (
                _intl._band_for(_intl._quality_score(f)) == "core"
                and not _intl._portfolio_overrides(
                    f,
                    us_exposure_pct=current_intl_pct,
                    it_concentration_pct=0.0,
                    risk_profile=risk,
                )
            ):
                if best_fund is None or _intl._quality_score(f) > _intl._quality_score(best_fund):
                    best_fund = f

        fund_name = (best_fund or {}).get("scheme_name") or "An international fund of funds"
        expense = (best_fund or {}).get("expense_ratio_direct")
        ret_3y = (best_fund or {}).get("ret_3y")

        detail_parts = []
        if ret_3y is not None:
            detail_parts.append(f"3Y return {ret_3y:.1f}%")
        if expense is not None:
            detail_parts.append(f"expense {expense:.2f}%")
        detail_str = f" ({', '.join(detail_parts)})" if detail_parts else ""

        reason_text = (
            f"Your portfolio has {current_intl_pct:.0f}% international exposure — "
            f"{target_pct:.0f}% is recommended for a {risk} risk profile. "
            f"Adding {fund_name}{detail_str} gives you 5–10% global exposure, "
            f"reducing India-concentration risk."
        )

        signal = EngineSignal(
            signal_id=f"international_engine::add::{fund_name[:30]}",
            engine_name=self.engine_name,
            rule_label="Rule 10",
            action_type="ADD",
            instrument_id=(best_fund or {}).get("scheme_code"),
            instrument_name=fund_name,
            amount_rs=round(gap_rs, 2),
            base_score=7.0,           # P2 medium priority
            confidence=0.6,           # MEDIUM
            diversification_gain=min(gap_pct / max(target_pct, 1.0), 1.0),
            urgency=0.3,
            implementation_ease=0.8,  # simple single ADD
            reason_codes=["INTERNATIONAL_DIVERSIFICATION", "GEOGRAPHIC_GAP"],
            reason_text=reason_text,
            dedup_key="ADD::international",
        )
        # Stash fund details so _signals_to_actions() can build full action dict
        signal.__dict__["_fund_details"] = {
            "fund_name": fund_name,
            "fund_type": "International Fund of Funds",
            "bucket": (best_fund or {}).get("bucket", "Global"),
            "expense_ratio": expense,
            "ret_3y": ret_3y,
            "aum_cr": (best_fund or {}).get("aum_cr"),
            "suggested_amount_rs": round(gap_rs, 0),
            "target_pct": target_pct,
            "current_pct": round(current_intl_pct, 2),
        }

        logger.info(
            "[InternationalEngine] ADD %s gap=%.1f%% ₹%.0f",
            fund_name[:40], gap_pct, gap_rs,
        )
        return [signal]
