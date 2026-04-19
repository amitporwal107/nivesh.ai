"""Unit tests for V2 Action Generation Rules (action_plan_manager._apply_action_rules).

Validates the 6 core rules using mocked data (no DB, no network):
  Rule 1: Regular → Direct same-fund consolidation (exit Regular)
  Rule 2: AMC concentration >15% → EXIT until <15%
  Rule 3: Underperformer → replace with same-category top fund
  Rule 4: Different-fund overlap >60% → EXIT fund with higher exit_score
  Rule 5: Debt <10% → ADD debt fund
  Rule 6: Regular→Direct cost leak >₹10K/yr → SWITCH actions

Run with:
    cd /app/backend && python -m pytest tests/test_action_rules.py -v
"""
import asyncio
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.action_plan_manager import ActionPlanManager  # noqa: E402


# ──────────────────────────────────────────────────────────────────────────
# Test fixtures
# ──────────────────────────────────────────────────────────────────────────

def _mk_holding(name, qty=1000, price=100, uid="u1"):
    return {
        "user_id": uid,
        "name": name,
        "quantity": qty,
        "current_price": price,
        "buy_price": price * 0.8,
        "asset_type": "mutual_fund",
    }


def _mk_mf(instrument_id, scheme_name, amount_rs=100000, category="Large Cap",
           expense_ratio=1.2, aum_cr=5000, resolved=True):
    return {
        "instrument_id": instrument_id,
        "scheme_name": scheme_name,
        "amount_rs": amount_rs,
        "category": category,
        "expense_ratio": expense_ratio,
        "aum_cr": aum_cr,
        "resolved": resolved,
    }


def _mk_candidate(instrument_id, scheme_name, exit_score, quality=5.0, amount=100000):
    return {
        "exit_score": exit_score,
        "action": "EXIT" if exit_score >= 7 else "HOLD",
        "priority": "high" if exit_score >= 7 else "medium",
        "confidence": "HIGH" if exit_score >= 7 else "MEDIUM",
        "score_breakdown": {"overlap": 5.0, "tax": 5.0, "cost": 5.0,
                            "quality": quality, "fit": 5.0},
        "reasons": [],
        "instrument_id": instrument_id,
        "instrument_name": scheme_name,
        "instrument_type": "mutual_fund",
        "mf_investment": {
            "instrument_id": instrument_id,
            "scheme_name": scheme_name,
            "amount_rs": amount,
            "expense_ratio": 1.2,
        },
        "holding": {"quantity": 1000, "current_price": amount / 1000,
                    "buy_price": amount / 1000 * 0.8},
        "tax_impact": {"tax_liability": 5000, "post_tax_proceeds": amount - 5000,
                       "capital_gain": 20000, "is_long_term": True,
                       "holding_period_days": 800, "tax_rate": 0.10},
    }


# ──────────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────────

def test_classify_plan_type():
    m = ActionPlanManager()
    assert m._classify_plan_type("HDFC Flexi Cap Fund - Direct Plan - Growth") == "direct"
    assert m._classify_plan_type("HDFC Flexi Cap Fund - Regular - Growth") == "regular"
    assert m._classify_plan_type("HDFC Flexi Cap Fund - Growth") == "regular"
    assert m._classify_plan_type("ICICI Prudential Bluechip - Direct - IDCW") == "direct"


def test_normalize_base_scheme_name():
    m = ActionPlanManager()
    a = m._normalize_base_scheme_name("HDFC Flexi Cap Fund - Direct Plan - Growth")
    b = m._normalize_base_scheme_name("HDFC Flexi Cap Fund - Regular - Growth")
    assert a == b == "hdfc flexi cap fund"


def test_find_regular_direct_pairs():
    m = ActionPlanManager()
    holdings = [
        _mk_holding("HDFC Flexi Cap Fund - Direct Plan - Growth"),
        _mk_holding("HDFC Flexi Cap Fund - Regular - Growth"),
        _mk_holding("Axis Small Cap Fund - Regular Growth"),  # no direct counterpart
    ]
    pairs = m._find_regular_direct_pairs(holdings)
    assert len(pairs) == 1
    assert pairs[0]["base_name"] == "hdfc flexi cap fund"


