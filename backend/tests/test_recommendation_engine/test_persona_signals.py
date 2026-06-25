"""
Tests for persona-calibrated recommendation engine signals.

Covers:
  - CategorySuitabilityEngine gates stock exposure for Conservative persona
  - GoalBucketFirstEngine emits ADD signals for at-risk goals
  - BehaviouralPersonaFilterEngine suppresses stock ADD for MF-investor persona
  - AllocationEngine uses persona debt target (not hardcoded 20%)
  - severity / execution_path fields populated on every signal
"""
from __future__ import annotations

import sys
sys.path.insert(0, "/app/backend")

import pytest
from services.recommendation_engine.context import RecommendationContext
from services.recommendation_engine.persona_config import (
    RiskPersonaType, classify_risk_persona, get_persona_profile,
)
from services.recommendation_engine.engines.category_suitability_engine import CategorySuitabilityEngine
from services.recommendation_engine.engines.goal_bucket_first_engine import GoalBucketFirstEngine
from services.recommendation_engine.engines.behavioural_persona_filter_engine import BehaviouralPersonaFilterEngine
from services.recommendation_engine.engines.allocation_engine import AllocationEngine
from tests.test_recommendation_engine.fixtures import _BASE_RULES_CFG, _mf_holding, _mf_investment


# ─── Helpers ────────────────────────────────────────────────────────────────

def _stock_holding(name: str, value: float) -> dict:
    return {
        "asset_type": "stock",
        "name": name,
        "quantity": 10,
        "current_price": value / 10,
        "buy_price": value / 12,
        "category": "Large Cap",
        "instrument_id": f"isin_STOCK_{name.replace(' ','_').upper()}",
        "user_id": "test_user",
        "is_direct_equity": True,
    }


def _goal_eval(health: str, on_track_pct: float, gap_rs: float, goal_type: str = "retirement", horizon: float = 20.0) -> dict:
    return {
        "health_status": health,
        "on_track_pct": on_track_pct,
        "gap_rs": gap_rs,
        "goal_name": f"My {goal_type} goal",
        "goal_type": goal_type,
        "horizon_years": horizon,
        "priority": "high",
        "monthly_sip_rs": 10_000,
    }


def _base_ctx(
    total_rs: float = 1_000_000,
    risk_profile: str = "Conservative",
    risk_score: float = 75.0,
    holdings=None,
    mf_holdings=None,
    stock_holdings=None,
    goal_evaluations=None,
    portfolio_intelligence=None,
    behavioural_persona: str = "balanced_investor",
    behavioural_confidence: float = 0.8,
) -> RecommendationContext:
    holdings = holdings or []
    mf_holdings = mf_holdings or []
    stock_holdings = stock_holdings or []
    goal_evaluations = goal_evaluations or []

    persona_profile = get_persona_profile(
        risk_profile_str=risk_profile,
        risk_score=risk_score,
    )

    return RecommendationContext(
        user_id="test_user",
        risk_profile=risk_profile,
        total_value_rs=total_rs,
        holdings=holdings + mf_holdings + stock_holdings,
        mf_holdings=mf_holdings,
        stock_holdings=stock_holdings,
        portfolio_intelligence=portfolio_intelligence or {
            "asset_allocation": {"equity_pct": 30.0, "debt_pct": 5.0},
            "mf_investments": [],
        },
        exit_candidates=[],
        v3_scores={},
        holding_weights={},
        goal_evaluations=goal_evaluations,
        deviation_result=None,
        rules_cfg=_BASE_RULES_CFG,
        signals=[],
        persona_profile=persona_profile,
        risk_score_numeric=risk_score,
        behavioural_persona=behavioural_persona,
        behavioural_confidence=behavioural_confidence,
    )


# ─── persona_config ──────────────────────────────────────────────────────────

def test_classify_risk_persona_conservative():
    assert classify_risk_persona(risk_score=75) == RiskPersonaType.CONSERVATIVE

def test_classify_risk_persona_aggressive():
    assert classify_risk_persona(risk_score=10) == RiskPersonaType.AGGRESSIVE

def test_classify_risk_persona_balanced():
    assert classify_risk_persona(risk_score=43) == RiskPersonaType.BALANCED

def test_classify_risk_persona_from_string_conservative():
    pp = get_persona_profile(risk_profile_str="Conservative")
    assert pp is not None
    assert pp.persona_type == RiskPersonaType.CONSERVATIVE

