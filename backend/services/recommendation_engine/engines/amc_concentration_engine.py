"""
AMCConcentrationEngine — Rule 2: EXIT holdings when a single AMC > threshold %.

Reads exited_ids from context (set by orchestrator after prior runs).
Emits one EXIT EngineSignal per holding that needs to be sold, in greedy order
(highest exit_score first) until the AMC drops below the threshold.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from services.recommendation_engine.base_engine import BaseEngine
from services.recommendation_engine.context import EngineSignal, RecommendationContext
from services.recommendation_engine.helpers import (
    calc_amc_exposure,
    extract_amc_from_name,
    fuzzy_match_holding,
    normalize_fund_name,
)

logger = logging.getLogger(__name__)


def _holding_key(h: Dict[str, Any]) -> str:
    return f"{h.get('user_id','')}::{normalize_fund_name(h.get('name',''))}"


class AMCConcentrationEngine(BaseEngine):
    """Rule 2 (P0): AMC concentration above threshold → EXIT highest-exit-score funds."""

    engine_name = "AMCConcentrationEngine"
    enabled_config_key = "rule_2_amc_concentration.enabled"

    def generate(self, ctx: RecommendationContext) -> List[EngineSignal]:
        mf_investments = ctx.portfolio_intelligence.get("mf_investments") or []
        total_value = ctx.total_value_rs
        if total_value <= 0 or not mf_investments:
            return []

        r2_params = (ctx.rules_cfg.get("rule_2_amc_concentration") or {}).get("params", {})
        threshold = float(r2_params.get("threshold_pct", 15.0))

        amc_exposure = calc_amc_exposure(mf_investments, total_value)
        over_amcs = [
            (amc, pct) for amc, pct in amc_exposure.items() if pct >= threshold
        ]
        over_amcs.sort(key=lambda x: -x[1])
        logger.debug("[AMCConcentrationEngine] over-concentrated: %s", over_amcs)

        signals: List[EngineSignal] = []
        local_exited_ids: set = set()      # tracks exits within this engine run
        local_exited_keys: set = set()

        # Build candidate lookup by instrument_id
        candidate_by_id: Dict[str, Dict] = {
            c.get("instrument_id"): c for c in ctx.exit_candidates if c.get("instrument_id")
        }

        def _exit_rank(iid: Optional[str], name: Optional[str] = None) -> float:
            """Use V3 exit score when available, else legacy."""
            v3 = ctx.v3_scores.get(iid or "", {})
            if v3.get("exit_score") is not None:
                return float(v3["exit_score"])
            cand = candidate_by_id.get(iid or "")
            return float((cand or {}).get("exit_score", 5.0))

        for amc_name, amc_pct in over_amcs:
            amc_funds = [
                m for m in mf_investments
                if extract_amc_from_name(m.get("scheme_name", "")) == amc_name
                and m.get("instrument_id") not in ctx.exited_ids
                and m.get("instrument_id") not in local_exited_ids
            ]

            ranked = sorted(
                [
                    {
                        "mf": m,
                        "candidate": candidate_by_id.get(m.get("instrument_id")),
                        "exit_score": _exit_rank(m.get("instrument_id"), m.get("scheme_name")),
                    }
                    for m in amc_funds
                ],
                key=lambda x: x["exit_score"],
                reverse=True,
            )

            current_pct = amc_pct
            for item in ranked:
                if current_pct < threshold:
                    break
                mf = item["mf"]
                h = fuzzy_match_holding(mf.get("scheme_name", ""), ctx.mf_holdings)
                if not h:
                    continue
                h_key = _holding_key(h)
                if h_key in ctx.exited_holding_keys or h_key in local_exited_keys:
                    current_pct -= (mf.get("amount_rs", 0) / total_value * 100)
                    continue

                fund_name = (h.get("name") or mf.get("scheme_name") or "")
                iid = mf.get("instrument_id")
                amount_rs = float(h.get("quantity", 0)) * float(h.get("current_price", 0))

                reason_text = (
                    f"Reducing {amc_name} AMC concentration from {current_pct:.1f}% "
                    f"toward <{threshold:.0f}% target. "
                    f"Exit score = {item['exit_score']:.1f} (highest in this AMC)."
                )

                sig = EngineSignal(
                    signal_id=f"amc_concentration::{amc_name}::{iid or fund_name[:20]}",
                    engine_name=self.engine_name,
                    rule_label="Rule 2",
                    action_type="EXIT",
                    instrument_id=iid,
                    instrument_name=fund_name,
                    amount_rs=amount_rs,
                    base_score=item["exit_score"],
                    confidence=0.9,
                    risk_reduction=0.7,
                    diversification_gain=0.5,
                    urgency=0.6,
                    implementation_ease=0.5,
                    reason_codes=["AMC_CONCENTRATION_EXIT"],
                    reason_text=reason_text,
                    dedup_key=f"EXIT::{iid or fund_name[:30]}",
                )
                sig.__dict__["_holding"] = h
                sig.__dict__["_candidate"] = item["candidate"]

                signals.append(sig)
                local_exited_keys.add(h_key)
                if iid:
                    local_exited_ids.add(iid)

                current_pct -= (mf.get("amount_rs", 0) / total_value * 100)
                logger.debug(
                    "[AMCConcentrationEngine] EXIT %s → AMC pct now ~%.1f%%",
                    fund_name[:40], current_pct,
                )

        return signals
