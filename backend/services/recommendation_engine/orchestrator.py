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
from services.recommendation_engine.persona_config import (
    get_persona_profile,
    map_behavioural_persona,
)

# ── Individual engines ───────────────────────────────────────────────────────
from services.recommendation_engine.engines.data_validation_engine import DataValidationEngine
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
from services.recommendation_engine.engines.risk_alignment_engine import RiskAlignmentEngine
from services.recommendation_engine.engines.portfolio_analytics_engine import PortfolioAnalyticsEngine
from services.recommendation_engine.engines.correlation_engine import CorrelationEngine
from services.recommendation_engine.engines.stock_scoring_engine import StockScoringEngine
from services.recommendation_engine.engines.category_suitability_engine import CategorySuitabilityEngine
from services.recommendation_engine.engines.behavioural_persona_filter_engine import BehaviouralPersonaFilterEngine
from services.recommendation_engine.engines.goal_bucket_first_engine import GoalBucketFirstEngine
from services.recommendation_engine.engines.concentration_engine import ConcentrationEngine

logger = logging.getLogger(__name__)

# ── Plugin registry — DataValidationEngine runs first (populates coverage flag) ──
ENGINE_REGISTRY: List[BaseEngine] = [
    DataValidationEngine(),           # DV-1..DV-3: data quality gate
    RiskAlignmentEngine(),            # RA-1..RA-3: risk profile caps (persona-calibrated)
    CategorySuitabilityEngine(),      # CS-1..CS-2: PRD §4 Rule 2 suitability gate (persona-aware)
    PortfolioAnalyticsEngine(),       # PA-1..PA-2: fund count / concentration
    RegularDirectEngine(),            # Rules 1 + 6: regular→direct
    AMCConcentrationEngine(),         # Rule 2: AMC concentration
    CategoryConcentrationEngine(),    # Rule 2b: category concentration
    UnderperformerEngine(),           # Rule 3: underperformer replacement (persona-calibrated)
    OverlapEngine(),                  # Rules 4 + 9: pairwise overlap
    CorrelationEngine(),              # CR-1: behavioural redundancy
    AllocationEngine(),               # Rule 5: debt allocation (persona-calibrated)
    SameCategoryEngine(),             # Rule 8: same-category consolidation
    InternationalEngine(),            # Rule 10: international fund gap
    DriftEngine(),                    # asset-class drift
    GoalAlignmentEngine(),            # GA-1..GA-4: goal alignment (wins AR-1)
    StockScoringEngine(),             # §10.9: direct equity scoring
    BehaviouralPersonaFilterEngine(), # BP-1: suppress instrument-type mismatches
    GoalBucketFirstEngine(),          # GBF-1/GBF-2: redirect new money to most-behind goal
    ConcentrationEngine(),            # CC-1/CC-2: persona single-holding + single-sector caps (PRD §6.2)
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
    risk_score_numeric: Optional[float] = None,
    behavioural_persona: Optional[str] = None,
    behavioural_confidence: float = 0.0,
    capacity_score: float = 50.0,
    tolerance_score: float = 50.0,
    capacity_tolerance_diverged: bool = False,
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

    # DV-1: Portfolio coverage pct — fraction of total_value_rs with a valid current_price
    if total_value_rs > 0:
        priced_value = sum(
            float(h.get("quantity", 0)) * float(h.get("current_price", 0))
            for h in holdings
            if (h.get("current_price") or 0) > 0
        )
        portfolio_coverage_pct = priced_value / total_value_rs * 100.0
    else:
        portfolio_coverage_pct = 100.0

    # DV-3: Holdings missing cost basis — suppress tax-aware EXIT signals for these
    tax_suppressed: set = set()
    for h in mf_holdings:
        iid = h.get("instrument_id")
        if iid and not any([
            h.get("buy_price"), h.get("average_cost_rs"), h.get("nav_at_purchase"),
            h.get("purchase_nav"), h.get("avg_cost"),
        ]):
            tax_suppressed.add(iid)

    # Resolve persona profile from risk_score (preferred) or profile string
    persona_profile = get_persona_profile(
        risk_profile_str=risk_profile,
        risk_score=risk_score_numeric,
    )

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
        portfolio_coverage_pct=portfolio_coverage_pct,
        tax_suppressed_instrument_ids=tax_suppressed,
        persona_profile=persona_profile,
        risk_score_numeric=risk_score_numeric,
        behavioural_persona=behavioural_persona or "unknown",
        behavioural_confidence=behavioural_confidence,
        capacity_score=capacity_score,
        tolerance_score=tolerance_score,
        capacity_tolerance_diverged=capacity_tolerance_diverged,
    )


