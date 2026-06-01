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
    """Rule 3 (P1): Underperforming funds → EXIT + ADD best-in-category replacement.

    Uses persona-calibrated quality thresholds (PRD §6.2) from ctx.persona_profile
    when available. Falls back to the V2.5 hardcoded defaults otherwise.
    """

    engine_name = "UnderperformerEngine"
    enabled_config_key = "rule_3_underperformer_replacement.enabled"

    def generate(self, ctx: RecommendationContext) -> List[EngineSignal]:
        mf_investments = ctx.portfolio_intelligence.get("mf_investments") or []
        catalog = ctx.portfolio_intelligence.get("catalog") or {}
        r3_params = (ctx.rules_cfg.get("rule_3_underperformer_replacement") or {}).get("params", {})
        max_replacements = int(r3_params.get("max_replacements", 2))

        # ── PRD §6.2 persona-calibrated thresholds ────────────────────────
        # NIDP quality_score is 0-100; legacy engine score is 0-10 (higher=worse).
        # exit_quality_threshold / add_quality_threshold are on the NIDP 0-100 scale.
        if ctx.persona_profile:
            pp = ctx.persona_profile
            # Convert NIDP 0-100 exit threshold to the 0-10 legacy engine scale
            # NIDP quality < exit_quality_threshold → exit; legacy: quality >= 6.5 → exit
            # The mapping: NIDP 100 = best quality; legacy 10 = worst. So:
            #   NIDP exit_threshold → legacy = (100 - exit_threshold) / 10
            nidp_exit_q_threshold = pp.exit_quality_threshold    # 0-100
            nidp_add_q_threshold = pp.add_quality_threshold      # 0-100
            # Legacy: quality score (0–10) where higher = WORSE (inverse)
            legacy_exit_q_gate = (100.0 - nidp_exit_q_threshold) / 10.0  # e.g. 55→4.5
        else:
            nidp_exit_q_threshold = 45.0   # V2.5 defaults
            nidp_add_q_threshold = 65.0
            legacy_exit_q_gate = 6.5       # V2.5 hardcoded

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

            # ── Quality check: prefer NIDP quality_score (0-100), fall back to legacy ──
            v3 = ctx.v3_scores.get(iid or "", {})
            nidp_qs = v3.get("quality_score")
            legacy_q = float((cand.get("score_breakdown") or {}).get("quality") or 5.0)

            if nidp_qs is not None:
                # NIDP quality_score: lower = worse; exit if below persona threshold
                weak_q = float(nidp_qs) < nidp_exit_q_threshold
            else:
                # Legacy scale: higher = worse; exit if above legacy gate
                weak_q = legacy_q >= legacy_exit_q_gate

            # ── Category rank check (mf_category_rank_daily via v_v3_mf_primitives) ──
            # category_rank_pct is 0–100 where 100=best in peer group.
            # exit_rank_threshold (persona): minimum acceptable pct to keep the fund.
            # e.g. exit_rank_threshold=65 → exit if fund is in bottom 35% of category.
            cat_pct = v3.get("category_rank_pct")
            if cat_pct is not None and ctx.persona_profile:
                keep_threshold = ctx.persona_profile.exit_rank_threshold  # e.g. 65
                weak_cat_rank = float(cat_pct) < (100.0 - keep_threshold)
            else:
                weak_cat_rank = False  # no data → don't trigger on rank alone

            fund_data = catalog.get(iid, {})
            ratios = (fund_data.get("ratios") or {}) if isinstance(fund_data, dict) else {}
            ret_1y = ratios.get("ret_1y")
            ret_3y = ratios.get("ret_3y")
            r1 = float(ret_1y) if ret_1y is not None else None
            r3 = float(ret_3y) if ret_3y is not None else None
            weak_1y = r1 is not None and r1 < 8.0
            weak_3y = r3 is not None and r3 < 10.0
            # Trigger on quality + return weakness, OR strengthen with category rank signal
            if (weak_q and weak_1y and (weak_3y or r3 is None)) or (weak_cat_rank and weak_q):
                exit_score = _v3_or_engine_exit_score(iid, cand, ctx.v3_scores)
                underperformers.append({
                    "mf": mf, "candidate": cand,
                    "quality_score": nidp_qs if nidp_qs is not None else legacy_q,
                    "quality_source": "nidp" if nidp_qs is not None else "legacy",
                    "exit_score": exit_score,
                    "ret_1y": round(r1, 2) if r1 is not None else "N/A",
                    "ret_3y": round(r3, 2) if r3 is not None else "N/A",
                    "category_rank_pct": cat_pct,
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

            # Build persona-aware reason text (PRD §6 — reason in goal/persona terms)
            _persona_label = (
                ctx.persona_profile.persona_type.value if ctx.persona_profile else ctx.risk_profile
            )
            _q_display = (
                f"NIDP quality {under['quality_score']:.0f}/100"
                if under.get("quality_source") == "nidp"
                else f"quality score {under['quality_score']:.1f}/10"
            )
            _q_bar = nidp_exit_q_threshold if under.get("quality_source") == "nidp" else legacy_exit_q_gate
            _rank_suffix = ""
            if under.get("category_rank_pct") is not None:
                _rank_suffix = f" Category rank: bottom {100 - under['category_rank_pct']:.0f}% of peers."
            exit_reason = (
                f"Below your {_persona_label} quality bar ({_q_display} vs threshold "
                f"{_q_bar:.0f}). 1Y return {under['ret_1y']}% — underperforming its peer category.{_rank_suffix}"
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
                severity="mismatch",
                execution_path="harvest",
                requires_confirmation=(
                    ctx.behavioural_confidence < 0.7 and amount_rs > (
                        ctx.persona_profile.confirmation_threshold_rs
                        if ctx.persona_profile else 500_000.0
                    )
                ),
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
                _persona_label = (
                    ctx.persona_profile.persona_type.value if ctx.persona_profile else ctx.risk_profile
                )
                add_reason = (
                    f"Replaces underperforming fund. Top-rated in {category} — "
                    f"fits your {_persona_label} profile and adds to a category you already need."
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
