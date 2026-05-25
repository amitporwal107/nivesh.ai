"""Unit tests for BaseEngine ABC and context dataclasses."""
import sys
sys.path.insert(0, "/app/backend")

import pytest
from typing import List

from services.recommendation_engine.context import EngineSignal, HoldingWeight, RecommendationContext
from services.recommendation_engine.base_engine import BaseEngine


# ── Minimal concrete engine for testing ──────────────────────────────────────

class _AlwaysOneSignal(BaseEngine):
    engine_name = "TestEngine"

    def generate(self, ctx: RecommendationContext) -> List[EngineSignal]:
        return [EngineSignal(
            signal_id="test::1",
            engine_name=self.engine_name,
            rule_label="TestRule",
            action_type="EXIT",
            instrument_id="isin_001",
            instrument_name="Test Fund",
            amount_rs=100_000,
            base_score=7.5,
            confidence=0.8,
        )]


class _AlwaysRaisesEngine(BaseEngine):
    engine_name = "BrokenEngine"

    def generate(self, ctx: RecommendationContext) -> List[EngineSignal]:
        raise RuntimeError("intentional crash")


class _DisabledEngine(BaseEngine):
    engine_name = "DisabledEngine"
    enabled_config_key = "fake_rule.enabled"

    def generate(self, ctx: RecommendationContext) -> List[EngineSignal]:
        return [EngineSignal(
            signal_id="should_not_appear",
            engine_name=self.engine_name,
            rule_label="R",
            action_type="EXIT",
            instrument_id=None,
            instrument_name="Fund",
            amount_rs=0,
            base_score=5,
            confidence=0.9,
        )]


# ── Fixtures ─────────────────────────────────────────────────────────────────

def _minimal_ctx(rules_cfg=None):
    from services.recommendation_engine.orchestrator import build_context
    return build_context(
        user_id="u1", risk_profile="medium", total_value_rs=1_000_000,
        holdings=[], mf_holdings=[], stock_holdings=[],
        portfolio_intelligence={"mf_investments": [], "pairwise_overlap": [], "catalog": {}},
        exit_candidates=[], v3_scores={},
        rules_cfg=rules_cfg or {"engine_pipeline": {"enabled": True}},
        signals=[],
    )


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_engine_returns_signals():
    ctx = _minimal_ctx()
    engine = _AlwaysOneSignal()
    sigs = engine.safe_generate(ctx)
    assert len(sigs) == 1
    assert sigs[0].signal_id == "test::1"
    assert sigs[0].base_score == 7.5


def test_crashing_engine_returns_empty_list():
    """safe_generate must never raise — crashes produce zero signals."""
    ctx = _minimal_ctx()
    engine = _AlwaysRaisesEngine()
    sigs = engine.safe_generate(ctx)
    assert sigs == []


def test_disabled_engine_returns_empty():
    """engine_pipeline.enabled_config_key=False → no signals emitted."""
    ctx = _minimal_ctx(rules_cfg={
        "engine_pipeline": {"enabled": True},
        "fake_rule": {"enabled": False},
    })
    engine = _DisabledEngine()
    sigs = engine.safe_generate(ctx)
    assert sigs == []


def test_engine_signal_dedup_key_default():
    sig = EngineSignal(
        signal_id="x", engine_name="E", rule_label="R",
        action_type="EXIT", instrument_id="isin_001",
        instrument_name="Fund", amount_rs=50_000,
        base_score=6.0, confidence=0.7,
    )
    assert sig.dedup_key == "EXIT::isin_001"


def test_engine_signal_ar3_priority():
    sig = EngineSignal(
        signal_id="x", engine_name="E", rule_label="R",
        action_type="EXIT", instrument_id=None, instrument_name="Fund",
        amount_rs=50_000, base_score=8.0, confidence=0.9,
        risk_reduction=1.0, diversification_gain=1.0,
        goal_impact=0.5, urgency=0.5, implementation_ease=0.5,
    )
    # AR-3 formula: (0.30×1 + 0.25×1 + 0.20×0.5 + 0.15×0.5 + 0.10×0.5) × 8.0
    expected = (0.30 + 0.25 + 0.10 + 0.075 + 0.05) * 8.0
    assert abs(sig.ar3_priority - expected) < 0.001


def test_holding_weight_fields():
    hw = HoldingWeight(
        instrument_id="isin_001",
        instrument_name="Fund",
        current_rs=250_000,
        weight_pct=25.0,
        allocation_multiplier=1.7,
    )
    assert hw.allocation_multiplier == 1.7
    assert hw.weight_pct == 25.0
