"""
RiskAlignmentEngine — RA-1..RA-3: Risk-profile compliance checks.

RA-1: Hard caps on smallcap %, sectoral %, single-stock % per risk profile.
      Conservative: SC ≤ 10%, sectoral ≤ 5%, single stock ≤ 8%.
      Moderate:     SC ≤ 20%, sectoral ≤ 15%, single stock ≤ 15%.
      Aggressive:   SC ≤ 35%, sectoral ≤ 25%, single stock ≤ 20%.

RA-2: Portfolio annualised volatility vs profile ceiling.
      Conservative ≤ 10%, Moderate ≤ 18%, Aggressive ≤ 28%.

RA-3: Portfolio max drawdown vs profile ceiling.
      Conservative ≤ 15%, Moderate ≤ 25%, Aggressive ≤ 40%.

Rule book §10.3
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from services.recommendation_engine.base_engine import BaseEngine
from services.recommendation_engine.context import EngineSignal, RecommendationContext

logger = logging.getLogger(__name__)


def _category_pct(ctx: RecommendationContext, category_keyword: str) -> float:
    """Fraction of MF portfolio in funds matching a category keyword (lowercase)."""
    mf_investments = ctx.portfolio_intelligence.get("mf_investments") or []
    total_mf = sum(float(m.get("amount_rs", 0)) for m in mf_investments) or 1.0
    matched = sum(
        float(m.get("amount_rs", 0)) for m in mf_investments
        if category_keyword in (m.get("category") or "").lower()
    )
    return matched / total_mf * 100.0


def _weighted_portfolio_metric(
    ctx: RecommendationContext,
    primitive_key: str,
) -> Optional[float]:
    """Compute holding-weighted average of a V3 primitive (e.g. volatility_1y, max_drawdown_pct)."""
    total_weight = 0.0
    weighted_sum = 0.0
    for iid, hw in ctx.holding_weights.items():
        v3 = ctx.v3_scores.get(iid or "", {})
        if not v3:
            continue
        val = (v3.get("v3_primitives") or {}).get(primitive_key)
        if val is None:
            continue
        total_weight += hw.weight_pct
        weighted_sum += float(val) * hw.weight_pct
    if total_weight < 20.0:   # <20% coverage → not meaningful
        return None
    return weighted_sum / total_weight


def _find_largest_holding_in_category(
    ctx: RecommendationContext, category_keyword: str,
) -> Optional[Dict[str, Any]]:
    """Return the exit candidate with highest exit score in the given category."""
    mf_investments = ctx.portfolio_intelligence.get("mf_investments") or []
    iids_in_cat = {
        m.get("instrument_id") for m in mf_investments
        if category_keyword in (m.get("category") or "").lower()
    }
    best: Optional[Dict[str, Any]] = None
    for cand in ctx.exit_candidates:
        if cand.get("instrument_id") in iids_in_cat:
            if best is None or cand.get("exit_score", 0) > best.get("exit_score", 0):
                best = cand
    return best


class RiskAlignmentEngine(BaseEngine):
    """RA-1..RA-3: Emit TRIM/EXIT signals when portfolio breaches risk-profile limits."""

    engine_name = "RiskAlignmentEngine"
    enabled_config_key = "risk_alignment.enabled"

    def generate(self, ctx: RecommendationContext) -> List[EngineSignal]:
        cfg = ctx.rules_cfg.get("risk_alignment") or {}
        if not cfg.get("enabled", True):
            return []

        risk = ctx.risk_profile.lower()
        signals: List[EngineSignal] = []

        # ── Prefer persona_profile thresholds (PRD §6.2); fall back to rules_cfg ──
        if ctx.persona_profile:
            pp = ctx.persona_profile
            sc_cap = pp.smallcap_cap_pct
            sectoral_cap = pp.sectoral_cap_pct
            vol_cap = pp.max_volatility_1y_pct
            dd_cap = pp.max_drawdown_pct
        else:
            profile_cfg = cfg.get(risk) or cfg.get("moderate") or {}
            vol_caps = cfg.get("volatility_cap_pct") or {}
            dd_caps = cfg.get("drawdown_cap_pct") or {}
            sc_cap = float(profile_cfg.get("smallcap_cap_pct", 20.0))
            sectoral_cap = float(profile_cfg.get("sectoral_cap_pct", 15.0))
            vol_cap = float(vol_caps.get(risk, 18.0))
            dd_cap = float(dd_caps.get(risk, 25.0))
        # single_stock_cap (RA-1c) would require stock-level breakdown — deferred

        sc_pct = _category_pct(ctx, "small cap")
        sectoral_pct = _category_pct(ctx, "sectoral")

        if sc_pct > sc_cap + 0.5:
            cand = _find_largest_holding_in_category(ctx, "small cap")
            excess = round(sc_pct - sc_cap, 1)
            from services.recommendation_engine.helpers import fuzzy_match_holding
            fund_name = (cand or {}).get("instrument_name", "Small Cap Fund")
            h = fuzzy_match_holding(fund_name, ctx.mf_holdings) if cand else None
            amt = (float(h.get("quantity", 0)) * float(h.get("current_price", 0))) if h else 0.0
            _persona_label = (ctx.persona_profile.persona_type.value if ctx.persona_profile else risk)
            _bands_over = max(1, int((sc_pct - sc_cap) / 10))
            signals.append(EngineSignal(
                signal_id=f"risk_alignment::ra1::smallcap::{ctx.risk_profile}",
                engine_name=self.engine_name,
                rule_label="RA-1",
                action_type="EXIT" if cand else "TRIM",
                instrument_id=(cand or {}).get("instrument_id"),
                instrument_name=fund_name,
                amount_rs=amt,
                base_score=6.5,
                confidence=0.8,
                risk_reduction=0.8,
                urgency=0.6,
                implementation_ease=0.5,
                estimated_tax_rs=float(((cand or {}).get("tax_impact") or {}).get("tax_liability") or 0),
                reason_codes=["RA1_SMALLCAP_BREACH"],
                reason_text=(
                    f"Small-cap allocation ({sc_pct:.0f}%) exceeds your {_persona_label} profile limit "
                    f"({sc_cap:.0f}%) by {excess:.0f}pp. This adds more downside risk than your plan allows."
                ),
                dedup_key=f"EXIT::{(cand or {}).get('instrument_id') or 'sc_breach'}",
                severity="severe" if _bands_over >= 2 else "mismatch",
                execution_path="redirect",
                requires_confirmation=ctx.behavioural_confidence < 0.7,
            ))
            if cand and h:
                signals[-1].__dict__["_holding"] = h
                signals[-1].__dict__["_candidate"] = cand

        if sectoral_pct > sectoral_cap + 0.5:
            cand = _find_largest_holding_in_category(ctx, "sectoral")
            excess = round(sectoral_pct - sectoral_cap, 1)
            from services.recommendation_engine.helpers import fuzzy_match_holding
            fund_name = (cand or {}).get("instrument_name", "Sectoral Fund")
            h = fuzzy_match_holding(fund_name, ctx.mf_holdings) if cand else None
            amt = (float(h.get("quantity", 0)) * float(h.get("current_price", 0))) if h else 0.0
            _persona_label = (ctx.persona_profile.persona_type.value if ctx.persona_profile else risk)
            signals.append(EngineSignal(
                signal_id=f"risk_alignment::ra1::sectoral::{ctx.risk_profile}",
                engine_name=self.engine_name,
                rule_label="RA-1",
                action_type="EXIT" if cand else "TRIM",
                instrument_id=(cand or {}).get("instrument_id"),
                instrument_name=fund_name,
                amount_rs=amt,
                base_score=6.0,
                confidence=0.75,
                risk_reduction=0.7,
                urgency=0.5,
                implementation_ease=0.5,
                estimated_tax_rs=float(((cand or {}).get("tax_impact") or {}).get("tax_liability") or 0),
                reason_codes=["RA1_SECTORAL_BREACH"],
                reason_text=(
                    f"Sectoral/thematic allocation ({sectoral_pct:.0f}%) exceeds your {_persona_label} profile "
                    f"cap ({sectoral_cap:.0f}%) by {excess:.0f}pp. Concentrated sector bets add volatility."
                ),
                dedup_key=f"EXIT::{(cand or {}).get('instrument_id') or 'sectoral_breach'}",
                severity="mismatch",
                execution_path="redirect",
            ))
            if cand and h:
                signals[-1].__dict__["_holding"] = h
                signals[-1].__dict__["_candidate"] = cand

        # ── RA-2: Portfolio volatility ceiling ────────────────────────────
        weighted_vol = _weighted_portfolio_metric(ctx, "volatility_1y")
        if weighted_vol is not None and weighted_vol > vol_cap + 1.0:
            excess_vol = round(weighted_vol - vol_cap, 1)
            _persona_label = (ctx.persona_profile.persona_type.value if ctx.persona_profile else risk)
            signals.append(EngineSignal(
                signal_id=f"risk_alignment::ra2::volatility::{ctx.risk_profile}",
                engine_name=self.engine_name,
                rule_label="RA-2",
                action_type="TRIM",
                instrument_id=None,
                instrument_name="High-volatility holdings",
                amount_rs=0.0,
                base_score=5.5,
                confidence=0.65,
                risk_reduction=0.7,
                urgency=0.5,
                implementation_ease=0.3,
                reason_codes=["RA2_VOLATILITY_BREACH"],
                reason_text=(
                    f"Portfolio annualised volatility ({weighted_vol:.1f}%) exceeds your {_persona_label} "
                    f"ceiling ({vol_cap:.0f}%) by {excess_vol:.1f}pp — more downside than your plan allows."
                ),
                dedup_key="TRIM::ra2_volatility",
                severity="mismatch",
                execution_path="redirect",
            ))

        # ── RA-3: Portfolio max-drawdown ceiling ──────────────────────────
        weighted_dd = _weighted_portfolio_metric(ctx, "max_drawdown_pct")
        if weighted_dd is not None and weighted_dd > dd_cap + 1.0:
            excess_dd = round(weighted_dd - dd_cap, 1)
            _persona_label = (ctx.persona_profile.persona_type.value if ctx.persona_profile else risk)
            signals.append(EngineSignal(
                signal_id=f"risk_alignment::ra3::drawdown::{ctx.risk_profile}",
                engine_name=self.engine_name,
                rule_label="RA-3",
                action_type="TRIM",
                instrument_id=None,
                instrument_name="High-drawdown holdings",
                amount_rs=0.0,
                base_score=5.0,
                confidence=0.6,
                risk_reduction=0.65,
                urgency=0.4,
                implementation_ease=0.3,
                reason_codes=["RA3_DRAWDOWN_BREACH"],
                reason_text=(
                    f"Portfolio max drawdown ({weighted_dd:.1f}%) exceeds your {_persona_label} "
                    f"ceiling ({dd_cap:.0f}%) by {excess_dd:.1f}pp. Trim highest-drawdown funds to protect capital."
                ),
                dedup_key="TRIM::ra3_drawdown",
                severity="mismatch",
                execution_path="redirect",
            ))

        return signals
