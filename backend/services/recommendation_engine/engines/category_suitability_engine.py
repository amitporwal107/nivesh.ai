"""
CategorySuitabilityEngine — PRD §4 Master Rule 2 + §6.1.

Suitability gate: any holding in a category NOT allowed for the user's risk persona
triggers an EXIT signal, regardless of quality score. Category-fit is checked before
score (PRD §4 Rule 2).

Examples:
  Conservative — small-cap, sectoral, thematic → EXIT
  Moderate     — small-cap above 10% sub-cap   → TRIM/EXIT
  Growth       — any category allowed except pure debt
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from services.recommendation_engine.base_engine import BaseEngine
from services.recommendation_engine.context import EngineSignal, RecommendationContext
from services.recommendation_engine.helpers import fuzzy_match_holding

logger = logging.getLogger(__name__)

# Severity mapping for suitability violations (PRD §8)
_SUITABILITY_SEVERITY = "severe"   # category mismatch is always severe (PRD §8)


def _category_matches_keyword(category: str, keywords: List[str]) -> bool:
    cat = (category or "").lower()
    return any(kw in cat for kw in keywords)


class CategorySuitabilityEngine(BaseEngine):
    """
    PRD §4 Rule 2 — Category suitability gate.

    Emits EXIT (or TRIM for partially over-cap sub-categories) for every
    holding in a category that is not in the persona's allowed set.
    """

    engine_name = "CategorySuitabilityEngine"
    enabled_config_key = "category_suitability.enabled"

    def generate(self, ctx: RecommendationContext) -> List[EngineSignal]:
        if not ctx.persona_profile:
            return []

        cfg = ctx.rules_cfg.get("category_suitability") or {}
        if not cfg.get("enabled", True):
            return []

        persona = ctx.persona_profile
        mf_investments = ctx.portfolio_intelligence.get("mf_investments") or []
        signals: List[EngineSignal] = []
        seen_ids: set = set()

        # Total MF value for sub-cap weight calculations
        total_mf_value = sum(float(m.get("amount_rs", 0)) for m in mf_investments) or 1.0

        for mf in mf_investments:
            if not mf.get("resolved"):
                continue
            iid = mf.get("instrument_id")
            if iid in ctx.exited_ids or iid in seen_ids:
                continue

            category = (mf.get("category") or mf.get("fund_category") or "").strip()
            if not category:
                continue

            amount_rs = float(mf.get("amount_rs", 0))
            weight_pct = amount_rs / total_mf_value * 100.0

            # ── Hard suitability check: is this category allowed at all? ─────
            allowed = persona.category_allowed(category)
            if not allowed:
                h = fuzzy_match_holding(mf.get("scheme_name", ""), ctx.mf_holdings)
                fund_name = (h or {}).get("name") or mf.get("scheme_name") or category
                amt = (
                    float(h.get("quantity", 0)) * float(h.get("current_price", 0))
                    if h else amount_rs
                )
                candidate = next(
                    (c for c in ctx.exit_candidates if c.get("instrument_id") == iid), None
                )
                estimated_tax = float(
                    (candidate.get("tax_impact") or {}).get("tax_liability") or 0
                ) if candidate else 0.0
                sig = EngineSignal(
                    signal_id=f"cat_suit::exit::{iid or fund_name[:20]}",
                    engine_name=self.engine_name,
                    rule_label="CS-1",
                    action_type="EXIT",
                    instrument_id=iid,
                    instrument_name=fund_name,
                    amount_rs=amt,
                    base_score=8.5,
                    confidence=0.9,
                    risk_reduction=0.9,
                    urgency=0.8,
                    implementation_ease=0.5,
                    estimated_tax_rs=estimated_tax,
                    reason_codes=["CATEGORY_SUITABILITY_BREACH"],
                    reason_text=(
                        f"{category} funds are not permitted for your {persona.persona_type.value} risk profile. "
                        f"This holding ({fund_name}) exceeds your risk band regardless of its quality score."
                    ),
                    dedup_key=f"EXIT::{iid or fund_name[:30]}",
                    severity=_SUITABILITY_SEVERITY,
                    execution_path="redirect",
                    requires_confirmation=ctx.behavioural_confidence < 0.7,
                )
                if h:
                    sig.__dict__["_holding"] = h
                if candidate:
                    sig.__dict__["_candidate"] = candidate
                signals.append(sig)
                if iid:
                    seen_ids.add(iid)
                continue

            # ── Sub-cap check: category is allowed but weight exceeds persona cap ──
            # Check each sub-category keyword against persona.equity_sub_caps
            for sub_kw, cap_pct in (persona.equity_sub_caps or {}).items():
                if cap_pct >= 100.0:
                    continue
                if sub_kw not in category.lower():
                    continue

                # Compute total portfolio weight in this sub-category
                total_sub_weight = sum(
                    float(m.get("amount_rs", 0)) / total_mf_value * 100.0
                    for m in mf_investments
                    if sub_kw in (m.get("category") or "").lower()
                )
                if total_sub_weight <= cap_pct + 0.5:
                    break

                # Over-cap → TRIM the largest holding in this sub-category
                if iid in seen_ids:
                    break
                excess_pct = round(total_sub_weight - cap_pct, 1)
                h = fuzzy_match_holding(mf.get("scheme_name", ""), ctx.mf_holdings)
                fund_name = (h or {}).get("name") or mf.get("scheme_name") or sub_kw
                full_amt = (
                    float(h.get("quantity", 0)) * float(h.get("current_price", 0))
                    if h else amount_rs
                )
                trim_rs = (excess_pct / 100.0) * ctx.total_value_rs
                candidate = next(
                    (c for c in ctx.exit_candidates if c.get("instrument_id") == iid), None
                )
                # Tax is proportional to the trimmed fraction of the holding
                trim_fraction = (trim_rs / full_amt) if full_amt > 0 else 0.0
                estimated_tax = float(
                    (candidate.get("tax_impact") or {}).get("tax_liability") or 0
                ) * trim_fraction if candidate else 0.0
                sig = EngineSignal(
                    signal_id=f"cat_suit::trim::{sub_kw}::{ctx.risk_profile}",
                    engine_name=self.engine_name,
                    rule_label="CS-2",
                    action_type="TRIM",
                    instrument_id=iid,
                    instrument_name=fund_name,
                    amount_rs=trim_rs,
                    base_score=6.5,
                    confidence=0.75,
                    risk_reduction=0.7,
                    urgency=0.6,
                    implementation_ease=0.5,
                    estimated_tax_rs=estimated_tax,
                    reason_codes=["SUB_CATEGORY_CAP_BREACH"],
                    reason_text=(
                        f"{sub_kw.title()} allocation ({total_sub_weight:.0f}%) exceeds your "
                        f"{persona.persona_type.value} profile cap of {cap_pct:.0f}% by {excess_pct:.0f}pp. "
                        f"Trimming the highest exit-score {sub_kw} holding."
                    ),
                    dedup_key=f"TRIM::{sub_kw}_sub_cap",
                    severity="mismatch",
                    execution_path="redirect",
                    requires_confirmation=ctx.behavioural_confidence < 0.7,
                )
                if h:
                    sig.__dict__["_holding"] = h
                if candidate:
                    sig.__dict__["_candidate"] = candidate
                signals.append(sig)
                if iid:
                    seen_ids.add(iid)
                break  # one signal per holding per loop

        return signals