def test_persona_profile_conservative_thresholds():
    pp = get_persona_profile(risk_profile_str="Conservative")
    assert pp.equity_target_pct[1] <= 45.0, f"Conservative equity max should be ≤45%, got {pp.equity_target_pct}"
    assert pp.debt_mid_target >= 50.0, f"Conservative debt target should be ≥50%, got {pp.debt_mid_target}"
    assert pp.target_holdings_max <= 15, f"Conservative holdings max should be ≤15, got {pp.target_holdings_max}"


# ─── CategorySuitabilityEngine ───────────────────────────────────────────────

def test_cs1_exits_smallcap_for_conservative_persona():
    """Conservative persona should not hold Small Cap — CS-1 must emit EXIT."""
    smallcap_mf = _mf_investment("Nippon Small Cap Fund", 100_000, "Small Cap", "Nippon")
    smallcap_mf["instrument_id"] = "isin_NIPPON_SMALLCAP"
    ctx = _base_ctx(
        risk_profile="Conservative", risk_score=75.0,
        portfolio_intelligence={
            "asset_allocation": {"equity_pct": 100.0, "debt_pct": 0.0},
            "mf_investments": [smallcap_mf],
        },
    )
    engine = CategorySuitabilityEngine()
    signals = engine.generate(ctx)
    exit_sigs = [s for s in signals if s.action_type == "EXIT"]
    assert exit_sigs, "Expected at least one EXIT signal for Small Cap in Conservative portfolio"
    assert all(s.severity == "severe" for s in exit_sigs), "CS-1 exits must be severity=severe"


def test_cs1_allows_large_cap_for_conservative():
    """Conservative persona CAN hold Large Cap — no EXIT signal expected."""
    largecap_mf = _mf_investment("Axis Bluechip Fund", 100_000, "Large Cap", "Axis")
    largecap_mf["instrument_id"] = "isin_AXIS_BLUECHIP"
    ctx = _base_ctx(
        risk_profile="Conservative", risk_score=75.0,
        portfolio_intelligence={
            "asset_allocation": {"equity_pct": 100.0, "debt_pct": 0.0},
            "mf_investments": [largecap_mf],
        },
    )
    engine = CategorySuitabilityEngine()
    signals = engine.generate(ctx)
    exit_sigs = [s for s in signals if s.action_type == "EXIT"]
    assert not exit_sigs, f"No EXIT expected for Large Cap in Conservative, got {exit_sigs}"


# ─── GoalBucketFirstEngine ───────────────────────────────────────────────────

def test_gbf1_emits_add_for_at_risk_goal():
    """At-risk goal → ADD signal toward appropriate asset class."""
    ge = _goal_eval("at_risk", on_track_pct=55.0, gap_rs=500_000)
    ctx = _base_ctx(goal_evaluations=[ge])
    engine = GoalBucketFirstEngine()
    signals = engine.generate(ctx)
    add_sigs = [s for s in signals if s.action_type == "ADD"]
    assert add_sigs, "Expected at least one ADD signal for at-risk goal"
    sig = add_sigs[0]
    assert sig.goal_impact > 0.5
    assert sig.execution_path == "redirect"


def test_gbf1_no_signals_for_on_track_goal():
    """On-track goal must not produce ADD signals."""
    ge = _goal_eval("on_track", on_track_pct=95.0, gap_rs=0)
    ctx = _base_ctx(goal_evaluations=[ge])
    engine = GoalBucketFirstEngine()
    signals = engine.generate(ctx)
    assert not signals, f"No signals expected for on-track goal, got {signals}"


def test_gbf1_critical_goal_gets_severe_severity():
    ge = _goal_eval("critical", on_track_pct=30.0, gap_rs=2_000_000)
    ctx = _base_ctx(goal_evaluations=[ge])
    engine = GoalBucketFirstEngine()
    signals = engine.generate(ctx)
    assert signals
    assert signals[0].severity == "severe"


def test_gbf1_short_horizon_prefers_debt():
    """Short horizon (2y) goal must suggest debt, not equity."""
    ge = _goal_eval("at_risk", on_track_pct=60.0, gap_rs=200_000, horizon=2.0)
    ctx = _base_ctx(goal_evaluations=[ge])
    engine = GoalBucketFirstEngine()
    signals = engine.generate(ctx)
    add_sigs = [s for s in signals if s.action_type == "ADD"]
    assert add_sigs
    fund_name = add_sigs[0].instrument_name.lower()
    assert any(kw in fund_name for kw in ("bond", "liquid", "debt", "gilt")), (
        f"Expected debt fund for 2y horizon, got: {add_sigs[0].instrument_name}"
    )


