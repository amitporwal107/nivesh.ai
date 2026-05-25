"""
AllocationEngine — Rule 5 (V2.5 Dynamic Debt Target).

ADD a debt fund when portfolio debt % is below the risk-profile-based target.

Pure engine: all data from context.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from services.recommendation_engine.base_engine import BaseEngine
from services.recommendation_engine.context import EngineSignal, RecommendationContext

logger = logging.getLogger(__name__)

# Static debt fund suggestions (no DB call needed)
_DEBT_FUNDS = [
    {"fund_name": "ICICI Prudential Corporate Bond Fund - Direct Growth", "amc": "ICICI", "fund_type": "Corporate Bond", "expense_ratio": 0.23, "aum": "₹18,500 Cr", "rating": "5-Star (CRISIL)", "returns_3y": "7.1%"},
    {"fund_name": "Axis Treasury Advantage Fund - Direct Growth",          "amc": "AXIS",  "fund_type": "Ultra Short Duration", "expense_ratio": 0.18, "aum": "₹12,000 Cr", "rating": "4-Star", "returns_3y": "6.8%"},
    {"fund_name": "SBI Magnum Gilt Fund - Direct Growth",                  "amc": "SBI",   "fund_type": "Gilt Fund",           "expense_ratio": 0.35, "aum": "₹9,500 Cr",  "rating": "4-Star", "returns_3y": "6.9%"},
    {"fund_name": "Kotak Corporate Bond Fund - Direct Growth",             "amc": "KOTAK", "fund_type": "Corporate Bond",      "expense_ratio": 0.32, "aum": "₹8,200 Cr",  "rating": "5-Star", "returns_3y": "7.0%"},
    {"fund_name": "HDFC Corporate Bond Fund - Direct Plan - Growth",       "amc": "HDFC",  "fund_type": "Corporate Bond",      "expense_ratio": 0.25, "aum": "₹25,000 Cr", "rating": "5-Star (CRISIL)", "returns_3y": "7.2%"},
]


def _calc_asset_allocation(holdings: List[Dict[str, Any]]) -> Dict[str, float]:
    total = sum(h["quantity"] * h["current_price"] for h in holdings) or 1
    equity = sum(
        h["quantity"] * h["current_price"] for h in holdings
        if h.get("asset_type", "").lower() in {"equity", "stock", "mutual_fund", "mutual fund"}
    )
    debt = sum(
        h["quantity"] * h["current_price"] for h in holdings
        if h.get("asset_type", "").lower() == "debt"
    )
    return {
        "equity_pct": round(equity / total * 100, 2),
        "debt_pct": round(debt / total * 100, 2),
    }


def _suggest_debt_fund(amount: float, excluded_amcs: List[str]) -> Dict[str, Any]:
    available = [f for f in _DEBT_FUNDS if f["amc"] not in excluded_amcs] or _DEBT_FUNDS
    if amount >= 500_000:
        return available[0]
    if amount >= 200_000:
        return available[min(1, len(available) - 1)]
    return available[min(2, len(available) - 1)]


def _debt_target(risk: str, params: Dict[str, Any]) -> float:
    if risk in ("conservative", "low"):
        return float(params.get("debt_target_conservative_pct", 30.0))
    if risk in ("aggressive", "high"):
        return float(params.get("debt_target_aggressive_pct", 10.0))
    return float(params.get("debt_target_medium_pct", 20.0))


class AllocationEngine(BaseEngine):
    """Rule 5 (P2): ADD debt fund when debt % is below risk-based target."""

    engine_name = "AllocationEngine"
    enabled_config_key = "rule_5_debt_allocation.enabled"

    def generate(self, ctx: RecommendationContext) -> List[EngineSignal]:
        if ctx.total_value_rs <= 0:
            return []

        r5_params = (ctx.rules_cfg.get("rule_5_debt_allocation") or {}).get("params", {})
        risk = ctx.risk_profile.lower()
        target = _debt_target(risk, r5_params)

        alloc = _calc_asset_allocation(ctx.holdings)
        debt_pct = alloc["debt_pct"]

        logger.debug(
            "[AllocationEngine] risk=%s target=%.1f%% debt=%.1f%%",
            risk, target, debt_pct,
        )

        if debt_pct >= target:
            return []

        # Determine AMC exclusions (same threshold as Rule 2)
        amc_threshold = float(
            (ctx.rules_cfg.get("rule_2_amc_concentration") or {})
            .get("params", {})
            .get("threshold_pct", 15.0)
        )
        # Compute AMC exposure from mf_investments in portfolio_intelligence
        mf_investments = ctx.portfolio_intelligence.get("mf_investments") or []
        total_mf_value = sum(float(m.get("amount_rs") or 0) for m in mf_investments) or 1.0
        amc_totals: Dict[str, float] = {}
        for m in mf_investments:
            amc = (m.get("amc") or "").strip().upper()
            if amc:
                amc_totals[amc] = amc_totals.get(amc, 0.0) + float(m.get("amount_rs") or 0)
        excluded_amcs = [
            amc for amc, val in amc_totals.items()
            if (val / total_mf_value * 100) > amc_threshold
        ]

        gap_pct = target - debt_pct
        gap_rs = ctx.total_value_rs * (gap_pct / 100.0)
        fund = _suggest_debt_fund(gap_rs, excluded_amcs)
        fund_name = fund["fund_name"]
        fund_type = fund.get("fund_type", "")

        reason_text = (
            f"Portfolio debt is {debt_pct:.0f}% — below your {target:.0f}% target "
            f"for a {risk} risk profile. "
            f"Consider {fund_name} ({fund_type})"
        )

        signal = EngineSignal(
            signal_id=f"allocation_engine::add::debt::{fund_name[:20]}",
            engine_name=self.engine_name,
            rule_label="Rule 5",
            action_type="ADD",
            instrument_id=None,
            instrument_name=fund_name,
            amount_rs=round(gap_rs, 2),
            base_score=6.0,
            confidence=0.6,           # MEDIUM
            risk_reduction=0.3,
            diversification_gain=0.5,
            urgency=0.4,
            implementation_ease=0.8,
            reason_codes=["ALLOCATION_GAP", "DIVERSIFICATION"],
            reason_text=reason_text,
            dedup_key="ADD::debt",
        )
        signal.__dict__["_fund_details"] = fund
        return [signal]
