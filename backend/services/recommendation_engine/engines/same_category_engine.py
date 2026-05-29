"""
SameCategoryEngine — Rule 8: Consolidate when ≥N funds exist in the same SEBI category.

Keeps the best-scoring fund; emits EXIT signals for the rest.
Wires exit_score_engine.score_holding() as additional ranking signal.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from services.recommendation_engine.base_engine import BaseEngine
from services.recommendation_engine.context import EngineSignal, RecommendationContext
from services.recommendation_engine.helpers import (
    infer_category_from_name,
    normalize_fund_name,
)

logger = logging.getLogger(__name__)


def _holding_key(h: Dict[str, Any]) -> str:
    return f"{h.get('user_id','')}::{normalize_fund_name(h.get('name',''))}"


def _combined_exit_score(
    iid: Optional[str],
    candidate: Optional[Dict[str, Any]],
    v3_scores: Dict[str, Any],
) -> float:
    """60% V3 exit score + 40% exit_score_engine (when both available)."""
    v3 = v3_scores.get(iid or "", {})
    v3_s: Optional[float] = float(v3["exit_score"]) if v3.get("exit_score") is not None else None

    eng_s: Optional[float] = None
    try:
        from services.exit_score_engine import ExitScoreInput, score_holding
        if candidate:
            inp = ExitScoreInput(
                instrument_id=iid or "",
                scheme_name=candidate.get("instrument_name") or "",
                exit_score_raw=float(candidate.get("exit_score") or 5.0),
                quality_score=float((candidate.get("score_breakdown") or {}).get("quality") or 5.0),
                ret_1y=None, ret_3y=None, sharpe=None, alpha=None,
                ter_pct=None, max_drawdown=None, category=None,
            )
            eng_s = score_holding(inp).score / 10.0
    except Exception:
        pass

    if v3_s is not None and eng_s is not None:
        return 0.6 * v3_s + 0.4 * eng_s
    return v3_s or eng_s or float((candidate or {}).get("exit_score") or 5.0)


class SameCategoryEngine(BaseEngine):
    """Rule 8 (P1): ≥N funds in same SEBI category → keep best, EXIT rest."""

    engine_name = "SameCategoryEngine"
    enabled_config_key = "rule_8_same_category_consolidation.enabled"

    def generate(self, ctx: RecommendationContext) -> List[EngineSignal]:
        r8_params = (ctx.rules_cfg.get("rule_8_same_category_consolidation") or {}).get("params", {})

        # PRD §6.2 — persona calibrates the max holdings target.
        # min_trigger: if holdings in a category > persona target, consolidate.
        # Conservative: ≤12 total → trigger when >3 in any single category.
        # Aggressive: ≤25 total → trigger when >5 in any single category.
        if ctx.persona_profile:
            pp = ctx.persona_profile
            # Scale category trigger: persona max_holdings / 4 (rough per-category budget)
            min_trigger = max(2, pp.target_holdings_max // 4)
        else:
            min_trigger = int(r8_params.get("min_funds_to_trigger", 3))

        candidate_by_name: Dict[str, Dict] = {
            normalize_fund_name(
                c.get("instrument_name") or c.get("mf_investment", {}).get("scheme_name", "")
            ): c
            for c in ctx.exit_candidates
        }

        def _resolve_cand(holding: Dict) -> Optional[Dict]:
            return candidate_by_name.get(normalize_fund_name(holding.get("name", "")))

        # Group non-exited mf_holdings by category
        cat_to_holdings: Dict[str, List[Dict]] = {}
        for m in ctx.mf_holdings:
            h_key = _holding_key(m)
            if h_key in ctx.exited_holding_keys:
                continue
            cat = (m.get("category") or "").strip()
            if not cat:
                cat = infer_category_from_name(m.get("name") or m.get("scheme_name", "")) or ""
            if not cat:
                continue
            cat_to_holdings.setdefault(cat, []).append(m)

        signals: List[EngineSignal] = []
        local_exited_keys: set = set()
        local_exited_ids: set = set()

        for cat, group in cat_to_holdings.items():
            if len(group) < min_trigger:
                continue

            # Score each holding
            scored = []
            for m in group:
                cand = _resolve_cand(m)
                iid = (cand or {}).get("instrument_id")
                score = _combined_exit_score(iid, cand, ctx.v3_scores)
                scored.append((score, m, cand))

            # Highest exit_score = exit first; last one = keeper
            scored.sort(key=lambda x: x[0], reverse=True)
            to_exit = scored[:-1]
            keeper_name = (scored[-1][1].get("name") or scored[-1][1].get("scheme_name") or "")[:40]

            logger.debug(
                "[SameCategoryEngine] %s funds in '%s' — keeping %s, exiting %s",
                len(group), cat, keeper_name, len(to_exit),
            )

            for exit_score, holding, cand in to_exit:
                h_key = _holding_key(holding)
                if h_key in ctx.exited_holding_keys or h_key in local_exited_keys:
                    continue

                iid = (cand or {}).get("instrument_id")
                if iid in ctx.exited_ids or iid in local_exited_ids:
                    continue

                fund_name = holding.get("name") or holding.get("scheme_name") or ""
                amount_rs = float(holding.get("quantity", 0)) * float(holding.get("current_price", 0))

                persona_label = (
                    ctx.persona_profile.persona_type.value if ctx.persona_profile else ctx.risk_profile
                )
                target_max = (
                    ctx.persona_profile.target_holdings_max if ctx.persona_profile else 20
                )
                reason_text = (
                    f"You hold {len(group)} {cat} funds — they all track similar stocks. "
                    f"Your {persona_label} profile targets ≤{target_max} total holdings. "
                    f"Keeping {keeper_name} (top-ranked) and exiting the rest reduces overlap."
                )

                sig = EngineSignal(
                    signal_id=f"same_category::{cat}::{iid or fund_name[:20]}",
                    engine_name=self.engine_name,
                    rule_label="Rule 8",
                    action_type="EXIT",
                    instrument_id=iid,
                    instrument_name=fund_name,
                    amount_rs=amount_rs,
                    base_score=exit_score,
                    confidence=0.8,
                    risk_reduction=0.4,
                    diversification_gain=0.5,
                    urgency=0.4,
                    implementation_ease=0.6,
                    reason_codes=["SAME_CATEGORY_CONSOLIDATION"],
                    reason_text=reason_text,
                    dedup_key=f"EXIT::{iid or fund_name[:30]}",
                    severity="mismatch",
                    execution_path="harvest",
                    requires_confirmation=(
                        ctx.behavioural_confidence < 0.7 and amount_rs > (
                            ctx.persona_profile.confirmation_threshold_rs
                            if ctx.persona_profile else 500_000.0
                        )
                    ),
                )
                sig.__dict__["_holding"] = holding
                sig.__dict__["_candidate"] = cand

                signals.append(sig)
                local_exited_keys.add(h_key)
                if iid:
                    local_exited_ids.add(iid)

        return signals