def _signal_to_action(
    sig: EngineSignal,
    priority: int,
    confidence_tier: str = "generic",
    confidence_label: str = "Generic plan — add your profile",
    plan_confidence_score: float = 40.0,
) -> Dict[str, Any]:
    """Convert an EngineSignal to the backward-compatible action dict shape."""
    from services.recommendation_engine import conviction_templates
    _id = f"act_{uuid4().hex[:8]}"
    _confidence = (
        "HIGH" if sig.confidence >= 0.85
        else "MEDIUM" if sig.confidence >= 0.55
        else "LOW"
    )
    base: Dict[str, Any] = {
        # PRD §12 canonical field names
        "id": _id,
        "action": sig.action_type,
        "magnitude": round(sig.amount_rs, 2),
        "execution": sig.execution_path,
        # Legacy aliases — kept for backward compat with action_plan_manager consumers
        "action_id": _id,
        "type": sig.action_type,
        "amount": round(sig.amount_rs, 2),
        "execution_path": sig.execution_path,
        # Shared fields
        "priority": priority,
        "asset_type": "mutual_fund",
        "asset_name": sig.instrument_name,
        "confidence": _confidence,
        "reason_text": sig.reason_text,
        "reason_codes": sig.reason_codes,
        "status": "PENDING",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "engine_signal_id": sig.signal_id,
        "engine_name": sig.engine_name,
        # Phase 4: plan-level confidence tier rides on every action
        "confidence_tier": confidence_tier,
        "confidence_label": confidence_label,
        "plan_confidence_score": round(plan_confidence_score, 1),
        # Phase 5 (D-5): deferred action fields
        "defer_reason": sig.defer_reason,
        "execution_date": sig.execution_date,
        # Advisory conviction text — primary user-facing string (spec §1b).
        # Leads with fund/bucket name; reason precedes implied action.
        # Never contains "BUY", "SELL", or "HOLD" as standalone words.
        "conviction_text": conviction_templates.build(sig),
        # PRD §12 output contract fields
        "severity": sig.severity,
        "requires_confirmation": sig.requires_confirmation,
    }

    if sig.instrument_id:
        base["instrument_id"] = sig.instrument_id

    # Enrich with holding / candidate data if engine stashed them
    holding = sig.__dict__.get("_holding")
    candidate = sig.__dict__.get("_candidate")

    if sig.action_type in ("EXIT", "SWITCH", "TRIM") and holding:
        base["asset_name"] = holding.get("name") or sig.instrument_name
        base["asset_type"] = holding.get("asset_type", "mutual_fund")
        ti = (candidate or {}).get("tax_impact") or {}
        # For TRIM, carry estimated_tax_rs from the signal (pre-computed as a proportional fraction)
        if sig.action_type == "TRIM" and sig.estimated_tax_rs:
            ti = dict(ti)
            ti.setdefault("tax_liability", round(sig.estimated_tax_rs, 2))
        base["tax_impact"] = ti
        base["exit_score"] = (candidate or {}).get("exit_score")
        base["score_breakdown"] = (candidate or {}).get("score_breakdown")
    elif sig.action_type in ("EXIT", "TRIM"):
        # General allocation-level EXIT/TRIM with no specific holding stashed.
        # PRD §12 requires tax_impact to be non-null on all EXIT/TRIM actions.
        base["tax_impact"] = {}

    if sig.action_type == "ADD":
        fund_details = sig.__dict__.get("_fund_details")
        if fund_details:
            base["fund_details"] = fund_details
            base["asset_name"] = fund_details.get("fund_name") or sig.instrument_name
        fund_options = sig.__dict__.get("_fund_options")
        if fund_options:
            base["fund_options"] = fund_options  # top-3 ranked alternatives for fund picker

    if sig.suppressed:
        base["status"] = "SUPPRESSED"
        base["suppression_reason"] = sig.suppression_reason

    # PRD §12: expected_effect — risk-band Δ, score Δ, funding-probability Δ
    # Computed from the signal's AR-3 priority components as a best-effort estimate.
    # Exact values require a full portfolio re-simulation; these are directional signals.
    base["expected_effect"] = {
        "risk_band_delta": (
            "lower" if sig.risk_reduction >= 0.4 and sig.action_type in ("EXIT", "TRIM")
            else "higher" if sig.action_type == "ADD" and sig.diversification_gain < 0.3
            else "neutral"
        ),
        "score_delta_pct": round(sig.risk_reduction * 10 + sig.diversification_gain * 5, 1),
        "funding_probability_delta": round(sig.goal_impact * 15, 1) if sig.goal_impact > 0 else 0.0,
    }

    # PI-2 and PI-4 metadata for UI/trace
    pi2_wo = sig.__dict__.get("_pi2_weighted_overlap")
    if pi2_wo is not None:
        base["pi2_weighted_overlap"] = pi2_wo

    pi4 = sig.__dict__.get("_pi4_contribution_score")
    if pi4 is not None:
        base["pi4_contribution_score"] = pi4

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
    risk_score_numeric: Optional[float] = None,
    behavioural_persona: Optional[str] = None,
    behavioural_confidence: float = 0.0,
    capacity_score: float = 50.0,
    tolerance_score: float = 50.0,
    capacity_tolerance_diverged: bool = False,
) -> tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """
    Full recommendation pipeline. Called by _apply_action_rules() when
    engine_pipeline.enabled=True.

    Returns (actions, simulation_result):
      - actions: backward-compatible action dicts (same shape as legacy sequential rule output)
      - simulation_result: IS-1/IS-2 before/after dict, or None if simulation unavailable
    """
    # 1. Build context (includes persona_profile classification)
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
        risk_score_numeric=risk_score_numeric,
        behavioural_persona=behavioural_persona,
        behavioural_confidence=behavioural_confidence,
        capacity_score=capacity_score,
        tolerance_score=tolerance_score,
        capacity_tolerance_diverged=capacity_tolerance_diverged,
    )

    # 1a. Mandatory gate (PRD §4 Rule 1): no persona → prompt user, don't generate.
    if not ctx.persona_profile:
        logger.info("[Orchestrator] user=%s: no risk persona — skipping engine pipeline", user_id)
        return [], None, {"requires_persona": True, "requires_goal": False, "capacity_tolerance_diverged": False}

    # 1a-2. Phase 3 gate split: the 7 goal-agnostic engines always run.
    # Only GoalAlignmentEngine and GoalBucketFirstEngine self-gate when goals absent
    # (confirmed: both already return [] when ctx.goal_evaluations is empty).
    # The old binary "no goals → skip everything" blocked ~90% of users from getting
    # any recommendations. The requires_goal flag now only surfaces as a soft nudge
    # (not a hard wall) — handled by the frontend RecGateState variant="goal_nudge".
    _has_goals = bool(goal_evaluations)
    if not _has_goals:
        logger.info(
            "[Orchestrator] user=%s: no active goals — running 7 goal-agnostic engines; "
            "GoalAlignmentEngine + GoalBucketFirstEngine will self-skip. tag=no_goals_soft",
            user_id,
        )

    # 1a-3. Phase 4: populate confidence tier from TargetAllocation (best-effort).
    # This gives every action dict a confidence_tier without requiring a second DB round-trip
    # (compute_target_allocation was already called to produce deviation_result upstream).
    try:
        from services.target_allocator import compute_target_allocation as _cta
        _ta = await _cta(user_id)
        ctx.confidence_tier = _ta.confidence_tier
        ctx.confidence_label = _ta.confidence_label
        ctx.plan_confidence_score = _ta.confidence_score
    except Exception as _ta_exc:
        logger.debug("[Orchestrator] TargetAllocation fetch failed: %s — using default tier", _ta_exc)

    # 1b. Pre-fetch MF quality scores from DAAS (best-effort)
    # Merges quality_score, health_score, category_rank into v3_scores keyed by ISIN.
    # Engines (UnderperformerEngine, CategorySuitabilityEngine) use these for
    # PRD §6.2 exit/add threshold checks against NIDP 0-100 scale.
    if mf_holdings:
        try:
            from services.copilot_tools import daas_client as _daas
            isins = list({
                h.get("isin") or h.get("instrument_id", "")
                for h in mf_holdings
                if h.get("isin") or h.get("instrument_id")
            })[:100]
            if isins:
                mf_prims = await _daas.get_v3_mf_primitives_bulk(isins)
                for isin, prow in mf_prims.items():
                    existing = ctx.v3_scores.get(isin) or {}
                    existing.update({
                        "quality_score": prow.get("quality_score"),
                        "health_score": prow.get("health_score"),
                        "quality_coverage_pct": prow.get("quality_coverage_pct"),
                        "category_rank_pct": prow.get("category_rank_pct"),  # percentile 0-100
                        "composite_rank": prow.get("composite_rank"),
                        "total_in_category": prow.get("total_in_category"),
                        "fund_category": prow.get("fund_category"),
                        "mf_primitives": prow,
                    })
                    ctx.v3_scores[isin] = existing
        except Exception as _exc:
            logger.debug("[Orchestrator] MF quality scores prefetch skipped: %s", _exc)

    # 1d. Pre-fetch portfolio correlations (CR-1, best-effort — NIDP may be unconfigured)
    corr_cfg = rules_cfg.get("correlation") or {}
    if corr_cfg.get("enabled", True) and holdings:
        try:
            from services.copilot_tools import daas_client as _daas
            # Collect NIDP security_ids from holdings (instrument_id = UUID from ref.security_master)
            security_ids = [
                h["instrument_id"] for h in holdings
                if h.get("instrument_id") and len(h["instrument_id"]) == 36  # UUID check
            ][:50]
            if security_ids:
                min_abs_corr = float(corr_cfg.get("min_abs_correlation", 0.85))
                window_days = corr_cfg.get("window_days", 90)
                ctx.portfolio_correlations = await _daas.get_portfolio_correlations(
                    security_ids=security_ids,
                    min_abs_corr=0.7,   # fetch lower threshold; CR-1 filters at 0.85 itself
                    window_days=window_days,
                )
        except Exception as _exc:
            logger.debug("[Orchestrator] portfolio_correlations prefetch skipped: %s", _exc)

    # 1e. Pre-fetch stock V3 primitives (§10.9, best-effort)
    if ctx.stock_holdings:
        try:
            from services.copilot_tools import daas_client as _daas
            symbols = [
                (h.get("ticker") or h.get("symbol") or "").upper()
                for h in ctx.stock_holdings
                if h.get("ticker") or h.get("symbol")
            ]
            symbols = [s for s in symbols if s][:30]
            if symbols:
                stock_prims = await _daas.get_v3_stock_primitives_bulk(symbols)
                for sym, prow in stock_prims.items():
                    # Store under symbol and under instrument_id if available
                    ctx.v3_scores[sym] = {
                        "quality_score": None,   # computed by StockScoringEngine
                        "v3_primitives": prow,
                    }
                    # Also index by instrument_id if we can match
                    iid_match = next(
                        (h.get("instrument_id") for h in ctx.stock_holdings
                         if (h.get("ticker") or h.get("symbol") or "").upper() == sym),
                        None,
                    )
                    if iid_match:
                        ctx.v3_scores[iid_match] = ctx.v3_scores[sym]
        except Exception as _exc:
            logger.debug("[Orchestrator] stock primitives prefetch skipped: %s", _exc)

    # 1f. Pre-fetch top ADD fund candidates from NIDP DaaS (best-effort, Step 4)
    # Keyed by normalised category; engines fall back to static defaults when empty.
    _add_categories = ["debt", "large cap", "mid cap", "small cap", "flexi cap", "equity"]
    try:
        from services.copilot_tools import daas_client as _daas_add
        import asyncio as _asyncio
        _add_results = await _asyncio.gather(
            *[_daas_add.get_top_add_funds_by_category(cat, n=5) for cat in _add_categories],
            return_exceptions=True,
        )
        for cat, rows in zip(_add_categories, _add_results):
            if isinstance(rows, list) and rows:
                ctx.top_add_candidates[cat] = rows
    except Exception as _exc:
        logger.debug("[Orchestrator] ADD fund pre-fetch skipped: %s", _exc)

    # 1g. reconcile_bucket pre-pass (Phase 2 / D-7)
    # Runs BEFORE the engine registry so engines see already-designated exits.
    # Identifies fund-count exits (bucket_count_exit) for buckets above FUNDS_PER_BUCKET.
    # Uses canonical keep_score from survivor.py (normalized, D-2 weights).
    _reconcile_signals: List[EngineSignal] = []
    try:
        from services.recommendation_engine.constants import FUNDS_PER_BUCKET, classify_bucket
        from services.recommendation_engine.survivor import select_survivors
        from uuid import uuid4 as _uuid4

        # Group MF holdings by bucket
        bucket_funds: Dict[str, List[Dict[str, Any]]] = {}
        for h in (mf_holdings or []):
            fid = h.get("isin") or h.get("instrument_id") or h.get("id") or ""
            if not fid:
                continue
            bucket = classify_bucket(
                h.get("asset_class") or h.get("asset_type") or "",
                h.get("category") or h.get("fund_category") or "",
            )
            bucket_funds.setdefault(bucket, []).append(h)

        for bucket, bucket_holdings in bucket_funds.items():
            target_count = FUNDS_PER_BUCKET.get(bucket, 3)
            if len(bucket_holdings) <= target_count:
                continue  # no consolidation needed

            fund_ids = [
                h.get("isin") or h.get("instrument_id") or h.get("id") or ""
                for h in bucket_holdings
            ]
            fund_ids = [fid for fid in fund_ids if fid]
            if not fund_ids:
                continue

            # Overlap data from portfolio_intelligence (best-effort)
            overlap_data: Dict[str, float] = {}
            for pair in (ctx.portfolio_intelligence.get("pairwise_overlap") or []):
                a_id = pair.get("isin_a") or pair.get("a")
                b_id = pair.get("isin_b") or pair.get("b")
                pct  = pair.get("overlap_pct") or pair.get("overlap") or 0.0
                if a_id in fund_ids:
                    overlap_data[a_id] = overlap_data.get(a_id, 0.0) + float(pct)
                if b_id in fund_ids:
                    overlap_data[b_id] = overlap_data.get(b_id, 0.0) + float(pct)

            survivors, exits, overlap_available = select_survivors(
                fund_ids=fund_ids,
                n=target_count,
                v3_scores=ctx.v3_scores,
                overlap_data=overlap_data if overlap_data else None,
                amc_cap_breaches=set(),  # AMC cap handled by ArbitrationEngine
            )

            # Mark exits in ctx so downstream engines don't re-propose them
            for fid in exits:
                ctx.exited_ids.add(fid)

            # Emit bucket_count_exit signals for each exit
            for fid in exits:
                # Find the holding dict for conviction text
                h = next((x for x in bucket_holdings
                           if (x.get("isin") or x.get("instrument_id") or x.get("id")) == fid), {})
                fname = h.get("name") or h.get("fund_name") or h.get("scheme_name") or fid[:8]
                sig_id = f"bucket_count::{bucket}::{fid[:8]}"
                sig = EngineSignal(
                    signal_id=sig_id,
                    engine_name="reconcile_bucket",
                    rule_label="BucketCount",
                    action_type="EXIT",
                    instrument_id=fid,
                    instrument_name=fname,
                    amount_rs=float(h.get("current_value") or h.get("value") or 0),
                    base_score=4.0,
                    confidence=0.65,
                    risk_reduction=0.3,
                    diversification_gain=0.4,
                    urgency=0.4,
                    implementation_ease=0.6,
                    reason_codes=["BUCKET_COUNT_EXIT"],
                    reason_text=(
                        f"{bucket.capitalize()} bucket has {len(bucket_holdings)} funds; "
                        f"target is {target_count}. Lowest-ranked by quality and cost."
                    ),
                    dedup_key=f"EXIT::bucket_count::{fid}",
                )
                _reconcile_signals.append(sig)

            if not overlap_available:
                ctx.telemetry["data_quality_warning"] = (
                    ctx.telemetry.get("data_quality_warning") or []
                )
                ctx.telemetry["data_quality_warning"].append(
                    f"overlap unavailable for {bucket} bucket — using cost+perf+amc only"
                )

        if _reconcile_signals:
            logger.info(
                "[Orchestrator] reconcile_bucket: %d bucket_count_exit signals across %d buckets",
                len(_reconcile_signals),
                len({s.reason_text.split(" bucket")[0].lower() for s in _reconcile_signals}),
            )
    except Exception as _exc:
        logger.warning("[Orchestrator] reconcile_bucket pre-pass failed: %s", _exc)

    # 2. Collect signals from all engines (pure, no I/O)
    # reconcile_bucket signals are prepended so they're visible to arbitration
    all_signals: List[EngineSignal] = list(_reconcile_signals)
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

    # 5b. Phase 5 — sell_score-based trade ordering (D-3).
    # Order: ADD (new inflows) first; within EXITs, sell_score highest goes first
    # (highest sell_score = cheapest to sell + most redundant).
    # Deferred actions move to the end regardless of sell_score.
    try:
        from services.recommendation_engine.survivor import sort_exits_by_sell_score
        _active = [s for s in arbitrated if not s.suppressed]
        _adds    = [s for s in _active if s.action_type == "ADD" and not s.defer_reason]
        _exits   = [s for s in _active if s.action_type in ("EXIT", "TRIM", "SWITCH")
                    and not s.defer_reason]
        _other   = [s for s in _active if s.action_type not in ("ADD","EXIT","TRIM","SWITCH")
                    and not s.defer_reason]
        _deferred = [s for s in _active if s.defer_reason]

        # Build overlap lookup for sell_score
        _ov: dict = {}
        for pair in (portfolio_intelligence.get("pairwise_overlap") or []):
            a_id = pair.get("isin_a") or pair.get("a")
            b_id = pair.get("isin_b") or pair.get("b")
            pct  = float(pair.get("overlap_pct") or pair.get("overlap") or 0)
            if a_id:
                _ov[a_id] = _ov.get(a_id, 0.0) + pct
            if b_id:
                _ov[b_id] = _ov.get(b_id, 0.0) + pct

        sort_exits_by_sell_score(_exits, ctx.v3_scores, _ov, total_value_rs)

        # Reassemble: ADD → sorted EXITs → other → deferred
        arbitrated_ordered = _adds + _exits + _other + _deferred
        # Re-add suppressed for audit trail
        arbitrated_ordered += [s for s in arbitrated if s.suppressed]
        arbitrated = arbitrated_ordered
    except Exception as _ord_exc:
        logger.warning("[Orchestrator] trade ordering failed: %s — using default order", _ord_exc)

    # 6. Convert signals → backward-compatible action dicts
    active_signals = [s for s in arbitrated if not s.suppressed]
    max_actions = int((rules_cfg.get("plan_limits") or {}).get("max_actions_per_plan", 6))
    actions: List[Dict[str, Any]] = []
    for i, sig in enumerate(active_signals[:max_actions]):
        actions.append(_signal_to_action(
            sig,
            priority=i + 1,
            confidence_tier=ctx.confidence_tier,
            confidence_label=ctx.confidence_label,
            plan_confidence_score=ctx.plan_confidence_score,
        ))

    # 7. Stamp V3 scores
    for a in actions:
        iid = a.get("instrument_id")
        if iid and ctx.v3_scores.get(iid):
            v3 = ctx.v3_scores[iid]
            a["v3_scores"] = {
                k: v3[k]
                for k in ("quality_score", "health_score", "exit_score", "add_score",
                          "category_rank_pct", "composite_rank", "total_in_category")
                if k in v3
            }

    # 8. Fallback: no actions → top 2 exit candidates
    if not actions and exit_candidates:
        logger.info("[Orchestrator] no actions from engines — falling back to top exit candidates")
        for i, cand in enumerate(exit_candidates[:2]):
            _fb_id = f"act_{uuid4().hex[:8]}"
            actions.append({
                "id": _fb_id, "action": "EXIT", "magnitude": 0, "execution": "sell-now",
                "action_id": _fb_id, "type": "EXIT", "amount": 0, "execution_path": "sell-now",
                "priority": i + 1,
                "asset_type": "mutual_fund",
                "asset_name": cand.get("instrument_name", ""),
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

    # Telemetry: emit exactly one of three tags so ops can distinguish
    # "engine didn't run" from "engine ran, nothing to do" from "actions emitted".
    if ctx.telemetry.get("skipped:no_target"):
        telem_tag = "skipped:no_target"
    elif not actions:
        telem_tag = "ran:no_drift"
        ctx.telemetry["ran:no_drift"] = True
    else:
        telem_tag = "ran:actions_emitted"
        ctx.telemetry["ran:actions_emitted"] = True

    logger.info(
        "[Orchestrator] pipeline complete: %d actions (%d signals, %d suppressed) tag=%s",
        len(actions), len(active_signals),
        sum(1 for s in arbitrated if s.suppressed),
        telem_tag,
    )

    gate_flags: Dict[str, bool] = {
        "requires_persona": False,
        # Phase 3: requires_goal is a soft nudge, not a hard wall.
        # True = "user has no goals, show the goal_nudge banner"
        # False = "user has goals, no nudge needed"
        # Either way, actions are returned (the hard block is gone).
        "requires_goal": not _has_goals,
        "capacity_tolerance_diverged": ctx.capacity_tolerance_diverged,
    }
    return actions, simulation_result, gate_flags
