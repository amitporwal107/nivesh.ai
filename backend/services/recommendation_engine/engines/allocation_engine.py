"""
AllocationEngine — Rule 5 (V2.5 Dynamic Debt Target).

ADD a debt fund when portfolio debt % is below the risk-profile-based target.

Phase 2 demotion: DriftEngine now owns all bucket-level sizing (bidirectional).
AllocationEngine is a fallback — it only fires when ctx.deviation_result is None
(i.e. DriftEngine is inactive). Once Phase 3 wires compute_deviation() into
action_plan_manager, AllocationEngine will be dormant for all users with
holdings + risk profile, and can be retired in a future cleanup.

Why this ordering: the two engines would otherwise double-count a debt
underweight — AllocationEngine adds debt AND DriftEngine adds debt for the
same gap. One signal per bucket is enforced by this guard.

Pure engine: all data from context.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from services.recommendation_engine.base_engine import BaseEngine
from services.recommendation_engine.context import EngineSignal, RecommendationContext

logger = logging.getLogger(__name__)

# Static fallback debt fund suggestions (used when NIDP DaaS is unavailable)
_DEBT_FUNDS_FALLBACK = [
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


def _normalise_daas_fund(row: Dict[str, Any]) -> Dict[str, Any]:
    """Normalise a NIDP DaaS screener row to the fund dict shape used by this engine."""
    return {
        "fund_name": row.get("scheme_name") or row.get("fund_name") or "",
        "amc": row.get("amc") or "",
        "fund_type": row.get("category") or row.get("sub_category") or "Debt",
        "expense_ratio": row.get("ter") or row.get("expense_ratio"),
        "aum": row.get("aum_cr"),
        "composite_score": row.get("composite_score"),
        "returns_3y": row.get("return_3y"),
        "isin": row.get("isin"),
    }


def _suggest_debt_fund(
    amount: float,
    excluded_amcs: List[str],
    live_candidates: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Pick the best available debt fund.

    Prefers live NIDP DaaS candidates (already sorted by composite_rank ASC);
    falls back to the static list when DaaS is unavailable.
    """
    candidates = (
        [_normalise_daas_fund(r) for r in live_candidates]
        if live_candidates
        else _DEBT_FUNDS_FALLBACK
    )
    available = [f for f in candidates if f.get("amc") not in excluded_amcs] or candidates
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
    """Rule 5 (P2): ADD debt fund when debt % is below risk-based target (persona-calibrated)."""

    engine_name = "AllocationEngine"
    enabled_config_key = "rule_5_debt_allocation.enabled"

    def generate(self, ctx: RecommendationContext) -> List[EngineSignal]:
        if ctx.total_value_rs <= 0:
            return []

        # Phase 2 demotion: DriftEngine owns bucket sizing when deviation_result is set.
        # Return empty so the two engines never double-count the same bucket gap.
        if ctx.deviation_result is not None:
            logger.debug("[AllocationEngine] deferred to DriftEngine (deviation_result is set)")
            return []

        r5_params = (ctx.rules_cfg.get("rule_5_debt_allocation") or {}).get("params", {})
        risk = ctx.risk_profile.lower()

        # Prefer persona_profile debt target (PRD §6.1); fall back to legacy rules_cfg
        if ctx.persona_profile:
            pp = ctx.persona_profile
            target = pp.debt_mid_target
            equity_target = pp.equity_mid_target
            persona_label = pp.persona_type.value
        else:
            target = _debt_target(risk, r5_params)
            equity_target = 100.0 - target
            persona_label = risk

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
        live_debt = ctx.top_add_candidates.get("debt") or []
        fund = _suggest_debt_fund(gap_rs, excluded_amcs, live_debt)
        fund_name = fund["fund_name"]
        fund_type = fund.get("fund_type", "")

        # Determine severity: how far below target?
        bands_below = int(gap_pct / 10)
        severity = "severe" if bands_below >= 3 else "mismatch" if gap_pct >= 10 else "minor"

        reason_text = (
            f"Debt is {debt_pct:.0f}% — well below your {persona_label} target of {target:.0f}%. "
            f"Point new money to {fund_name} ({fund_type}) to close this gap without triggering tax."
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
            confidence=0.6,
            risk_reduction=0.3,
            diversification_gain=0.5,
            urgency=0.4,
            implementation_ease=0.8,
            reason_codes=["ALLOCATION_GAP", "DIVERSIFICATION"],
            reason_text=reason_text,
            dedup_key="ADD::debt",
            severity=severity,
            execution_path="redirect",   # always prefer new money for ADD
        )
        signal.__dict__["_fund_details"] = fund
        return [signal]