def test_rule_1_regular_direct_consolidation():
    m = ActionPlanManager()
    holdings = [
        _mk_holding("HDFC Flexi Cap Fund - Direct Plan - Growth", price=150, qty=500),
        _mk_holding("HDFC Flexi Cap Fund - Regular - Growth", price=100, qty=500),
    ]
    mf_investments = [
        _mk_mf("pg-1", "HDFC Flexi Cap Fund - Direct Plan - Growth",
               amount_rs=75000, expense_ratio=0.5),
        _mk_mf("pg-2", "HDFC Flexi Cap Fund - Regular - Growth",
               amount_rs=50000, expense_ratio=1.5),
    ]
    exit_candidates = [
        _mk_candidate("pg-2", "HDFC Flexi Cap Fund - Regular - Growth",
                      exit_score=6.0, amount=50000),
    ]
    actions = asyncio.run(m._apply_action_rules(
        mf_holdings=holdings, mf_investments=mf_investments,
        exit_candidates=exit_candidates, holdings=holdings,
        portfolio_intelligence={"mf_investments": mf_investments,
                                "pairwise_overlap": [], "catalog": {}},
        portfolio_context={"total_value": 125000, "mf_count": 2, "stock_count": 0},
        signals=[],
    ))
    # At least one action exits the REGULAR plan
    exits = [a for a in actions if a["type"] == "EXIT"]
    assert exits, "Expected at least one EXIT action"
    assert any("Regular" in a["asset_name"] for a in exits), \
        f"Expected Regular plan to be exited; got {[a['asset_name'] for a in exits]}"
    assert any("REGULAR_DIRECT_DUPLICATE" in (a.get("reason_codes") or []) for a in exits)


def test_rule_6_cost_leak_switch():
    m = ActionPlanManager()
    # 3 Regular funds without Direct counterparts → each with big expense ratio
    holdings = [
        _mk_holding("Axis Bluechip Fund - Regular Growth", qty=5000, price=100),  # ₹5L value
        _mk_holding("SBI Focused Equity - Regular Growth", qty=4000, price=100),  # ₹4L
    ]
    mf_investments = [
        _mk_mf("pg-a", "Axis Bluechip Fund - Regular Growth",
               amount_rs=500000, expense_ratio=2.0),  # 2% Regular
        _mk_mf("pg-b", "SBI Focused Equity - Regular Growth",
               amount_rs=400000, expense_ratio=1.8),
    ]
    exit_candidates = []  # no scored candidates
    actions = asyncio.run(m._apply_action_rules(
        mf_holdings=holdings, mf_investments=mf_investments,
        exit_candidates=exit_candidates, holdings=holdings,
        portfolio_intelligence={"mf_investments": mf_investments,
                                "pairwise_overlap": [], "catalog": {}},
        portfolio_context={"total_value": 900000, "mf_count": 2, "stock_count": 0},
        signals=[],
    ))
    switch_actions = [a for a in actions if "COST_LEAK_SWITCH_TO_DIRECT" in (a.get("reason_codes") or [])]
    # 500000 * (2.0-1.3)/100 = ₹3500; 400000 * (1.8-1.1)/100 = ₹2800 → total ₹6300 → NOT > 10k
    # Adjust test: make expenses higher
    # Actually the function uses 0.7% default gap → 500000*0.7/100 = ₹3500 + 400000*0.7/100 = ₹2800 = ₹6300 < 10k
    # So this should NOT trigger. Let's verify.
    assert len(switch_actions) == 0


def test_rule_6_cost_leak_triggers_when_large():
    m = ActionPlanManager()
    holdings = [
        _mk_holding("ABC Bluechip - Regular Growth", qty=20000, price=100),  # ₹20L
    ]
    mf_investments = [
        _mk_mf("pg-a", "ABC Bluechip - Regular Growth",
               amount_rs=2000000, expense_ratio=2.0),
    ]
    actions = asyncio.run(m._apply_action_rules(
        mf_holdings=holdings, mf_investments=mf_investments,
        exit_candidates=[], holdings=holdings,
        portfolio_intelligence={"mf_investments": mf_investments,
                                "pairwise_overlap": [], "catalog": {}},
        portfolio_context={"total_value": 2000000, "mf_count": 1, "stock_count": 0},
        signals=[],
    ))
    # 2000000 * 0.7/100 = ₹14,000 > ₹10,000 threshold
    switch_actions = [a for a in actions if "COST_LEAK_SWITCH_TO_DIRECT" in (a.get("reason_codes") or [])]
    assert len(switch_actions) == 1
    assert "saves" in switch_actions[0]["reason_text"].lower()


