"""
RegularDirectEngine — Rules 1 + 6.

Rule 1: EXIT Regular plan when Direct plan of the same fund already exists.
Rule 6: SWITCH Regular → Direct when total annual cost leak > ₹10K (no Direct twin).

Note: V3 switch_score gating is handled via ctx.v3_scores when available.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from services.recommendation_engine.base_engine import BaseEngine
from services.recommendation_engine.context import EngineSignal, RecommendationContext
from services.recommendation_engine.helpers import (
    classify_plan_type,
    normalize_base_scheme_name,
    normalize_fund_name,
)

logger = logging.getLogger(__name__)


def _holding_key(h: Dict[str, Any]) -> str:
    return f"{h.get('user_id','')}::{normalize_fund_name(h.get('name',''))}"


def _estimate_cost_leak(
    regular_holding: Dict[str, Any],
    mf_investments: List[Dict[str, Any]],
) -> float:
    """Estimate annual cost leak (₹) = holding_value × (regular_er - direct_er)."""
    name = regular_holding.get("name") or regular_holding.get("scheme_name") or ""
    base = normalize_base_scheme_name(name)
    value_rs = float(regular_holding.get("quantity", 0)) * float(regular_holding.get("current_price", 0))
    if not value_rs:
        return 0.0
    # Look for matching mf_investment to get expense ratios
    for mf in mf_investments:
        if normalize_base_scheme_name(mf.get("scheme_name", "")) == base:
            er = float(mf.get("expense_ratio") or 0)
            # Estimate Direct ER ≈ Regular ER − 0.7% (typical delta)
            if er > 0.7:
                return value_rs * 0.007
    return 0.0


def _find_pairs(mf_holdings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Group by base name; return groups with both Regular and Direct."""
    groups: Dict[str, Dict] = {}
    for h in mf_holdings:
        base = normalize_base_scheme_name(h.get("name", ""))
        if not base:
            continue
        plan = classify_plan_type(h.get("name", ""))
        g = groups.setdefault(base, {"regular": None, "direct": None})
        if plan == "direct" and g["direct"] is None:
            g["direct"] = h
        elif plan == "regular" and g["regular"] is None:
            g["regular"] = h
    return [g for g in groups.values() if g["regular"] and g["direct"]]


