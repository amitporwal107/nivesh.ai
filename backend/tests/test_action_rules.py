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
    # Diverse categories so Rule 2b (>35% single-category) does NOT fire and
    # Rule 4 (different-fund overlap) is isolated.
    mf_investments = [
        _mk_mf("pg-A", "Axis Large Cap - Direct Growth", amount_rs=125000, category="Large Cap"),
        _mk_mf("pg-K", "Kotak Bluechip - Direct Growth", amount_rs=125000, category="Large Cap"),
        _mk_mf("pg-N", "Nippon Focused - Direct Growth", amount_rs=125000, category="Focused"),
        _mk_mf("pg-S", "SBI Multi Cap - Direct Growth", amount_rs=125000, category="Multi Cap"),
        _mk_mf("pg-U", "UTI Flexi - Direct Growth", amount_rs=125000, category="Flexi Cap"),
        _mk_mf("pg-M", "Mirae Emerging - Direct Growth", amount_rs=125000, category="Large & Mid Cap"),
        _mk_mf("pg-D", "DSP Midcap - Direct Growth", amount_rs=125000, category="Mid Cap"),
        _mk_mf("pg-T", "Tata Small Cap - Direct Growth", amount_rs=125000, category="Small Cap"),
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


def test_rule_2b_category_concentration_trims_over_35_pct():
    """When a single MF category >35% of corpus, Rule 2b must emit EXIT actions."""
    m = ActionPlanManager()
    # 6 holdings, all Mid Cap = 100% Mid Cap concentration, across different AMCs
    # (each AMC <= ~17% so Rule 2 also triggers on two of them; Rule 2b runs after
    # Rule 2 so it sees whatever remains). We pick 6 AMCs so each is ~16.7% < 15.5
    # guard (AMC rule threshold is 15%). Keep AMCs below 15% by using 7 funds.
    holdings = [
        _mk_holding("Axis Midcap - Direct Growth", qty=1000, price=100),
        _mk_holding("Kotak Midcap - Direct Growth", qty=1000, price=100),
        _mk_holding("Nippon Midcap - Direct Growth", qty=1000, price=100),
        _mk_holding("SBI Midcap - Direct Growth", qty=1000, price=100),
        _mk_holding("UTI Midcap - Direct Growth", qty=1000, price=100),
        _mk_holding("Mirae Midcap - Direct Growth", qty=1000, price=100),
        _mk_holding("DSP Midcap - Direct Growth", qty=1000, price=100),
    ]
    mf_investments = [
        _mk_mf("pg-A", "Axis Midcap - Direct Growth", amount_rs=100000, category="Mid Cap"),
        _mk_mf("pg-K", "Kotak Midcap - Direct Growth", amount_rs=100000, category="Mid Cap"),
        _mk_mf("pg-N", "Nippon Midcap - Direct Growth", amount_rs=100000, category="Mid Cap"),
        _mk_mf("pg-S", "SBI Midcap - Direct Growth", amount_rs=100000, category="Mid Cap"),
        _mk_mf("pg-U", "UTI Midcap - Direct Growth", amount_rs=100000, category="Mid Cap"),
        _mk_mf("pg-M", "Mirae Midcap - Direct Growth", amount_rs=100000, category="Mid Cap"),
        _mk_mf("pg-D", "DSP Midcap - Direct Growth", amount_rs=100000, category="Mid Cap"),
    ]
    # Exit candidate: DSP has the highest exit score
    exit_candidates = [
        _mk_candidate("pg-D", "DSP Midcap - Direct Growth", exit_score=9.0),
        _mk_candidate("pg-A", "Axis Midcap - Direct Growth", exit_score=6.0),
    ]
    portfolio_intel = {
        "mf_investments": mf_investments,
        "pairwise_overlap": [],
        "catalog": {},
    }
    actions = asyncio.run(m._apply_action_rules(
        mf_holdings=holdings, mf_investments=mf_investments,
        exit_candidates=exit_candidates, holdings=holdings,
        portfolio_intelligence=portfolio_intel,
        portfolio_context={"total_value": 700000, "mf_count": 7, "stock_count": 0},
        signals=[],
    ))
    cat_exits = [a for a in actions if "CATEGORY_CONCENTRATION_EXIT" in (a.get("reason_codes") or [])]
    assert len(cat_exits) >= 1, f"Expected Rule 2b to fire; got actions: {[a.get('reason_codes') for a in actions]}"
    # Highest exit_score in category is DSP — first trim target
    assert "DSP Midcap" in cat_exits[0]["asset_name"], (
        f"Expected DSP Midcap first; got {cat_exits[0]['asset_name']}"
    )


def test_rule_2b_skipped_when_category_under_threshold():
    """No CATEGORY_CONCENTRATION_EXIT actions when categories are balanced."""
    m = ActionPlanManager()
    holdings = [
        _mk_holding("Axis Large Cap - Direct Growth", qty=1000, price=100),
        _mk_holding("DSP Midcap - Direct Growth", qty=1000, price=100),
        _mk_holding("Tata Small Cap - Direct Growth", qty=1000, price=100),
        _mk_holding("Nippon Corporate Bond Fund - Direct", qty=1000, price=100),
    ]
    mf_investments = [
        _mk_mf("pg-A", "Axis Large Cap - Direct Growth", amount_rs=100000, category="Large Cap"),
        _mk_mf("pg-D", "DSP Midcap - Direct Growth", amount_rs=100000, category="Mid Cap"),
        _mk_mf("pg-T", "Tata Small Cap - Direct Growth", amount_rs=100000, category="Small Cap"),
        _mk_mf("pg-N", "Nippon Corporate Bond Fund - Direct", amount_rs=100000, category="Corporate Bond"),
    ]
    actions = asyncio.run(m._apply_action_rules(
        mf_holdings=holdings, mf_investments=mf_investments,
        exit_candidates=[], holdings=holdings,
        portfolio_intelligence={"mf_investments": mf_investments, "pairwise_overlap": [], "catalog": {}},
        portfolio_context={"total_value": 400000, "mf_count": 4, "stock_count": 0},
        signals=[],
    ))
    cat_exits = [a for a in actions if "CATEGORY_CONCENTRATION_EXIT" in (a.get("reason_codes") or [])]
    assert len(cat_exits) == 0


def test_rule_2_amc_fires_for_unresolved_funds():
    """Reg: when PG has no record, AMC rule must still fire based on scheme_name.

    Reproduces the nivessh.ai@gmail.com bug: 12 MF holdings all unresolved,
    previous code skipped them with `if not mf.get('resolved'): continue` so
    Rule 2 never ran and only the debt-ADD action was emitted.
    """
    m = ActionPlanManager()
    holdings = [
        _mk_holding("HDFC Mid Cap Fund - Direct - Growth", qty=5725, price=100),
        _mk_holding("HDFC Flexi Cap Fund - Direct", qty=5000, price=100),
        _mk_holding("ICICI Prudential Value Fund - Direct", qty=4200, price=100),
        _mk_holding("Nippon India Large Cap Fund - Direct", qty=2700, price=100),
        _mk_holding("Mirae Asset Emerging Bluechip - Direct", qty=1000, price=100),
    ]
    # Unresolved — no instrument_id, no category (what the scraper returns
    # when PG doesn't have the fund)
    mf_investments = [
        {"instrument_id": None, "scheme_name": h["name"], "amount_rs": h["quantity"] * h["current_price"],
         "category": None, "resolved": False}
        for h in holdings
    ]
    actions = asyncio.run(m._apply_action_rules(
        mf_holdings=holdings, mf_investments=mf_investments,
        exit_candidates=[], holdings=holdings,
        portfolio_intelligence={"mf_investments": mf_investments, "pairwise_overlap": [], "catalog": {}},
        portfolio_context={"total_value": sum(h["quantity"] * h["current_price"] for h in holdings),
                           "mf_count": len(holdings), "stock_count": 0},
        signals=[],
    ))
    amc_exits = [a for a in actions if "AMC_CONCENTRATION_EXIT" in (a.get("reason_codes") or [])]
    # HDFC = 1072500/1862500 = 57.6% — well over 15% threshold → must fire
    assert len(amc_exits) >= 1, f"Expected AMC_CONCENTRATION_EXIT on unresolved funds; got {[a.get('reason_codes') for a in actions]}"
    assert any("HDFC" in a.get("asset_name", "") for a in amc_exits), (
        f"Expected HDFC exit; got {[a.get('asset_name') for a in amc_exits]}"
    )


def test_category_inferred_from_scheme_name():
    """Rule 2b must use _infer_category_from_name when category is None/missing."""
    m = ActionPlanManager()
    # 8 Mid Cap funds across 8 AMCs → each AMC = 12.5% (< 15% threshold, Rule 2
    # stays silent) but category = 100% Mid Cap (> 35% → Rule 2b fires).
    holdings = [
        _mk_holding("Axis Midcap Fund - Direct", qty=1000, price=100),
        _mk_holding("SBI Midcap Fund - Direct", qty=1000, price=100),
        _mk_holding("DSP Midcap Fund - Direct", qty=1000, price=100),
        _mk_holding("Kotak Emerging Equity Fund - Direct", qty=1000, price=100),
        _mk_holding("Tata Midcap Fund - Direct", qty=1000, price=100),
        _mk_holding("UTI Midcap Fund - Direct", qty=1000, price=100),
        _mk_holding("Mirae Midcap Fund - Direct", qty=1000, price=100),
        _mk_holding("Invesco Midcap Fund - Direct", qty=1000, price=100),
    ]
    # First 3 inferrable as Mid Cap (3/4 = 75% > 35% threshold)
    mf_investments = [
        {"instrument_id": None, "scheme_name": h["name"],
         "amount_rs": h["quantity"] * h["current_price"],
         "category": None, "resolved": False}
        for h in holdings
    ]
    actions = asyncio.run(m._apply_action_rules(
        mf_holdings=holdings, mf_investments=mf_investments,
        exit_candidates=[], holdings=holdings,
        portfolio_intelligence={"mf_investments": mf_investments, "pairwise_overlap": [], "catalog": {}},
        portfolio_context={"total_value": 800000, "mf_count": 8, "stock_count": 0},
        signals=[],
    ))
    cat_exits = [a for a in actions if "CATEGORY_CONCENTRATION_EXIT" in (a.get("reason_codes") or [])]
    assert len(cat_exits) >= 1, (
        f"Expected Rule 2b to fire on inferred Mid Cap; got {[a.get('reason_codes') for a in actions]}"
    )


def test_infer_category_helper():
    """Unit test for _infer_category_from_name keyword matcher."""
    m = ActionPlanManager()
    assert m._infer_category_from_name("HDFC Mid Cap Fund") == "Mid Cap"
    assert m._infer_category_from_name("ICICI Large & Mid Cap Fund") == "Large & Mid Cap"
    assert m._infer_category_from_name("Axis Bluechip Fund - Direct") == "Large Cap"
    assert m._infer_category_from_name("Parag Parikh Flexi Cap Fund") == "Flexi Cap"
    assert m._infer_category_from_name("Quant Small Cap Fund") == "Small Cap"
    assert m._infer_category_from_name("Nippon Corporate Bond Fund") == "Corporate Bond"
    assert m._infer_category_from_name("SBI Gold ETF") == "Gold"
    assert m._infer_category_from_name("Random Alpha Fund") is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