def test_rule_2_amc_concentration():
    m = ActionPlanManager()
    # Portfolio: 3 HDFC funds (each 5% = 15% combined actually 30%)
    # + Axis 20%, Kotak 20%, SBI 20%, Nippon 10% (all under 15% threshold)
    holdings = [
        _mk_holding("HDFC Small Cap - Direct Growth", qty=1000, price=100),       # 10%
        _mk_holding("HDFC Flexi Cap - Direct Growth", qty=1000, price=100),       # 10%
        _mk_holding("HDFC Balanced Advantage - Direct Growth", qty=1000, price=100),  # 10%
        _mk_holding("Axis Midcap Fund - Direct Growth", qty=1400, price=100),     # 14%
        _mk_holding("Kotak Flexi Cap - Direct Growth", qty=1400, price=100),      # 14%
        _mk_holding("SBI Large Cap - Direct Growth", qty=1400, price=100),        # 14%
        _mk_holding("Nippon Smallcap - Direct Growth", qty=1400, price=100),      # 14%
        _mk_holding("Mirae Large Cap - Direct Growth", qty=1400, price=100),      # 14%
    ]
    mf_investments = [
        _mk_mf("pg-1", "HDFC Small Cap - Direct Growth", amount_rs=100000),
        _mk_mf("pg-2", "HDFC Flexi Cap - Direct Growth", amount_rs=100000),
        _mk_mf("pg-3", "HDFC Balanced Advantage - Direct Growth", amount_rs=100000),
        _mk_mf("pg-4", "Axis Midcap Fund - Direct Growth", amount_rs=140000),
        _mk_mf("pg-5", "Kotak Flexi Cap - Direct Growth", amount_rs=140000),
        _mk_mf("pg-6", "SBI Large Cap - Direct Growth", amount_rs=140000),
        _mk_mf("pg-7", "Nippon Smallcap - Direct Growth", amount_rs=140000),
        _mk_mf("pg-8", "Mirae Large Cap - Direct Growth", amount_rs=140000),
    ]
    exit_candidates = [
        _mk_candidate("pg-1", "HDFC Small Cap - Direct Growth", exit_score=8.5, amount=100000),
        _mk_candidate("pg-2", "HDFC Flexi Cap - Direct Growth", exit_score=6.0, amount=100000),
        _mk_candidate("pg-3", "HDFC Balanced Advantage - Direct Growth", exit_score=5.0, amount=100000),
    ]
    actions = asyncio.run(m._apply_action_rules(
        mf_holdings=holdings, mf_investments=mf_investments,
        exit_candidates=exit_candidates, holdings=holdings,
        portfolio_intelligence={"mf_investments": mf_investments,
                                "pairwise_overlap": [], "catalog": {}},
        portfolio_context={"total_value": 1000000, "mf_count": 8, "stock_count": 0},
        signals=[],
    ))
    amc_actions = [a for a in actions if "AMC_CONCENTRATION_EXIT" in (a.get("reason_codes") or [])]
    # Only HDFC is over-concentrated (30%) — Rule 2 should exit HDFC highest exit_score fund
    assert len(amc_actions) >= 1
    # Highest exit_score HDFC = Small Cap (8.5)
    assert "HDFC Small Cap" in amc_actions[0]["asset_name"], \
        f"Expected HDFC Small Cap first; got {amc_actions[0]['asset_name']}"


def test_rule_4_different_fund_overlap():
    m = ActionPlanManager()
    # 8 holdings, each 12.5% → no AMC over 15%, preventing Rule 2 from interfering
    holdings = [
        _mk_holding("Axis Large Cap - Direct Growth", qty=1250, price=100),
        _mk_holding("Kotak Bluechip - Direct Growth", qty=1250, price=100),
        _mk_holding("Nippon Focused - Direct Growth", qty=1250, price=100),
        _mk_holding("SBI Multi Cap - Direct Growth", qty=1250, price=100),
        _mk_holding("UTI Flexi - Direct Growth", qty=1250, price=100),
        _mk_holding("Mirae Large Cap - Direct Growth", qty=1250, price=100),
        _mk_holding("DSP Midcap - Direct Growth", qty=1250, price=100),
        _mk_holding("Tata Large Cap - Direct Growth", qty=1250, price=100),
    ]
    mf_investments = [
        _mk_mf("pg-A", "Axis Large Cap - Direct Growth", amount_rs=125000),
        _mk_mf("pg-K", "Kotak Bluechip - Direct Growth", amount_rs=125000),
        _mk_mf("pg-N", "Nippon Focused - Direct Growth", amount_rs=125000),
        _mk_mf("pg-S", "SBI Multi Cap - Direct Growth", amount_rs=125000),
        _mk_mf("pg-U", "UTI Flexi - Direct Growth", amount_rs=125000),
        _mk_mf("pg-M", "Mirae Large Cap - Direct Growth", amount_rs=125000),
        _mk_mf("pg-D", "DSP Midcap - Direct Growth", amount_rs=125000),
        _mk_mf("pg-T", "Tata Large Cap - Direct Growth", amount_rs=125000),
    ]
    exit_candidates = [
        _mk_candidate("pg-A", "Axis Large Cap - Direct Growth", exit_score=6.0),
        _mk_candidate("pg-K", "Kotak Bluechip - Direct Growth", exit_score=8.0),  # higher
    ]
    portfolio_intel = {
        "mf_investments": mf_investments,
        "pairwise_overlap": [
            {"a": "pg-A", "b": "pg-K",
             "a_name": "Axis Large Cap - Direct Growth",
             "b_name": "Kotak Bluechip - Direct Growth",
             "overlap_pct": 75.0, "shared_count": 40}
        ],
        "catalog": {},
    }
    actions = asyncio.run(m._apply_action_rules(
        mf_holdings=holdings, mf_investments=mf_investments,
        exit_candidates=exit_candidates, holdings=holdings,
        portfolio_intelligence=portfolio_intel,
        portfolio_context={"total_value": 1000000, "mf_count": 8, "stock_count": 0},
        signals=[],
    ))
    overlap_actions = [a for a in actions if "OVERLAP_CONSOLIDATION" in (a.get("reason_codes") or [])]
    assert len(overlap_actions) >= 1
    # Should exit Kotak (higher exit_score = 8.0)
    assert "Kotak Bluechip" in overlap_actions[0]["asset_name"]


