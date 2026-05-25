"""
StockScoringEngine — §10.9: Direct equity Exit / Trim / Review signals.

Quality Score (0-100):
  0.25 × ROE  +  0.20 × earnings_consistency  +  0.20 × EPS_growth
  + 0.15 × debt_ratio  +  0.10 × promoter_holding  +  0.10 × market_cap_stability

Exit Score (0-100):
  0.25 × PE_overvaluation  +  0.25 × earnings_decline  +  0.20 × quality_deterioration
  + 0.10 × debt_spike  +  0.10 × liquidity_risk  +  0.10 × tax_impact

Thresholds: EXIT ≥ 75,  TRIM 60–75,  REVIEW quality < 45.
NOTE: EXIT and REVIEW are independent signals.

Data source: NIDP stock_features_daily via /stocks/v3-primitives/bulk
  (pre-fetched by orchestrator.run_engine_pipeline() into ctx.v3_scores)

Rule book §10.9
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from services.recommendation_engine.base_engine import BaseEngine
from services.recommendation_engine.context import EngineSignal, RecommendationContext

logger = logging.getLogger(__name__)

_MCAP_STABILITY = {"LARGE_CAP": 80.0, "MID_CAP": 60.0, "SMALL_CAP": 40.0, "MICRO_CAP": 20.0}


def _stock_quality_score(p: Dict[str, Any]) -> float:
    """Quality score 0-100 per §10.9 rule book."""
    roe = float(p.get("roe_pct") or 0)
    roe_s = min(100.0, max(0.0, roe / 30.0 * 100.0))

    consistency_raw = p.get("earnings_consistency_score")
    consistency_s = float(consistency_raw) if consistency_raw is not None else 50.0
    consistency_s = min(100.0, max(0.0, consistency_s))

    eps = float(p.get("eps_growth_3y_cagr_pct") or p.get("eps_growth_yoy_pct") or 0)
    eps_s = min(100.0, max(0.0, (eps + 10.0) / 50.0 * 100.0))

    de = float(p.get("debt_to_equity") or 0)
    de_s = max(0.0, 100.0 - de * 30.0)

    promoter = float(p.get("promoter_holding_pct") or p.get("promoter_pct") or 50.0)
    promoter_s = min(100.0, max(0.0, promoter))

    bucket = (p.get("market_cap_bucket") or "MID_CAP").upper()
    mcap_s = _MCAP_STABILITY.get(bucket, 50.0)

    return round(
        0.25 * roe_s + 0.20 * consistency_s + 0.20 * eps_s
        + 0.15 * de_s + 0.10 * promoter_s + 0.10 * mcap_s,
        1,
    )


def _stock_exit_score(p: Dict[str, Any], quality_score: float) -> float:
    """Exit score 0-100 per §10.9 rule book."""
    pe_over = float(p.get("pe_overvaluation_pct") or p.get("pe_vs_sector_pct") or 0)
    pe_s = min(100.0, max(0.0, pe_over))

    earnings_decline = bool(p.get("earnings_decline_flag"))
    ed_s = 100.0 if earnings_decline else 0.0

    quality_detn_s = max(0.0, 100.0 - quality_score)

    debt_spike = bool(p.get("debt_spike_flag"))
    ds_s = 100.0 if debt_spike else 0.0

    liquidity = float(p.get("liquidity_score") or 50.0)
    liq_s = max(0.0, 100.0 - liquidity)

    tax_s = 30.0  # neutral default; DV-3 would suppress if cost basis missing

    return round(
        0.25 * pe_s + 0.25 * ed_s + 0.20 * quality_detn_s
        + 0.10 * ds_s + 0.10 * liq_s + 0.10 * tax_s,
        1,
    )


class StockScoringEngine(BaseEngine):
    """§10.9: Quality + Exit scoring for direct equity holdings."""

    engine_name = "StockScoringEngine"

    def generate(self, ctx: RecommendationContext) -> List[EngineSignal]:
        if not ctx.stock_holdings:
            return []

        signals: List[EngineSignal] = []

        for h in ctx.stock_holdings:
            symbol = (h.get("ticker") or h.get("symbol") or "").upper().strip()
            iid = h.get("instrument_id") or ""

            # Look up primitives: keyed by instrument_id, symbol, or name
            prims: Dict[str, Any] = {}
            for key in (iid, symbol):
                if key:
                    bundle = ctx.v3_scores.get(key, {})
                    if bundle:
                        prims = bundle.get("v3_primitives") or bundle
                        break

            if not prims:
                continue

            quality_score = _stock_quality_score(prims)
            exit_score = _stock_exit_score(prims, quality_score)

            holding_value = float(h.get("quantity", 0)) * float(h.get("current_price", 0))
            fund_name = h.get("name") or symbol

            # Build driver reason codes
            reason_codes: List[str] = []
            if float(prims.get("pe_overvaluation_pct") or prims.get("pe_vs_sector_pct") or 0) > 30:
                reason_codes.append("STOCK_PE_OVERVALUED")
            if prims.get("earnings_decline_flag"):
                reason_codes.append("STOCK_EARNINGS_DECLINE")
            if prims.get("debt_spike_flag"):
                reason_codes.append("STOCK_DEBT_SPIKE")
            if float(prims.get("debt_to_equity") or 0) > 2.0:
                reason_codes.append("STOCK_HIGH_LEVERAGE")

            # §10.9 Action Thresholds
            if exit_score >= 75:
                reason_codes = ["STOCK_EXIT_SCORE_HIGH"] + reason_codes
                reason_text = (
                    f"{fund_name} has a high exit score ({exit_score:.0f}/100). "
                    + (f"Earnings declining. " if "STOCK_EARNINGS_DECLINE" in reason_codes else "")
                    + (f"PE {float(prims.get('pe_overvaluation_pct') or 0):.0f}% above sector avg. " if "STOCK_PE_OVERVALUED" in reason_codes else "")
                    + f"Quality score: {quality_score:.0f}/100."
                )
                signals.append(EngineSignal(
                    signal_id=f"stock_scoring::exit::{iid or symbol}",
                    engine_name=self.engine_name,
                    rule_label="§10.9 EXIT",
                    action_type="EXIT",
                    instrument_id=iid or None,
                    instrument_name=fund_name,
                    amount_rs=holding_value,
                    base_score=exit_score / 10.0,   # normalize 0-100 → 0-10
                    confidence=0.8 if exit_score >= 85 else 0.65,
                    risk_reduction=0.5,
                    diversification_gain=0.3,
                    urgency=0.6 if exit_score >= 85 else 0.4,
                    implementation_ease=0.5,
                    reason_codes=reason_codes,
                    reason_text=reason_text,
                    dedup_key=f"EXIT::{iid or symbol}",
                ))
                signals[-1].__dict__["_holding"] = h
                signals[-1].__dict__["_stock_quality_score"] = quality_score
                signals[-1].__dict__["_stock_exit_score"] = exit_score

            elif exit_score >= 60:
                reason_codes = ["STOCK_TRIM"] + reason_codes
                signals.append(EngineSignal(
                    signal_id=f"stock_scoring::trim::{iid or symbol}",
                    engine_name=self.engine_name,
                    rule_label="§10.9 TRIM",
                    action_type="TRIM",
                    instrument_id=iid or None,
                    instrument_name=fund_name,
                    amount_rs=holding_value * 0.5,  # trim ~50%
                    base_score=exit_score / 10.0,
                    confidence=0.65,
                    risk_reduction=0.35,
                    urgency=0.3,
                    implementation_ease=0.6,
                    reason_codes=reason_codes,
                    reason_text=(
                        f"{fund_name} exit score {exit_score:.0f}/100 suggests reducing position. "
                        f"Quality score: {quality_score:.0f}/100."
                    ),
                    dedup_key=f"TRIM::{iid or symbol}",
                ))
                signals[-1].__dict__["_holding"] = h

            # REVIEW is independent of EXIT/TRIM
            if quality_score < 45:
                signals.append(EngineSignal(
                    signal_id=f"stock_scoring::review::{iid or symbol}",
                    engine_name=self.engine_name,
                    rule_label="§10.9 REVIEW",
                    action_type="HOLD",
                    instrument_id=iid or None,
                    instrument_name=fund_name,
                    amount_rs=holding_value,
                    base_score=3.0,
                    confidence=0.6,
                    risk_reduction=0.2,
                    urgency=0.2,
                    implementation_ease=0.7,
                    reason_codes=["STOCK_QUALITY_LOW"],
                    reason_text=(
                        f"{fund_name} quality score is {quality_score:.0f}/100 — "
                        f"below the 45-point threshold. Monitor closely for deterioration."
                    ),
                    dedup_key=f"HOLD::review::{iid or symbol}",
                ))

        return signals