# ─── BehaviouralPersonaFilterEngine ──────────────────────────────────────────

def test_bp1_mf_investor_suppresses_stock_add():
    """MF investor persona emits BP-1 advisory when user holds direct equity stocks."""
    ctx = _base_ctx(
        behavioural_persona="mutual_fund_investor",
        behavioural_confidence=0.85,
        stock_holdings=[_stock_holding("Reliance Industries", 50_000)],
    )
    engine = BehaviouralPersonaFilterEngine()
    signals = engine.generate(ctx)
    bp1_sigs = [s for s in signals if "BP-1" in s.rule_label or "bp1" in s.signal_id]
    assert bp1_sigs, "Expected BP-1 signal for MF-investor holding direct equity"
    # BP-1 signal must have suppressed=True
    assert bp1_sigs[0].suppressed is True


# ─── AllocationEngine — persona target ───────────────────────────────────────

def test_allocation_engine_uses_conservative_debt_target():
    """Conservative persona has debt_mid_target ~60%, not the hardcoded 20%."""
    # Portfolio with very low debt (5%)
    mf_h = [
        _mf_holding("Parag Parikh Flexi Cap", 900_000, category="Flexi Cap"),
        {**_mf_holding("HDFC Corp Bond", 50_000, category="Corporate Bond"), "asset_type": "debt"},
    ]
    ctx = _base_ctx(
        risk_profile="Conservative", risk_score=75.0,
        total_rs=950_000,
        mf_holdings=mf_h,
        portfolio_intelligence={
            "asset_allocation": {"equity_pct": 94.7, "debt_pct": 5.3},
            "mf_investments": [
                _mf_investment("Flexi Cap", 900_000, "Flexi Cap"),
            ],
        },
    )
    engine = AllocationEngine()
    signals = engine.generate(ctx)
    add_sigs = [s for s in signals if s.action_type == "ADD"]
    assert add_sigs, "Conservative with 5% debt should trigger ADD debt signal"
    # Suggested amount should be large (closing ~55% gap on ₹950k portfolio)
    assert add_sigs[0].amount_rs > 100_000, (
        f"Expected large ADD amount for Conservative debt gap, got {add_sigs[0].amount_rs}"
    )


# ─── Signal contract: all engines populate severity + execution_path ─────────

def test_all_signals_have_severity_and_execution_path():
    """Every signal from any engine must have valid severity + execution_path."""
    from services.recommendation_engine.orchestrator import ENGINE_REGISTRY, build_context

    mf_h = [
        _mf_holding("Fund A", 300_000, category="Large Cap"),
        _mf_holding("Fund B", 200_000, category="Flexi Cap"),
    ]
    ctx = build_context(
        user_id="test_user",
        risk_profile="Moderate",
        total_value_rs=500_000,
        holdings=mf_h,
        mf_holdings=mf_h,
        stock_holdings=[],
        portfolio_intelligence={
            "asset_allocation": {"equity_pct": 100.0, "debt_pct": 0.0},
            "mf_investments": [
                _mf_investment("Fund A", 300_000, "Large Cap", "HDFC"),
                _mf_investment("Fund B", 200_000, "Flexi Cap", "ICICI"),
            ],
        },
        exit_candidates=[],
        v3_scores={},
        rules_cfg=_BASE_RULES_CFG,
        signals=[],
        risk_score_numeric=50.0,
        goal_evaluations=[_goal_eval("at_risk", 60.0, 300_000)],
    )

    valid_severities = {"aligned", "minor", "mismatch", "severe"}
    valid_paths = {"redirect", "harvest", "stagger", "sell-now"}

    for engine in ENGINE_REGISTRY:
        sigs = engine.generate(ctx)
        for sig in sigs:
            assert sig.severity in valid_severities, (
                f"{engine.engine_name} emitted severity={sig.severity!r} not in {valid_severities}"
            )
            assert sig.execution_path in valid_paths, (
                f"{engine.engine_name} emitted execution_path={sig.execution_path!r} not in {valid_paths}"
            )
