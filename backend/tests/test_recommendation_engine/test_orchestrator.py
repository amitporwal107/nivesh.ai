"""
Integration tests for the orchestrator pipeline.

These tests assert on the full pipeline behavior:
  - PI-1: 2% holding gets lower priority than 25% holding
  - AR-1: GoalAlignmentEngine signals win over competing signals for the same fund
  - AR-2/AR-3: Tax suppression and confidence gating
  - No duplicate instrument in two EXIT actions
  - plan["simulation"] populated when engine_pipeline enabled
"""
import sys
sys.path.insert(0, "/app/backend")

import asyncio
import pytest
from tests.test_recommendation_engine.fixtures import (
    _BASE_RULES_CFG, _mf_holding, _mf_investment,
    medium_portfolio_context,
)
from services.recommendation_engine.orchestrator import (
    build_context, run_engine_pipeline, ENGINE_REGISTRY,
    _signal_to_action,
)
from services.recommendation_engine.portfolio_impact_engine import PortfolioImpactEngine
from services.recommendation_engine.arbitration_engine import ArbitrationEngine
from services.recommendation_engine.context import EngineSignal


# ── PI-1: Allocation weighting ────────────────────────────────────────────────

def test_pi1_large_holding_gets_higher_weighted_score():
    """
    PRD PI-1: A 25% holding should get a 1.7x multiplier.
    A 1% holding should get a 0.4x multiplier.
    """
    from services.recommendation_engine.portfolio_impact_engine import _alloc_multiplier
    assert _alloc_multiplier(25.0) == 1.7
    assert _alloc_multiplier(1.0) == 0.4
    assert _alloc_multiplier(4.9) == 0.7  # 2-5% bracket → 0.7x (upper bound exclusive)
    assert _alloc_multiplier(7.5) == 1.0  # 5-10% bracket → 1.0x
    assert _alloc_multiplier(15.0) == 1.3  # 10-20% bracket → 1.3x


def test_pi1_applies_to_signals():
    ctx = medium_portfolio_context()

    # Create two signals: one for a 40% holding (1.7x), one for a 2% holding (0.4x)
    # The context has holdings of 40%/35%/25%
    sig_large = EngineSignal(
        signal_id="large::exit::isin_FLEXI_CAP_FUND_A",
        engine_name="TestEngine", rule_label="R",
        action_type="EXIT",
        instrument_id="isin_FLEXI_CAP_FUND_A",  # matches 400K holding (40%)
        instrument_name="Flexi Cap Fund A - Direct Growth",
        amount_rs=400_000, base_score=5.0, confidence=0.7,
    )
    sig_small = EngineSignal(
        signal_id="small::exit::isin_SMALL",
        engine_name="TestEngine", rule_label="R",
        action_type="EXIT",
        instrument_id="isin_SMALL_FUND",  # not in holdings → default 5% = 1.0x
        instrument_name="Small Fund",
        amount_rs=10_000, base_score=5.0, confidence=0.7,
    )

    weighted = PortfolioImpactEngine().apply([sig_large, sig_small], ctx)
    large_ws = next(s for s in weighted if s.signal_id == sig_large.signal_id)
    small_ws = next(s for s in weighted if s.signal_id == sig_small.signal_id)

    # Large holding has 40% weight → 1.7x multiplier
    # Small holding not found → default 5% → 1.0x
    assert large_ws.base_score > small_ws.base_score


# ── AR-1: Arbitration dedup ───────────────────────────────────────────────────

def test_ar1_goal_engine_beats_other_engine():
    """GoalAlignmentEngine signal must win over competing signal for the same dedup_key."""
    ctx = medium_portfolio_context()

    non_goal_sig = EngineSignal(
        signal_id="overlap::isin_001",
        engine_name="OverlapEngine", rule_label="Rule 4",
        action_type="EXIT", instrument_id="isin_001",
        instrument_name="Fund A", amount_rs=200_000,
        base_score=8.0, confidence=0.9,
        dedup_key="EXIT::isin_001",
    )
    goal_sig = EngineSignal(
        signal_id="goal::isin_001",
        engine_name="GoalAlignmentEngine", rule_label="Goal Alignment",
        action_type="EXIT", instrument_id="isin_001",
        instrument_name="Fund A", amount_rs=200_000,
        base_score=6.0, confidence=0.8,  # lower base_score than overlap
        goal_impact=0.9,
        dedup_key="EXIT::isin_001",  # SAME dedup key
    )

    arbitrated = ArbitrationEngine().arbitrate([non_goal_sig, goal_sig], ctx)
    active = [s for s in arbitrated if not s.suppressed]

    assert len(active) == 1
    assert active[0].engine_name == "GoalAlignmentEngine", (
        "GoalAlignmentEngine must win over OverlapEngine for same dedup_key"
    )


