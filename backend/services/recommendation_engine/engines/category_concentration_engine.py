"""
CategoryConcentrationEngine — Rule 2b: EXIT when one SEBI category > threshold %.

Fires when a single fund category (e.g. Mid Cap) represents more than the
configured % of the total MF corpus. Exits highest-exit-score funds in the
over-concentrated category until the category drops below threshold.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Dict, List, Optional

from services.recommendation_engine.base_engine import BaseEngine
from services.recommendation_engine.context import EngineSignal, RecommendationContext
from services.recommendation_engine.helpers import (
    fuzzy_match_holding,
    infer_category_from_name,
    normalize_fund_name,
)

logger = logging.getLogger(__name__)


def _holding_key(h: Dict[str, Any]) -> str:
    return f"{h.get('user_id','')}::{normalize_fund_name(h.get('name',''))}"


class CategoryConcentrationEngine(BaseEngine):
    """Rule 2b (P0): Category concentration above threshold → EXIT excess."""

    engine_name = "CategoryConcentrationEngine"
    enabled_config_key = "rule_2b_category_concentration.enabled"

    def generate(self, ctx: RecommendationContext) -> List[EngineSignal]:
        mf_investments = ctx.portfolio_intelligence.get("mf_investments") or []
        total_mf_value = sum(float(m.get("amount_rs") or 0) for m in mf_investments)
        if total_mf_value <= 0 or not mf_investments:
            return []

        r2b_params = (ctx.rules_cfg.get("rule_2b_category_concentration") or {}).get("params", {})
        threshold = float(r2b_params.get("threshold_pct", 35.0))

        # Build category totals (prefer stored category; infer from name when absent)
        cat_totals: Dict[str, float] = defaultdict(float)
        cat_funds: Dict[str, List[Dict]] = defaultdict(list)
        for m in mf_investments:
            cn = (m.get("category") or "").strip()
            if not cn or cn == "Uncategorised":
                cn = infer_category_from_name(m.get("scheme_name", "")) or "Uncategorised"
            cat_totals[cn] += float(m.get("amount_rs") or 0)
            cat_funds[cn].append(m)

        over_cats = [
            (cn, val / total_mf_value * 100)
            for cn, val in cat_totals.items()
            if val / total_mf_value * 100 >= threshold and cn != "Uncategorised"
        ]
        over_cats.sort(key=lambda x: -x[1])
        logger.debug("[CategoryConcentrationEngine] over-concentrated categories: %s", over_cats)

        signals: List[EngineSignal] = []
        local_exited_ids: set = set()
        local_exited_keys: set = set()

        candidate_by_id: Dict[str, Dict] = {
            c.get("instrument_id"): c for c in ctx.exit_candidates if c.get("instrument_id")
        }

        def _exit_rank(iid: Optional[str]) -> float:
            v3 = ctx.v3_scores.get(iid or "", {})
            if v3.get("exit_score") is not None:
                return float(v3["exit_score"])
            cand = candidate_by_id.get(iid or "")
            return float((cand or {}).get("exit_score", 5.0))

        for cat_name, cat_pct in over_cats:
            ranked = sorted(
                [
                    {
                        "mf": m,
                        "candidate": candidate_by_id.get(m.get("instrument_id")),
                        "exit_score": _exit_rank(m.get("instrument_id")),
                    }
                    for m in cat_funds[cat_name]
                    if m.get("instrument_id") not in ctx.exited_ids
                    and m.get("instrument_id") not in local_exited_ids
                ],
                key=lambda x: x["exit_score"],
                reverse=True,
            )

            current_pct = cat_pct
            for item in ranked:
                if current_pct < threshold:
                    break
                mf = item["mf"]
                h = fuzzy_match_holding(mf.get("scheme_name", ""), ctx.mf_holdings)
                if not h:
                    continue
                h_key = _holding_key(h)
                if h_key in ctx.exited_holding_keys or h_key in local_exited_keys:
                    current_pct -= mf.get("amount_rs", 0) / total_mf_value * 100
                    continue

                iid = mf.get("instrument_id")
                fund_name = h.get("name") or mf.get("scheme_name") or ""
                amount_rs = float(h.get("quantity", 0)) * float(h.get("current_price", 0))

                reason_text = (
                    f"{cat_name} is {current_pct:.1f}% of your MF corpus — above the "
                    f"{threshold:.0f}% guardrail. Exiting this fund "
                    f"(exit score {item['exit_score']:.1f}) to diversify category exposure."
                )

                sig = EngineSignal(
                    signal_id=f"category_concentration::{cat_name}::{iid or fund_name[:20]}",
                    engine_name=self.engine_name,
                    rule_label="Rule 2b",
                    action_type="EXIT",
                    instrument_id=iid,
                    instrument_name=fund_name,
                    amount_rs=amount_rs,
                    base_score=item["exit_score"],
                    confidence=0.9,
                    risk_reduction=0.6,
                    diversification_gain=0.6,
                    urgency=0.5,
                    implementation_ease=0.5,
                    reason_codes=["CATEGORY_CONCENTRATION_EXIT"],
                    reason_text=reason_text,
                    dedup_key=f"EXIT::{iid or fund_name[:30]}",
                )
                sig.__dict__["_holding"] = h
                sig.__dict__["_candidate"] = item["candidate"]

                signals.append(sig)
                local_exited_keys.add(h_key)
                if iid:
                    local_exited_ids.add(iid)
                current_pct -= mf.get("amount_rs", 0) / total_mf_value * 100
                logger.debug(
                    "[CategoryConcentrationEngine] EXIT %s → %s pct now ~%.1f%%",
                    fund_name[:40], cat_name, current_pct,
                )

        return signals
