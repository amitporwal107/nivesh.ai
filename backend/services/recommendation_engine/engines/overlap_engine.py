"""
OverlapEngine — Rules 4 + 9: EXIT when two funds have high stock overlap.

Rule 4: Exit the fund with the higher exit score when overlap > threshold.
Rule 9: Suggest a replacement from a complementary category (cross-category variant).

Wires consolidation_score_engine.score_pair() for confidence scoring.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from services.recommendation_engine.base_engine import BaseEngine
from services.recommendation_engine.context import EngineSignal, RecommendationContext
from services.recommendation_engine.helpers import (
    fuzzy_match_holding,
    infer_category_from_name,
    normalize_base_scheme_name,
    normalize_fund_name,
)

logger = logging.getLogger(__name__)

# Complementary category map: when exiting a fund in key category,
# suggest adding one from the value category.
_COMPLEMENT_CATEGORIES = {
    "Large Cap": "Small Cap",
    "Large & Mid Cap": "Small Cap",
    "Multi Cap": "Flexi Cap",
    "Flexi Cap": "International",
    "Mid Cap": "Debt",
    "Small Cap": "Debt",
    "Hybrid": "Debt",
}


def _holding_key(h: Dict[str, Any]) -> str:
    return f"{h.get('user_id','')}::{normalize_fund_name(h.get('name',''))}"


class OverlapEngine(BaseEngine):
    """Rules 4 + 9 (P1): High overlap → exit weaker fund; optionally suggest complement."""

    engine_name = "OverlapEngine"
    enabled_config_key = "rule_4_different_fund_overlap.enabled"

    def generate(self, ctx: RecommendationContext) -> List[EngineSignal]:
        pairs = ctx.portfolio_intelligence.get("pairwise_overlap") or []
        if not pairs:
            return []

        r4_params = (ctx.rules_cfg.get("rule_4_different_fund_overlap") or {}).get("params", {})
        overlap_threshold = float(r4_params.get("overlap_threshold_pct", 60.0))
        max_exits = int(r4_params.get("max_overlap_exits", 2))

        r9_enabled = (ctx.rules_cfg.get("rule_9_cross_category_overlap_replacement") or {}).get("enabled", True)
        r9_params = (ctx.rules_cfg.get("rule_9_cross_category_overlap_replacement") or {}).get("params", {})
        r9_max = int(r9_params.get("max_replacements", 2))

        signals: List[EngineSignal] = []
        local_exited_ids: set = set()
        local_exited_keys: set = set()
        overlap_exit_count = 0
        r9_count = 0

        candidate_by_id: Dict[str, Dict] = {
            c.get("instrument_id"): c for c in ctx.exit_candidates if c.get("instrument_id")
        }

        def _exit_rank(iid: Optional[str], scheme_name: Optional[str] = None) -> float:
            v3 = ctx.v3_scores.get(iid or "", {})
            if v3.get("exit_score") is not None:
                return float(v3["exit_score"])
            cand = candidate_by_id.get(iid or "")
            return float((cand or {}).get("exit_score", 5.0))

        for pair in pairs:
            if pair.get("overlap_pct", 0) < overlap_threshold:
                continue
            if overlap_exit_count >= max_exits:
                break

            id_a, id_b = pair.get("a"), pair.get("b")
            name_a = pair.get("a_name", "")
            name_b = pair.get("b_name", "")

            # Skip regular/direct twins (handled by RegularDirectEngine)
            if normalize_base_scheme_name(name_a) == normalize_base_scheme_name(name_b):
                continue

            # Skip if either already marked for exit
            if (id_a in ctx.exited_ids or id_a in local_exited_ids or
                    id_b in ctx.exited_ids or id_b in local_exited_ids):
                continue

            score_a = _exit_rank(id_a, name_a)
            score_b = _exit_rank(id_b, name_b)

            if score_a >= score_b:
                victim_iid, victim_name, victim_cand, partner_name = id_a, name_a, candidate_by_id.get(id_a), name_b
            else:
                victim_iid, victim_name, victim_cand, partner_name = id_b, name_b, candidate_by_id.get(id_b), name_a

            # Proxy switch score gate (Rule 4 V2.5 guard)
            if victim_cand:
                vti = victim_cand.get("tax_impact") or {}
                tmp_h = fuzzy_match_holding(victim_name, ctx.mf_holdings)
                exit_amt = (vti.get("exit_amount_rs") or 0) or (
                    (tmp_h.get("quantity", 0) * tmp_h.get("current_price", 0)) if tmp_h else 0
                )
                tax_pct = ((vti.get("tax_liability") or 0) / exit_amt * 10) if exit_amt else 0
                proxy_score = (victim_cand.get("exit_score", 5.0) - 5.0) - tax_pct
                if proxy_score <= 0:
                    logger.debug(
                        "[OverlapEngine] SKIP — proxy_score=%.2f for %s", proxy_score, victim_name[:40]
                    )
                    continue

            # Try to get consolidation_score_engine confidence
            confidence = 0.7
            try:
                from services.consolidation_score_engine import (
                    ConsolidationInput, FundSnapshot, score_pair
                )
                def _snap(iid: Optional[str]) -> Optional[FundSnapshot]:
                    cat = ctx.portfolio_intelligence.get("catalog", {}).get(iid or "", {})
                    r = cat.get("ratios", {}) if cat else {}
                    h = fuzzy_match_holding(
                        (ctx.portfolio_intelligence.get("mf_investments") or [{}])[0].get("scheme_name",""),
                        ctx.mf_holdings
                    ) or {}
                    return FundSnapshot(
                        scheme_code=iid or "",
                        name=(cat.get("scheme_name") or iid or ""),
                        current_value_rs=float(h.get("quantity",0)) * float(h.get("current_price",0)),
                        return_1y=r.get("ret_1y"),
                        return_3y=r.get("ret_3y"),
                        ter_pct=r.get("expense_ratio"),
                    )
                snap_a = _snap(id_a)
                snap_b = _snap(id_b)
                if snap_a and snap_b:
                    result = score_pair(ConsolidationInput(
                        fund_a=snap_a, fund_b=snap_b,
                        overlap_pct=float(pair.get("overlap_pct", overlap_threshold)),
                    ))
                    rec = result.recommendation
                    if rec in ("Consolidate Immediately", "Switch to One"):
                        confidence = 0.9
                    elif rec == "Consider Consolidation":
                        confidence = 0.6
                    elif rec == "Review":
                        confidence = 0.4
                    elif rec == "Keep Both":
                        continue
            except Exception:
                pass  # consolidation engine unavailable — use default confidence

            h = fuzzy_match_holding(victim_name, ctx.mf_holdings)
            if not h:
                continue
            h_key = _holding_key(h)
            if h_key in ctx.exited_holding_keys or h_key in local_exited_keys:
                continue

            amount_rs = float(h.get("quantity", 0)) * float(h.get("current_price", 0))
            overlap_pct = pair.get("overlap_pct", overlap_threshold)

            reason_text = (
                f"High overlap ({overlap_pct:.1f}%, {pair.get('shared_count',0)} shared stocks) "
                f"with {partner_name}. Consolidating by exiting the weaker fund "
                f"(exit score {max(score_a, score_b):.1f})."
            )

            sig = EngineSignal(
                signal_id=f"overlap::{victim_iid or victim_name[:20]}",
                engine_name=self.engine_name,
                rule_label="Rule 4",
                action_type="EXIT",
                instrument_id=victim_iid,
                instrument_name=victim_name,
                amount_rs=amount_rs,
                base_score=max(score_a, score_b),
                confidence=confidence,
                risk_reduction=0.5,
                diversification_gain=0.6,
                urgency=0.4,
                implementation_ease=0.5,
                reason_codes=["OVERLAP_CONSOLIDATION"],
                reason_text=reason_text,
                dedup_key=f"EXIT::{victim_iid or victim_name[:30]}",
            )
            sig.__dict__["_holding"] = h
            sig.__dict__["_candidate"] = victim_cand
            signals.append(sig)

            local_exited_keys.add(h_key)
            if victim_iid:
                local_exited_ids.add(victim_iid)
            overlap_exit_count += 1

            # Rule 9: suggest complement category replacement
            if r9_enabled and r9_count < r9_max:
                mf_investments = ctx.portfolio_intelligence.get("mf_investments") or []
                victim_mf = next((m for m in mf_investments if m.get("instrument_id") == victim_iid), {})
                victim_cat = victim_mf.get("category") or infer_category_from_name(victim_name) or ""
                complement_cat = _COMPLEMENT_CATEGORIES.get(victim_cat)
                if complement_cat:
                    r9_reason = (
                        f"After removing {victim_name[:40]} (high overlap with {partner_name[:40]}), "
                        f"consider adding a {complement_cat} fund to maintain diversification."
                    )
                    add_sig = EngineSignal(
                        signal_id=f"overlap_r9::add::{complement_cat}",
                        engine_name=self.engine_name,
                        rule_label="Rule 9",
                        action_type="ADD",
                        instrument_id=None,
                        instrument_name=f"{complement_cat} Fund",
                        amount_rs=amount_rs,
                        base_score=5.0,
                        confidence=0.5,
                        diversification_gain=0.7,
                        reason_codes=["CROSS_CATEGORY_REPLACEMENT"],
                        reason_text=r9_reason,
                        dedup_key=f"ADD::{complement_cat}",
                    )
                    add_sig.__dict__["_complement_category"] = complement_cat
                    signals.append(add_sig)
                    r9_count += 1

        return signals
