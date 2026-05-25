"""
Shared test fixtures for recommendation_engine tests.

All fixtures are pure Python — no DB, no external calls.
"""
from __future__ import annotations

import sys
sys.path.insert(0, "/app/backend")

from services.recommendation_engine.orchestrator import build_context

_BASE_RULES_CFG = {
    "engine_pipeline": {
        "enabled": True,
        "arbitration": {"confidence_threshold": 0.4, "tax_suppression_threshold_pct": 15.0},
        "simulation": {"marginal_improvement_threshold_rs": 0},
        "portfolio_impact": {"enabled": True},
    },
    "rule_1_regular_to_direct": {"enabled": True, "params": {"min_switch_score": 1.0}},
    "rule_2_amc_concentration": {"enabled": True, "params": {"threshold_pct": 15.0}},
    "rule_2b_category_concentration": {"enabled": True, "params": {"threshold_pct": 35.0}},
    "rule_3_underperformer_replacement": {"enabled": True, "params": {"max_replacements": 2}},
    "rule_4_different_fund_overlap": {"enabled": True, "params": {"overlap_threshold_pct": 60.0, "max_overlap_exits": 2}},
    "rule_5_debt_allocation": {"enabled": True, "params": {"debt_target_conservative_pct": 30.0, "debt_target_medium_pct": 20.0, "debt_target_aggressive_pct": 10.0}},
    "rule_6_cost_leak_switch": {"enabled": True, "params": {"total_leak_threshold_rs": 10000.0, "max_switches": 3, "min_switch_score": 1.0}},
    "rule_8_same_category_consolidation": {"enabled": True, "params": {"min_funds_to_trigger": 3}},
    "rule_9_cross_category_overlap_replacement": {"enabled": True, "params": {"overlap_threshold_pct": 60.0, "max_replacements": 2}},
    "rule_10_international_fund_gap": {"enabled": True, "params": {"min_intl_gap_pct": 2.0, "min_portfolio_value_rs": 500000}},
    "plan_limits": {"max_actions_per_plan": 6},
}


def _mf_holding(name: str, value: float, category: str = "Flexi Cap", is_direct: bool = True) -> dict:
    """Build a minimal MF holding dict."""
    plan_suffix = "Direct Growth" if is_direct else "Regular Growth"
    full_name = f"{name} - {plan_suffix}"
    return {
        "asset_type": "mutual_fund",
        "name": full_name,
        "quantity": 1000,
        "current_price": value / 1000,
        "buy_price": value / 1100,
        "category": category,
        "instrument_id": f"isin_{name.replace(' ', '_').upper()}",
        "user_id": "test_user",
    }


def _mf_investment(name: str, value: float, category: str = "Flexi Cap", amc: str = "HDFC") -> dict:
    return {
        "scheme_name": f"{amc} {name} - Direct Growth",
        "amount_rs": value,
        "category": category,
        "amc": amc,
        "resolved": True,
        "instrument_id": f"isin_{amc}_{name.replace(' ', '_').upper()}",
        "expense_ratio": 0.5,
    }


def empty_context(**overrides) -> object:
    """Context with no holdings — useful for testing engine skip logic."""
    kwargs = dict(
        user_id="test_u1",
        risk_profile="medium",
        total_value_rs=0,
        holdings=[],
        mf_holdings=[],
        stock_holdings=[],
        portfolio_intelligence={"mf_investments": [], "pairwise_overlap": [], "catalog": {}},
        exit_candidates=[],
        v3_scores={},
        rules_cfg=_BASE_RULES_CFG,
        signals=[],
    )
    kwargs.update(overrides)
    return build_context(**kwargs)


def medium_portfolio_context(**overrides) -> object:
    """
    ₹10L portfolio — 100% equity (no debt, no intl).
    Triggers: AllocationEngine (Rule 5) + InternationalEngine (Rule 10).
    """
    holdings = [
        _mf_holding("Flexi Cap Fund A", 400_000, "Flexi Cap"),
        _mf_holding("Large Cap Fund B", 350_000, "Large Cap"),
        _mf_holding("Mid Cap Fund C", 250_000, "Mid Cap"),
    ]
    mf_investments = [
        _mf_investment("Flexi Cap Fund A", 400_000, "Flexi Cap", "HDFC"),
        _mf_investment("Large Cap Fund B", 350_000, "Large Cap", "ICICI"),
        _mf_investment("Mid Cap Fund C", 250_000, "Mid Cap", "SBI"),
    ]
    kwargs = dict(
        user_id="test_u1",
        risk_profile="medium",
        total_value_rs=1_000_000,
        holdings=holdings,
        mf_holdings=holdings,
        stock_holdings=[],
        portfolio_intelligence={
            "mf_investments": mf_investments,
            "pairwise_overlap": [],
            "catalog": {},
        },
        exit_candidates=[],
        v3_scores={},
        rules_cfg=_BASE_RULES_CFG,
        signals=[],
    )
    kwargs.update(overrides)
    return build_context(**kwargs)
