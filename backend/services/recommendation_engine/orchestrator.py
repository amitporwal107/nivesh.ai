"""
Recommendation Engine Orchestrator.

run_engine_pipeline() is the new entry point called by _apply_action_rules()
when engine_pipeline.enabled=True.

build_context() constructs a RecommendationContext from the same inputs that
_apply_action_rules() already receives (no new I/O needed at call time).

ENGINE_REGISTRY is the plugin list; append YourEngine() here to register it.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from services.recommendation_engine.context import (
    EngineSignal,
    HoldingWeight,
    RecommendationContext,
)
from services.recommendation_engine.base_engine import BaseEngine
from services.recommendation_engine.portfolio_impact_engine import PortfolioImpactEngine
from services.recommendation_engine.arbitration_engine import ArbitrationEngine
from services.recommendation_engine.helpers import normalize_fund_name

# ── Individual engines ───────────────────────────────────────────────────────
from services.recommendation_engine.engines.regular_direct_engine import RegularDirectEngine
from services.recommendation_engine.engines.amc_concentration_engine import AMCConcentrationEngine
from services.recommendation_engine.engines.category_concentration_engine import CategoryConcentrationEngine
from services.recommendation_engine.engines.underperformer_engine import UnderperformerEngine
from services.recommendation_engine.engines.overlap_engine import OverlapEngine
from services.recommendation_engine.engines.allocation_engine import AllocationEngine
from services.recommendation_engine.engines.same_category_engine import SameCategoryEngine
from services.recommendation_engine.engines.international_engine import InternationalEngine
from services.recommendation_engine.engines.drift_engine import DriftEngine
from services.recommendation_engine.engines.goal_alignment_engine import GoalAlignmentEngine

logger = logging.getLogger(__name__)

# ── Plugin registry — order matters for tiebreaking only (AR-1 handles dedup) ──
ENGINE_REGISTRY: List[BaseEngine] = [
    RegularDirectEngine(),
    AMCConcentrationEngine(),
    CategoryConcentrationEngine(),
    UnderperformerEngine(),
    OverlapEngine(),
    AllocationEngine(),
    SameCategoryEngine(),
    InternationalEngine(),
    DriftEngine(),
    GoalAlignmentEngine(),
]


def _holding_weight(h: Dict[str, Any], total_value_rs: float) -> HoldingWeight:
    """Compute HoldingWeight (PRD PI-1) for a single holding."""
    value = float(h.get("quantity", 0)) * float(h.get("current_price", 0))
    weight_pct = (value / total_value_rs * 100.0) if total_value_rs > 0 else 0.0
    if weight_pct < 2.0:
        mult = 0.4
    elif weight_pct < 5.0:
        mult = 0.7
    elif weight_pct < 10.0:
        mult = 1.0
    elif weight_pct < 20.0:
        mult = 1.3
    else:
        mult = 1.7
    return HoldingWeight(
        instrument_id=h.get("instrument_id"),
        instrument_name=h.get("name") or h.get("scheme_name") or "",
        current_rs=value,
        weight_pct=round(weight_pct, 2),
        allocation_multiplier=mult,
    )


def build_context(
    *,
    user_id: str,
    risk_profile: str,
    total_value_rs: float,
    holdings: List[Dict[str, Any]],
    mf_holdings: List[Dict[str, Any]],
    stock_holdings: List[Dict[str, Any]],
    portfolio_intelligence: Dict[str, Any],
    exit_candidates: List[Dict[str, Any]],
    v3_scores: Dict[str, Dict[str, Any]],
    rules_cfg: Dict[str, Any],
    signals: List[Dict[str, Any]],
    goal_evaluations: Optional[List] = None,
    deviation_result: Optional[Any] = None,
    international_funds_cache: Optional[List[Dict[str, Any]]] = None,
) -> RecommendationContext:
    """Construct a RecommendationContext from caller-supplied data.

    All I/O (DB queries, scoring) must be done by the caller before calling
    build_context(); this function is pure.
    """
    # Pre-compute holding weights (PI-1)
    holding_weights: Dict[str, HoldingWeight] = {}
    for h in holdings:
        hw = _holding_weight(h, total_value_rs)
        if hw.instrument_id:
            holding_weights[hw.instrument_id] = hw
        name_key = normalize_fund_name(hw.instrument_name)
        if name_key:
            holding_weights[name_key] = hw

    return RecommendationContext(
        user_id=user_id,
        risk_profile=risk_profile,
        total_value_rs=total_value_rs,
        holdings=holdings,
        mf_holdings=mf_holdings,
        stock_holdings=stock_holdings,
        portfolio_intelligence=portfolio_intelligence,
        exit_candidates=exit_candidates,
        v3_scores=v3_scores,
        holding_weights=holding_weights,
        goal_evaluations=goal_evaluations or [],
        deviation_result=deviation_result,
        rules_cfg=rules_cfg,
        signals=signals,
        international_funds_cache=international_funds_cache or [],
    )


def _signal_to_action(
    sig: EngineSignal,
    priority: int,
) -> Dict[str, Any]:
    """Convert an EngineSignal to the backward-compatible action dict shape."""
    base: Dict[str, Any] = {
        "action_id": f"act_{uuid4().hex[:8]}",
        "type": sig.action_type,
        "priority": priority,
        "asset_type": "mutual_fund",
        "asset_name": sig.instrument_name,
        "amount": round(sig.amount_rs, 2),
        "confidence": (
            "HIGH" if sig.confidence >= 0.85
            else "MEDIUM" if sig.confidence >= 0.55
            else "LOW"
        ),
        "reason_text": sig.reason_text,
        "reason_codes": sig.reason_codes,
        "status": "PENDING",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "engine_signal_id": sig.signal_id,
        "engine_name": sig.engine_name,
    }

    if sig.instrument_id:
        base["instrument_id"] = sig.instrument_id

    # Enrich with holding / candidate data if engine stashed them
    holding = sig.__dict__.get("_holding")
    candidate = sig.__dict__.get("_candidate")

    if sig.action_type in ("EXIT", "SWITCH") and holding:
        base["asset_name"] = holding.get("name") or sig.instrument_name
        base["asset_type"] = holding.get("asset_type", "mutual_fund")
        ti = (candidate or {}).get("tax_impact") or {}
        base["tax_impact"] = ti
        base["exit_score"] = (candidate or {}).get("exit_score")
        base["score_breakdown"] = (candidate or {}).get("score_breakdown")

    if sig.action_type == "ADD":
        fund_details = sig.__dict__.get("_fund_details")
        if fund_details:
            base["fund_details"] = fund_details
            base["asset_name"] = fund_details.get("fund_name") or sig.instrument_name

    if sig.suppressed:
        base["status"] = "SUPPRESSED"
        base["suppression_reason"] = sig.suppression_reason

    return base


async def run_engine_pipeline(
    *,
    user_id: str,
    risk_profile: str,
    total_value_rs: float,
    holdings: List[Dict[str, Any]],
    mf_holdings: List[Dict[str, Any]],
    stock_holdings: List[Dict[str, Any]],
    portfolio_intelligence: Dict[str, Any],
    mf_investments: List[Dict[str, Any]],
    exit_candidates: List[Dict[str, Any]],
    v3_scores: Dict[str, Dict[str, Any]],
    rules_cfg: Dict[str, Any],
    signals: List[Dict[str, Any]],
    goal_evaluations: Optional[List] = None,
    deviation_result: Optional[Any] = None,
    international_funds_cache: Optional[List[Dict[str, Any]]] = None,
) -> tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """
    Full recommendation pipeline. Called by _apply_action_rules() when
    engine_pipeline.enabled=True.

    Returns (actions, simulation_result):
      - actions: backward-compatible action dicts (same shape as legacy sequential rule output)
      - simulation_result: IS-1/IS-2 before/after dict, or None if simulation unavailable
    """
    # 1. Build context
    ctx = build_context(
        user_id=user_id,
        risk_profile=risk_profile,
        total_value_rs=total_value_rs,
        holdings=holdings,
        mf_holdings=mf_holdings,
        stock_holdings=stock_holdings,
        portfolio_intelligence=portfolio_intelligence,
        exit_candidates=exit_candidates,
        v3_scores=v3_scores,
        rules_cfg=rules_cfg,
        signals=signals,
        goal_evaluations=goal_evaluations,
        deviation_result=deviation_result,
        international_funds_cache=international_funds_cache,
    )

    # 2. Collect signals from all engines (pure, no I/O)
    all_signals: List[EngineSignal] = []
    for engine in ENGINE_REGISTRY:
        try:
            engine_signals = engine.safe_generate(ctx)
            all_signals.extend(engine_signals)
        except Exception as exc:
            logger.exception("[Orchestrator] engine %s failed: %s", engine.engine_name, exc)

    logger.info(
        "[Orchestrator] collected %d raw signals from %d engines",
        len(all_signals), len(ENGINE_REGISTRY),
    )

    # 3. Allocation weighting (PI-1..PI-4)
    weighted = PortfolioImpactEngine().apply(all_signals, ctx)

    # 4. Arbitration (AR-1, AR-2, AR-3)
    arbitrated = ArbitrationEngine().arbitrate(weighted, ctx)

    # 5. Update dedup state on ctx from arbitrated (non-suppressed) signals
    for sig in arbitrated:
        if sig.suppressed:
            continue
        if sig.action_type in ("EXIT", "SWITCH"):
            if sig.instrument_id:
                ctx.exited_ids.add(sig.instrument_id)
            holding = sig.__dict__.get("_holding")
            if holding:
                from services.recommendation_engine.helpers import normalize_fund_name
                h_key = f"{holding.get('user_id','')}::{normalize_fund_name(holding.get('name',''))}"
                ctx.exited_holding_keys.add(h_key)
        elif sig.action_type == "ADD":
            bucket_key = sig.__dict__.get("_complement_category") or sig.dedup_key
            ctx.added_buckets.add(bucket_key)

    # 6. Convert signals → backward-compatible action dicts
    active_signals = [s for s in arbitrated if not s.suppressed]
    max_actions = int((rules_cfg.get("plan_limits") or {}).get("max_actions_per_plan", 6))
    actions: List[Dict[str, Any]] = []
    for i, sig in enumerate(active_signals[:max_actions]):
        actions.append(_signal_to_action(sig, priority=i + 1))

    # 7. Stamp V3 scores
    for a in actions:
        iid = a.get("instrument_id")
        if iid and ctx.v3_scores.get(iid):
            v3 = ctx.v3_scores[iid]
            a["v3_scores"] = {
                k: v3[k] for k in ("quality_score", "health_score", "exit_score", "add_score")
                if k in v3
            }

    # 8. Fallback: no actions → top 2 exit candidates
    if not actions and exit_candidates:
        logger.info("[Orchestrator] no actions from engines — falling back to top exit candidates")
        for i, cand in enumerate(exit_candidates[:2]):
            actions.append({
                "action_id": f"act_{uuid4().hex[:8]}",
                "type": "EXIT",
                "priority": i + 1,
                "asset_type": "mutual_fund",
                "asset_name": cand.get("instrument_name", ""),
                "amount": 0,
                "confidence": "MEDIUM",
                "reason_text": f"Exit score {cand.get('exit_score', 5.0):.1f} — consider reviewing this holding.",
                "reason_codes": ["EXIT_CANDIDATE"],
                "status": "PENDING",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "exit_score": cand.get("exit_score"),
            })

    # 9. Simulation (IS-1: before/after; IS-2: marginal suppression)
    from services.recommendation_engine.simulation_engine import SimulationEngine
    sim_engine = SimulationEngine()
    actions, simulation_result = sim_engine.run(actions, ctx)
    # Stash simulation on ctx for callers that need it (e.g. generate_plan)
    ctx.__dict__["_simulation_result"] = simulation_result

    logger.info(
        "[Orchestrator] pipeline complete: %d actions (%d signals, %d suppressed)",
        len(actions), len(active_signals),
        sum(1 for s in arbitrated if s.suppressed),
    )

    return actions, simulation_result
