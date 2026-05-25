"""
UnderperformerEngine — Rule 3: EXIT underperforming funds and ADD best-in-category.

Wires exit_score_engine.score_holding() as an additional ranking signal.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from services.recommendation_engine.base_engine import BaseEngine
from services.recommendation_engine.context import EngineSignal, RecommendationContext
from services.recommendation_engine.helpers import (
    extract_amc_from_name,
    fuzzy_match_holding,
    normalize_fund_name,
)

logger = logging.getLogger(__name__)

# Hard-coded top-fund suggestions per category (fallback when PG unavailable)
_TOP_FUND_MAP = {
    "large cap": {"scheme_name": "Nippon India Large Cap Fund - Direct Growth", "category": "Large Cap", "expense_ratio": 0.71, "aum_cr": 28000, "ret_3y": 18.5},
    "small cap": {"scheme_name": "Nippon India Small Cap Fund - Direct Growth", "category": "Small Cap", "expense_ratio": 0.68, "aum_cr": 45000, "ret_3y": 28.2},
    "mid cap": {"scheme_name": "Motilal Oswal Midcap Fund - Direct Growth", "category": "Mid Cap", "expense_ratio": 0.65, "aum_cr": 9500, "ret_3y": 32.1},
    "flexi cap": {"scheme_name": "Parag Parikh Flexi Cap Fund - Direct Growth", "category": "Flexi Cap", "expense_ratio": 0.63, "aum_cr": 62000, "ret_3y": 20.4},
    "elss": {"scheme_name": "Mirae Asset ELSS Tax Saver Fund - Direct Growth", "category": "ELSS", "expense_ratio": 0.50, "aum_cr": 18000, "ret_3y": 19.1},
    "index": {"scheme_name": "Nifty 50 Index Fund - Direct Growth", "category": "Index", "expense_ratio": 0.10, "aum_cr": 15000, "ret_3y": 15.2},
}


def _holding_key(h: Dict[str, Any]) -> str:
    return f"{h.get('user_id','')}::{normalize_fund_name(h.get('name',''))}"


def _v3_or_engine_exit_score(
    iid: Optional[str],
    candidate: Optional[Dict],
    v3_scores: Dict,
) -> float:
    """Combined exit score: 60% V3 + 40% exit_engine (0-100 → 0-10) when both available."""
    v3_s = None
    eng_s = None

    v3 = v3_scores.get(iid or "", {})
    if v3.get("exit_score") is not None:
        v3_s = float(v3["exit_score"])

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
            res = score_holding(inp)
            eng_s = res.score / 10.0  # scale 0-100 → 0-10
    except Exception:
        pass

    if v3_s is not None and eng_s is not None:
        return 0.6 * v3_s + 0.4 * eng_s
    return v3_s or eng_s or float((candidate or {}).get("exit_score") or 5.0)


class UnderperformerEngine(BaseEngine):
    """Rule 3 (P1): Underperforming funds → EXIT + ADD best-in-category replacement."""

    engine_name = "UnderperformerEngine"
    enabled_config_key = "rule_3_underperformer_replacement.enabled"

    def generate(self, ctx: RecommendationContext) -> List[EngineSignal]:
        mf_investments = ctx.portfolio_intelligence.get("mf_investments") or []
        catalog = ctx.portfolio_intelligence.get("catalog") or {}
        r3_params = (ctx.rules_cfg.get("rule_3_underperformer_replacement") or {}).get("params", {})
        max_replacements = int(r3_params.get("max_replacements", 2))

        candidate_by_id = {c.get("instrument_id"): c for c in ctx.exit_candidates if c.get("instrument_id")}

        underperformers: List[Dict] = []
        for mf in mf_investments:
            if not mf.get("resolved"):
                continue
            iid = mf.get("instrument_id")
            if iid in ctx.exited_ids:
                continue
            cand = candidate_by_id.get(iid)
            if not cand:
                continue
            quality = float((cand.get("score_breakdown") or {}).get("quality") or 5.0)
            fund_data = catalog.get(iid, {})
            ratios = (fund_data.get("ratios") or {}) if isinstance(fund_data, dict) else {}
            ret_1y = ratios.get("ret_1y")
            ret_3y = ratios.get("ret_3y")
            r1 = float(ret_1y) if ret_1y is not None else None
            r3 = float(ret_3y) if ret_3y is not None else None
            # V2.5 quality gate: quality >= 6.5 (higher = worse) + underperformance
            weak_q = quality >= 6.5
            weak_1y = r1 is not None and r1 < 8.0
            weak_3y = r3 is not None and r3 < 10.0
            if weak_q and weak_1y and (weak_3y or r3 is None):
                exit_score = _v3_or_engine_exit_score(iid, cand, ctx.v3_scores)
                underperformers.append({
                    "mf": mf, "candidate": cand,
                    "quality_score": quality,
                    "exit_score": exit_score,
                    "ret_1y": round(r1, 2) if r1 is not None else "N/A",
                    "ret_3y": round(r3, 2) if r3 is not None else "N/A",
                })

        underperformers.sort(key=lambda x: x["exit_score"], reverse=True)

        signals: List[EngineSignal] = []
        local_exited_ids: set = set()
        local_exited_keys: set = set()
        count = 0

        for under in underperformers:
            if count >= max_replacements:
                break
            mf = under["mf"]
            iid = mf.get("instrument_id")
            if iid in local_exited_ids:
                continue
            h = fuzzy_match_holding(mf.get("scheme_name", ""), ctx.mf_holdings)
            if not h:
                continue
            h_key = _holding_key(h)
            if h_key in ctx.exited_holding_keys or h_key in local_exited_keys:
                continue

            fund_name = h.get("name") or mf.get("scheme_name") or ""
            amount_rs = float(h.get("quantity", 0)) * float(h.get("current_price", 0))

            exit_reason = (
                f"Underperforming benchmark: 1Y return {under['ret_1y']}%, "
                f"quality score {under['quality_score']:.1f}/10. "
            )

            exit_sig = EngineSignal(
                signal_id=f"underperformer::exit::{iid or fund_name[:20]}",
                engine_name=self.engine_name,
                rule_label="Rule 3",
                action_type="EXIT",
                instrument_id=iid,
                instrument_name=fund_name,
                amount_rs=amount_rs,
                base_score=under["exit_score"],
                confidence=0.7,
                risk_reduction=0.4,
                diversification_gain=0.3,
                urgency=0.5,
                implementation_ease=0.6,
                reason_codes=["UNDERPERFORMER_REPLACEMENT"],
                reason_text=exit_reason,
                dedup_key=f"EXIT::{iid or fund_name[:30]}",
            )
            exit_sig.__dict__["_holding"] = h
            exit_sig.__dict__["_candidate"] = under["candidate"]
            signals.append(exit_sig)

            local_exited_keys.add(h_key)
            if iid:
                local_exited_ids.add(iid)
            count += 1

            # Suggest replacement in same category
            category = mf.get("category") or ""
            replacement = _TOP_FUND_MAP.get((category or "").lower())
            if replacement:
                add_reason = (
                    f"Replaces underperforming fund. Top-rated in same category ({category})."
                )
                amc_key = extract_amc_from_name(replacement["scheme_name"]) or ""
                add_fund = {
                    "fund_name": replacement["scheme_name"],
                    "fund_type": replacement.get("category", "Equity"),
                    "amc": amc_key,
                    "expense_ratio": replacement.get("expense_ratio"),
                    "aum": f"₹{replacement.get('aum_cr', 0):,.0f} Cr",
                    "rating": "Top-rated in category",
                    "returns_3y": f"{replacement.get('ret_3y','N/A')}%",
                }
                add_sig = EngineSignal(
                    signal_id=f"underperformer::add::{replacement['scheme_name'][:20]}",
                    engine_name=self.engine_name,
                    rule_label="Rule 3",
                    action_type="ADD",
                    instrument_id=None,
                    instrument_name=replacement["scheme_name"],
                    amount_rs=amount_rs,
                    base_score=6.0,
                    confidence=0.7,
                    diversification_gain=0.4,
                    urgency=0.5,
                    implementation_ease=0.7,
                    reason_codes=["ALLOCATION_GAP", "DIVERSIFICATION"],
                    reason_text=add_reason,
                    dedup_key=f"ADD::{category}",
                )
                add_sig.__dict__["_fund_details"] = add_fund
                signals.append(add_sig)

        return signals
