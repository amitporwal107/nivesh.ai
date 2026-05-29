"""
BehaviouralPersonaFilterEngine — PRD §7 Behavioural-persona modifiers.

Runs last in the pipeline (after all engines have emitted) and suppresses
signals that conflict with the detected behavioural persona. Does NOT change
targets — only changes instruments and tone.

BP-1 Mutual Fund Investor:
  - Suppress ADD signals targeting direct equities/stocks (unless user opts in).
  - Consolidation signals lead; fund-level language only.

BP-2 Active Trader:
  - Surface STCG tax cost prominently on any EXIT that would realise short-term gains.
  - Warn on churn (multiple EXITs in same session).

BP-3 New / First-time Investor:
  - Cap the number of recommendations at 2 (fewer, simpler).
  - Prefer REDIRECT over EXIT; avoid restructuring in one step.

Note: This engine does not emit new signals. It annotates and suppresses existing
ones — it reads ctx.exited_ids state which is populated by the orchestrator.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from services.recommendation_engine.base_engine import BaseEngine
from services.recommendation_engine.context import EngineSignal, RecommendationContext
from services.recommendation_engine.persona_config import BehaviouralPersonaType, map_behavioural_persona

logger = logging.getLogger(__name__)


class BehaviouralPersonaFilterEngine(BaseEngine):
    """
    BP-1..BP-3: Suppress or annotate signals that conflict with the behavioural persona.

    Suppressed signals still flow through to the orchestrator's active_signals filter
    (suppressed=True means they are excluded from the final action list but logged).
    """

    engine_name = "BehaviouralPersonaFilterEngine"
    enabled_config_key = "behavioural_persona_filter.enabled"

    def generate(self, ctx: RecommendationContext) -> List[EngineSignal]:
        """
        This engine returns NO new signals. Instead it returns a list of
        suppression signals for signals already queued via ctx state.

        Implementation note: since engines don't share mutable state, the
        filter works by querying ctx and emitting suppression markers that the
        ArbitrationEngine will pick up via dedup_key matching. Full suppression
        of prior signals is handled in the orchestrator post-arbitration loop.
        """
        cfg = ctx.rules_cfg.get("behavioural_persona_filter") or {}
        if not cfg.get("enabled", True):
            return []

        bp = map_behavioural_persona(ctx.behavioural_persona)
        confidence = ctx.behavioural_confidence

        # Low-confidence persona → don't filter aggressively
        if confidence < 0.5:
            return []

        signals: List[EngineSignal] = []

        if bp == BehaviouralPersonaType.MUTUAL_FUND_INVESTOR:
            signals.extend(self._mf_investor_filter(ctx))

        elif bp == BehaviouralPersonaType.NEW_FIRST_TIME:
            signals.extend(self._new_investor_filter(ctx))

        elif bp == BehaviouralPersonaType.ACTIVE_TRADER:
            signals.extend(self._active_trader_annotations(ctx))

        elif bp == BehaviouralPersonaType.DIRECT_EQUITY_INVESTOR:
            signals.extend(self._direct_equity_investor_filter(ctx))

        elif bp == BehaviouralPersonaType.INCOME_DIVIDEND_SEEKER:
            signals.extend(self._income_dividend_filter(ctx))

        return signals

    # ── BP-1: Mutual Fund Investor ────────────────────────────────────────────

    def _mf_investor_filter(self, ctx: RecommendationContext) -> List[EngineSignal]:
        """
        For MF investors: emit a suppression signal for any ADD targeting a
        direct equity/stock (asset_type="equity" or instrument_type="stock").
        Consolidation should be front and centre — emit a clarification signal.
        """
        suppress_signals: List[EngineSignal] = []

        # If user has direct stock holdings, flag for confirmation before any equity ADD
        if ctx.stock_holdings:
            suppress_signals.append(EngineSignal(
                signal_id="bp1::mf_investor::stock_add_warning",
                engine_name=self.engine_name,
                rule_label="BP-1",
                action_type="HOLD",
                instrument_id=None,
                instrument_name="Direct equity (informational)",
                amount_rs=0.0,
                base_score=0.1,
                confidence=0.9,
                reason_codes=["BP1_MF_INVESTOR_STOCK_ADD_SUPPRESSED"],
                reason_text=(
                    "Your portfolio is primarily mutual funds. Stock-level recommendations "
                    "are available but require explicit opt-in. Focusing on fund consolidation first."
                ),
                dedup_key="HOLD::bp1_stock_add_suppressed",
                severity="aligned",
                execution_path="redirect",
                requires_confirmation=True,
                suppressed=True,
                suppression_reason="Behavioural persona: MF investor — stock ADD suppressed",
            ))

        return suppress_signals

    # ── BP-3: New / First-time Investor ──────────────────────────────────────

    def _new_investor_filter(self, ctx: RecommendationContext) -> List[EngineSignal]:
        """
        For new investors: emit a single advisory HOLD signal that will be
        inserted at priority 1, pushing complex restructuring signals down.
        The orchestrator caps at max_actions_per_plan anyway; with this at
        priority 1, complex EXITs get crowded out.
        """
        return [EngineSignal(
            signal_id="bp3::new_investor::simplify_advisory",
            engine_name=self.engine_name,
            rule_label="BP-3",
            action_type="HOLD",
            instrument_id=None,
            instrument_name="Portfolio (new investor guidance)",
            amount_rs=0.0,
            base_score=0.5,
            confidence=0.85,
            risk_reduction=0.0,
            diversification_gain=0.0,
            goal_impact=0.0,
            urgency=0.2,
            implementation_ease=1.0,
            reason_codes=["BP3_NEW_INVESTOR_SIMPLIFIED"],
            reason_text=(
                "As a new investor, we recommend starting with 1-2 focused actions "
                "rather than a full restructure. Review each suggestion carefully before acting."
            ),
            dedup_key="HOLD::bp3_new_investor_advisory",
            severity="aligned",
            execution_path="redirect",
            requires_confirmation=True,
        )]

    # ── BP-4: Direct Equity Investor (PRD §7) ────────────────────────────────

    def _direct_equity_investor_filter(self, ctx: RecommendationContext) -> List[EngineSignal]:
        """
        For direct equity investors:
        - Flag single-stock concentration hard (>persona max_single_holding_pct).
        - Emit position-sizing advisory when any stock > 2× persona cap.
        - Sector diversification lead: flag when top sector > persona max_single_sector_pct.
        """
        signals: List[EngineSignal] = []
        if not ctx.stock_holdings or not ctx.persona_profile:
            return signals

        pp = ctx.persona_profile
        total = ctx.total_value_rs or 1.0

        # Single-stock concentration check
        for h in ctx.stock_holdings:
            value = float(h.get("quantity", 0)) * float(h.get("current_price", 0))
            if value <= 0:
                continue
            weight_pct = value / total * 100.0
            if weight_pct < pp.max_single_holding_pct:
                continue

            name = h.get("name") or h.get("ticker") or ""
            excess = weight_pct - pp.max_single_holding_pct
            severity = "severe" if weight_pct >= pp.max_single_holding_pct * 2 else "mismatch"
            signals.append(EngineSignal(
                signal_id=f"bp4::direct_equity::concentration::{h.get('instrument_id', name[:15])}",
                engine_name=self.engine_name,
                rule_label="BP-4",
                action_type="TRIM",
                instrument_id=h.get("instrument_id"),
                instrument_name=name,
                amount_rs=round(total * (excess / 100.0), 2),
                base_score=7.5,
                confidence=0.9,
                risk_reduction=0.5,
                diversification_gain=0.3,
                urgency=0.7 if severity == "severe" else 0.5,
                implementation_ease=0.7,
                reason_codes=["BP4_SINGLE_STOCK_CONCENTRATION"],
                reason_text=(
                    f"{name} is {weight_pct:.1f}% of your portfolio — "
                    f"single-stock blowup risk. Your {pp.persona_type.value} cap is "
                    f"{pp.max_single_holding_pct:.0f}%. Trim ₹{total*(excess/100):,.0f} "
                    f"and diversify across sectors."
                ),
                dedup_key=f"TRIM::bp4_stock_conc::{h.get('instrument_id', name[:20])}",
                severity=severity,
                execution_path="harvest",
                requires_confirmation=True,
            ))

        # Sector diversification check via portfolio intelligence
        sector_exposure = ctx.portfolio_intelligence.get("sector_exposure") or []
        for sector in sector_exposure[:3]:  # check top 3 sectors
            pct = float(sector.get("pct") or sector.get("weight_pct") or 0)
            if pct <= pp.max_single_sector_pct:
                continue
            sector_name = sector.get("sector") or sector.get("name") or "sector"
            signals.append(EngineSignal(
                signal_id=f"bp4::direct_equity::sector::{sector_name[:20]}",
                engine_name=self.engine_name,
                rule_label="BP-4",
                action_type="DIVERSIFY",
                instrument_id=None,
                instrument_name=f"{sector_name} (sector diversification)",
                amount_rs=0.0,
                base_score=6.0,
                confidence=0.8,
                risk_reduction=0.4,
                diversification_gain=0.6,
                urgency=0.4,
                implementation_ease=0.6,
                reason_codes=["BP4_SECTOR_CONCENTRATION"],
                reason_text=(
                    f"{sector_name} is {pct:.1f}% of your equity — above your "
                    f"{pp.max_single_sector_pct:.0f}% sector cap. Reduce exposure "
                    f"by trimming the lowest-ranked stock in this sector."
                ),
                dedup_key=f"DIVERSIFY::bp4_sector::{sector_name[:20]}",
                severity="mismatch",
                execution_path="harvest",
            ))

        return signals

    # ── BP-5: Income / Dividend Seeker (PRD §7) ──────────────────────────────

    def _income_dividend_filter(self, ctx: RecommendationContext) -> List[EngineSignal]:
        """
        For income/dividend seekers:
        - Suppress growth-oriented ADD signals (small-cap, thematic ADD).
        - Emit advisory to redirect new money to dividend/debt instruments.
        - Frame all signals in yield and stability terms.
        """
        signals: List[EngineSignal] = []

        # Advisory: redirect new money to dividend/debt
        alloc = ctx.portfolio_intelligence.get("asset_allocation") or {}
        debt_pct = float(alloc.get("debt_pct") or 0)
        if debt_pct < 30.0:  # income seekers should have substantial debt
            gap_rs = ctx.total_value_rs * ((30.0 - debt_pct) / 100.0)
            signals.append(EngineSignal(
                signal_id="bp5::income_seeker::debt_underweight",
                engine_name=self.engine_name,
                rule_label="BP-5",
                action_type="ADD",
                instrument_id=None,
                instrument_name="ICICI Prudential Corporate Bond Fund - Direct Growth",
                amount_rs=round(gap_rs, 2),
                base_score=6.5,
                confidence=0.8,
                risk_reduction=0.3,
                diversification_gain=0.2,
                goal_impact=0.4,
                urgency=0.5,
                implementation_ease=0.8,
                reason_codes=["BP5_INCOME_SEEKER_DEBT_ADD"],
                reason_text=(
                    f"Your debt allocation is {debt_pct:.0f}% — low for an income-focused portfolio. "
                    f"Directing ₹{gap_rs:,.0f} to a high-quality corporate bond fund improves "
                    f"your yield stability without equity-market exposure."
                ),
                dedup_key="ADD::bp5_income_debt",
                severity="minor",
                execution_path="redirect",
            ))

        return signals

    # ── BP-2: Active Trader ───────────────────────────────────────────────────

    def _active_trader_annotations(self, ctx: RecommendationContext) -> List[EngineSignal]:
        """
        For active traders: emit an advisory signal that surfaces STCG tax costs
        prominently if multiple EXITs are recommended in this plan cycle.
        """
        # Count how many EXIT signals are already queued (tracked via exited_ids)
        exit_count = len(ctx.exited_ids)
        if exit_count < 2:
            return []

        return [EngineSignal(
            signal_id="bp2::active_trader::stcg_warning",
            engine_name=self.engine_name,
            rule_label="BP-2",
            action_type="HOLD",
            instrument_id=None,
            instrument_name="Tax advisory",
            amount_rs=0.0,
            base_score=0.3,
            confidence=0.9,
            reason_codes=["BP2_STCG_CHURN_WARNING"],
            reason_text=(
                f"{exit_count} exits recommended. Check each for short-term capital gains (STCG) — "
                f"holdings under 12 months attract higher tax. Consider holding past the 1-year "
                f"mark where the tax saving outweighs the risk."
            ),
            dedup_key="HOLD::bp2_stcg_warning",
            severity="minor",
            execution_path="stagger",
            requires_confirmation=False,
        )]