def test_rule_5_debt_gap_triggers_add():
    m = ActionPlanManager()
    holdings = [_mk_holding("Equity Fund", qty=10000, price=100)]  # 100% equity
    actions = asyncio.run(m._apply_action_rules(
        mf_holdings=holdings,
        mf_investments=[_mk_mf("pg-1", "Equity Fund", amount_rs=1000000)],
        exit_candidates=[],
        holdings=holdings,
        portfolio_intelligence={"mf_investments": [], "pairwise_overlap": [], "catalog": {}},
        portfolio_context={"total_value": 1000000, "mf_count": 1, "stock_count": 0},
        signals=[],
    ))
    add_actions = [a for a in actions if a["type"] == "ADD"]
    assert len(add_actions) >= 1
    assert "debt" in add_actions[0]["reason_text"].lower()


def test_rule_3_underperformer_replacement():
    m = ActionPlanManager()
    # Add multiple AMCs so no single one exceeds 15%
    holdings = [
        _mk_holding("Franklin India Small Cap Fund - Regular Growth", qty=1000, price=100),
        _mk_holding("Kotak Midcap - Direct Growth", qty=1400, price=100),
        _mk_holding("Axis Small Cap - Direct Growth", qty=1400, price=100),
        _mk_holding("Nippon Large Cap - Direct Growth", qty=1400, price=100),
        _mk_holding("SBI Multi Cap - Direct Growth", qty=1400, price=100),
        _mk_holding("UTI Flexi - Direct Growth", qty=1400, price=100),
    ]
    mf_investments = [
        _mk_mf("pg-1", "Franklin India Small Cap Fund - Regular Growth",
               amount_rs=100000, category="Small Cap"),
        _mk_mf("pg-2", "Kotak Midcap - Direct Growth", amount_rs=140000, category="Mid Cap"),
        _mk_mf("pg-3", "Axis Small Cap - Direct Growth", amount_rs=140000, category="Small Cap"),
        _mk_mf("pg-4", "Nippon Large Cap - Direct Growth", amount_rs=140000, category="Large Cap"),
        _mk_mf("pg-5", "SBI Multi Cap - Direct Growth", amount_rs=140000, category="Flexi Cap"),
        _mk_mf("pg-6", "UTI Flexi - Direct Growth", amount_rs=140000, category="Flexi Cap"),
    ]
    # Underperformer: quality_score=8.0 (weak) — Franklin
    exit_candidates = [
        _mk_candidate("pg-1", "Franklin India Small Cap Fund - Regular Growth",
                      exit_score=7.5, quality=8.0, amount=100000),
    ]
    portfolio_intel = {
        "mf_investments": mf_investments,
        "pairwise_overlap": [],
        "catalog": {"pg-1": {"ratios": {"ret_1y": 5.36}}},
    }
    actions = asyncio.run(m._apply_action_rules(
        mf_holdings=holdings, mf_investments=mf_investments,
        exit_candidates=exit_candidates, holdings=holdings,
        portfolio_intelligence=portfolio_intel,
        portfolio_context={"total_value": 800000, "mf_count": 6, "stock_count": 0},
        signals=[],
    ))
    replacement_exits = [a for a in actions if "UNDERPERFORMER_REPLACEMENT" in (a.get("reason_codes") or [])]
    adds = [a for a in actions if a["type"] == "ADD"]
    assert len(replacement_exits) == 1
    assert "Franklin" in replacement_exits[0]["asset_name"]
    # Expect an ADD action with a same-category (Small Cap) replacement
    small_cap_adds = [a for a in adds if "small cap" in a.get("asset_name", "").lower()]
    assert len(small_cap_adds) >= 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