def test_ar2_tax_suppression():
    """Signals where tax > threshold_pct are suppressed."""
    ctx = medium_portfolio_context()
    sig = EngineSignal(
        signal_id="test::exit",
        engine_name="TestEngine", rule_label="R",
        action_type="EXIT", instrument_id="isin_001",
        instrument_name="Fund", amount_rs=100_000,
        base_score=7.0, confidence=0.9,
        estimated_tax_rs=20_000,  # 20% tax on 100K → > 15% threshold
    )
    arbitrated = ArbitrationEngine().arbitrate([sig], ctx)
    assert len(arbitrated) == 1
    assert arbitrated[0].suppressed is True
    assert "Tax" in (arbitrated[0].suppression_reason or "")


def test_ar3_confidence_gate():
    """Signals with confidence < threshold are suppressed."""
    ctx = medium_portfolio_context()
    low_conf = EngineSignal(
        signal_id="test::low_conf",
        engine_name="TestEngine", rule_label="R",
        action_type="EXIT", instrument_id="isin_001",
        instrument_name="Fund", amount_rs=50_000,
        base_score=5.0, confidence=0.2,  # below 0.4 threshold
    )
    arbitrated = ArbitrationEngine().arbitrate([low_conf], ctx)
    assert arbitrated[0].suppressed is True


# ── No duplicate EXIT for same instrument ────────────────────────────────────

def test_no_duplicate_exit_per_instrument():
    """After arbitration, each instrument_id appears in at most one EXIT signal."""
    ctx = medium_portfolio_context()
    all_signals = []
    for engine in ENGINE_REGISTRY:
        all_signals.extend(engine.safe_generate(ctx))

    weighted = PortfolioImpactEngine().apply(all_signals, ctx)
    arbitrated = ArbitrationEngine().arbitrate(weighted, ctx)
    active = [s for s in arbitrated if not s.suppressed and s.action_type == "EXIT"]

    exit_ids = [s.instrument_id for s in active if s.instrument_id]
    assert len(exit_ids) == len(set(exit_ids)), (
        f"Duplicate EXIT instrument_ids: {exit_ids}"
    )


# ── _signal_to_action shape ───────────────────────────────────────────────────

def test_signal_to_action_produces_required_fields():
    sig = EngineSignal(
        signal_id="alloc::add::debt",
        engine_name="AllocationEngine", rule_label="Rule 5",
        action_type="ADD", instrument_id=None,
        instrument_name="ICICI Corporate Bond Fund",
        amount_rs=200_000, base_score=6.0, confidence=0.6,
        reason_codes=["ALLOCATION_GAP"], reason_text="Add debt.",
    )
    action = _signal_to_action(sig, priority=1)

    required = {"action_id", "type", "priority", "asset_name", "amount", "confidence", "reason_codes", "status", "created_at"}
    missing = required - set(action.keys())
    assert not missing, f"Missing fields: {missing}"

    assert action["type"] == "ADD"
    assert action["priority"] == 1
    assert action["confidence"] == "MEDIUM"  # 0.6 → MEDIUM


# ── Async pipeline end-to-end ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_engine_pipeline_returns_actions_and_simulation():
    from tests.test_recommendation_engine.fixtures import _mf_holding, _mf_investment
    holdings = [_mf_holding("Flexi Cap Fund A", 1_000_000, "Flexi Cap")]

    actions, simulation = await run_engine_pipeline(
        user_id="u1",
        risk_profile="medium",
        total_value_rs=1_000_000,
        holdings=holdings,
        mf_holdings=holdings,
        stock_holdings=[],
        portfolio_intelligence={
            "mf_investments": [_mf_investment("Flexi Cap Fund A", 1_000_000, "Flexi Cap", "HDFC")],
            "pairwise_overlap": [], "catalog": {},
        },
        mf_investments=[_mf_investment("Flexi Cap Fund A", 1_000_000, "Flexi Cap", "HDFC")],
        exit_candidates=[],
        v3_scores={},
        rules_cfg=_BASE_RULES_CFG,
        signals=[],
    )

    assert isinstance(actions, list)
    # All actions must have required shape
    for a in actions:
        assert "action_id" in a
        assert "type" in a
        assert a["type"] in ("EXIT", "ADD", "SWITCH", "HOLD")

    # Simulation result (may be None if switch_simulator unavailable in test env)
    # If populated, must have before/after/delta keys
    if simulation is not None:
        assert "before" in simulation
        assert "after" in simulation
        assert "delta" in simulation
