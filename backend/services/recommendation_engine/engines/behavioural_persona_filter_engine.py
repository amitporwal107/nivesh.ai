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