def _find_regular_without_direct(
    mf_holdings: List[Dict[str, Any]], pairs: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    paired_regulars = {normalize_fund_name(p["regular"].get("name", "")) for p in pairs}
    return [
        h for h in mf_holdings
        if classify_plan_type(h.get("name", "")) == "regular"
        and normalize_fund_name(h.get("name", "")) not in paired_regulars
    ]


class RegularDirectEngine(BaseEngine):
    """Rules 1 + 6 (P0): Regular → Direct consolidation and cost-leak switch."""

    engine_name = "RegularDirectEngine"

    @property
    def enabled_config_key(self) -> str:
        return ""  # Always runs; individual sub-rules checked inside generate()

    def generate(self, ctx: RecommendationContext) -> List[EngineSignal]:
        r1_cfg = ctx.rules_cfg.get("rule_1_regular_to_direct") or {}
        r6_cfg = ctx.rules_cfg.get("rule_6_cost_leak_switch") or {}
        r1_enabled = bool(r1_cfg.get("enabled", True))
        r6_enabled = bool(r6_cfg.get("enabled", True))
        mf_investments = ctx.portfolio_intelligence.get("mf_investments") or []

        pairs = _find_pairs(ctx.mf_holdings)
        signals: List[EngineSignal] = []
        local_exited_keys: set = set()

        # ── Rule 1: EXIT Regular when Direct twin exists ──────────────────
        if r1_enabled:
            switch_threshold = float((r1_cfg.get("params") or {}).get("min_switch_score", 1.0))
            candidate_by_name = {
                normalize_fund_name(
                    c.get("instrument_name") or
                    c.get("mf_investment", {}).get("scheme_name", "")
                ): c
                for c in ctx.exit_candidates
            }

            for pair in pairs:
                regular = pair["regular"]
                reg_key = _holding_key(regular)
                if reg_key in ctx.exited_holding_keys or reg_key in local_exited_keys:
                    continue

                cand = candidate_by_name.get(normalize_fund_name(regular.get("name", "")))
                cost_leak = _estimate_cost_leak(regular, mf_investments)

                # V3 switch score gate (when v3 data available)
                switch_s: Optional[float] = None
                if ctx.v3_scores:
                    try:
                        from services import v3_integration
                        switch_s = v3_integration.compute_reg_to_direct_switch_score(
                            regular_holding=regular,
                            cost_leak_rs=cost_leak,
                            v3_scores_by_id=ctx.v3_scores,
                            mf_investments=mf_investments,
                        )
                        if switch_s < switch_threshold:
                            logger.debug(
                                "[RegularDirectEngine] SKIP %s — switch_score=%.2f < %.2f",
                                regular.get("name", "")[:40], switch_s, switch_threshold,
                            )
                            continue
                    except Exception:
                        pass

                fund_name = regular.get("name") or ""
                iid = (cand or {}).get("instrument_id")
                amount_rs = float(regular.get("quantity", 0)) * float(regular.get("current_price", 0))

                reason_text = (
                    (
                        f"Direct plan of same fund exists (expense saving ≈ ₹{cost_leak:,.0f}/yr"
                        + (f", switch score {switch_s:.1f}" if switch_s is not None else "")
                        + "). "
                    ) if cost_leak > 0 else
                    "Direct plan of same fund exists (lower expense ratio). "
                ) + "Regular → Direct consolidation."

                sig = EngineSignal(
                    signal_id=f"regular_direct::r1::{iid or fund_name[:20]}",
                    engine_name=self.engine_name,
                    rule_label="Rule 1",
                    action_type="EXIT",
                    instrument_id=iid,
                    instrument_name=fund_name,
                    amount_rs=amount_rs,
                    base_score=(cand or {}).get("exit_score", 5.0),
                    confidence=0.95,
                    risk_reduction=0.2,
                    diversification_gain=0.1,
                    urgency=0.5,
                    implementation_ease=0.9,
                    estimated_tax_rs=float(
                        ((cand or {}).get("tax_impact") or {}).get("tax_liability") or 0
                    ),
                    reason_codes=["REGULAR_DIRECT_DUPLICATE"],
                    reason_text=reason_text,
                    dedup_key=f"EXIT::{iid or fund_name[:30]}",
                )
                if switch_s is not None:
                    sig.__dict__["switch_score"] = switch_s
                sig.__dict__["_holding"] = regular
                sig.__dict__["_candidate"] = cand

                signals.append(sig)
                local_exited_keys.add(reg_key)

        # ── Rule 6: Cost-leak SWITCH when no Direct twin ──────────────────
        if r6_enabled:
            r6_params = r6_cfg.get("params") or {}
            leak_threshold = float(r6_params.get("total_leak_threshold_rs", 10000.0))
            max_switches = int(r6_params.get("max_switches", 3))
            switch_threshold_6 = float(r6_params.get("min_switch_score", 1.0))

            regulars_no_direct = _find_regular_without_direct(ctx.mf_holdings, pairs)
            leaks = []
            for reg in regulars_no_direct:
                leak = _estimate_cost_leak(reg, mf_investments)
                if leak > 0:
                    leaks.append({"holding": reg, "leak": leak})
            total_leak = sum(x["leak"] for x in leaks)

            if total_leak >= leak_threshold:
                leaks.sort(key=lambda x: x["leak"], reverse=True)
                for item in leaks[:max_switches]:
                    reg = item["holding"]
                    reg_key = _holding_key(reg)
                    if reg_key in ctx.exited_holding_keys or reg_key in local_exited_keys:
                        continue

                    # V3 switch score gate
                    switch_s_6: Optional[float] = None
                    if ctx.v3_scores:
                        try:
                            from services import v3_integration
                            switch_s_6 = v3_integration.compute_reg_to_direct_switch_score(
                                regular_holding=reg,
                                cost_leak_rs=item["leak"],
                                v3_scores_by_id=ctx.v3_scores,
                                mf_investments=mf_investments,
                            )
                            if switch_s_6 < switch_threshold_6:
                                continue
                        except Exception:
                            pass

                    fund_name = reg.get("name") or ""
                    amount_rs = float(reg.get("quantity", 0)) * float(reg.get("current_price", 0))

                    sig = EngineSignal(
                        signal_id=f"regular_direct::r6::{fund_name[:20]}",
                        engine_name=self.engine_name,
                        rule_label="Rule 6",
                        action_type="EXIT",
                        instrument_id=None,
                        instrument_name=fund_name,
                        amount_rs=amount_rs,
                        base_score=6.0,
                        confidence=0.8,
                        risk_reduction=0.1,
                        diversification_gain=0.1,
                        urgency=0.4,
                        implementation_ease=0.9,
                        reason_codes=["COST_LEAK_SWITCH"],
                        reason_text=(
                            f"Annual cost leak ≈ ₹{item['leak']:,.0f} vs Direct equivalent. "
                            f"Switching to Direct saves expense ratio difference."
                        ),
                        dedup_key=f"EXIT::{fund_name[:30]}",
                    )
                    if switch_s_6 is not None:
                        sig.__dict__["switch_score"] = switch_s_6
                    sig.__dict__["_holding"] = reg
                    sig.__dict__["_candidate"] = None

                    signals.append(sig)
                    local_exited_keys.add(reg_key)

        return signals
