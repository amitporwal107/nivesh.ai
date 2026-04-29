"""V2.5 Decision Engine — Backend test suite.

Covers:
  A. POST /api/plans/generate — schema of new V2.5 fields
  B. /api/plans/active and /api/plans/{id}/save — backwards compatibility
  C. /api/copilot/suggested-prompts — unchanged
  D. Unit tests on scoring primitives (InstrumentScoringEngine)
     - MF_QUALITY_WEIGHTS has 6 components
     - MF_ADD_WEIGHTS has 'need'=0.15
     - score_mf_hold / score_mf_switch / score_mf_exit (guardrails)
     - score_mf_add 'debt' uses dynamic debt_target_pct
  E. Unit test on TaxCalculator.calculate_tax_impact → tax_efficiency_score field
  F. Unit test on ActionPlanManager._find_underperformers — Rule 3 stricter trigger
  G. Unit test on _compute_improvements / _generate_plan_summary (Rule 7 text)
"""
from __future__ import annotations
import os
import sys
import pytest
import requests

# Enable local imports of /app/backend/*
sys.path.insert(0, "/app/backend")

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or "https://wealth-advisor-96.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
SESSION_TOKEN = "370eff71-fda1-46d8-b506-b81b894d634f"
USER_ID = "user_f087c6332922"
HDR = {"Authorization": f"Bearer {SESSION_TOKEN}", "Content-Type": "application/json"}


# ─────────────────────────────────────────────────────────────────────────
# A. /api/plans/generate schema
# ─────────────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def generated_plan():
    r = requests.post(f"{API}/plans/generate", headers=HDR, timeout=120)
    assert r.status_code == 200, f"plan generate failed: {r.status_code} {r.text[:500]}"
    body = r.json()
    assert "plan" in body
    return body["plan"]


def test_plan_metadata_engine_version(generated_plan):
    meta = generated_plan.get("metadata") or {}
    assert meta.get("engine_version") == "v2.5", f"engine_version != v2.5, got {meta.get('engine_version')}"


def test_plan_portfolio_score(generated_plan):
    s = generated_plan.get("portfolio_score")
    assert isinstance(s, (int, float)), f"portfolio_score must be numeric, got {type(s)}"
    assert 0 <= s <= 100, f"portfolio_score out of range: {s}"


def test_plan_portfolio_score_breakdown(generated_plan):
    br = generated_plan.get("portfolio_score_breakdown")
    assert isinstance(br, dict)
    required = {"diversification", "overlap", "amc_concentration", "cost_efficiency", "asset_allocation"}
    missing = required - set(br.keys())
    assert not missing, f"missing portfolio_score_breakdown keys: {missing}"


def test_plan_confidence_score(generated_plan):
    c = generated_plan.get("confidence_score")
    assert isinstance(c, (int, float)), f"confidence_score must be numeric"
    assert 0 <= c <= 100
    cb = generated_plan.get("confidence_breakdown") or {}
    assert cb.get("label") in ("High", "Medium", "Low"), f"bad confidence label: {cb.get('label')}"


def test_plan_summary_is_non_empty_string(generated_plan):
    s = generated_plan.get("plan_summary")
    assert isinstance(s, str) and len(s.strip()) > 0, f"plan_summary empty/invalid: {s!r}"


def test_plan_improvements_shape(generated_plan):
    imp = generated_plan.get("improvements")
    assert isinstance(imp, dict)
    for k in ("overlap_pct", "top_amc_pct", "debt_pct"):
        assert k in imp, f"improvements missing {k}"
        assert "before" in imp[k] and "after" in imp[k]
    assert "annual_cost_saving_rs" in imp


def test_plan_do_nothing_and_degraded_flags(generated_plan):
    assert isinstance(generated_plan.get("do_nothing"), bool)
    assert isinstance(generated_plan.get("degraded"), bool)


def test_plan_hard_cap_6_actions(generated_plan):
    actions = generated_plan.get("actions") or []
    assert len(actions) <= 6, f"actions should be <=6 (hard cap), got {len(actions)}"


# ─────────────────────────────────────────────────────────────────────────
# B. Active + save preserves V2.5 fields
# ─────────────────────────────────────────────────────────────────────────
def test_active_plan_has_v25_fields():
    r = requests.get(f"{API}/plans/active", headers=HDR, timeout=30)
    assert r.status_code == 200
    body = r.json()
    if not body.get("has_plan"):
        pytest.skip("no active plan on record")
    plan = body["plan"]
    assert (plan.get("metadata") or {}).get("engine_version") == "v2.5"
    assert "portfolio_score" in plan
    assert "plan_summary" in plan


def test_save_preserves_v25_fields():
    gen = requests.post(f"{API}/plans/generate", headers=HDR, timeout=120)
    assert gen.status_code == 200
    pid = gen.json()["plan"]["plan_id"]
    sv = requests.post(f"{API}/plans/{pid}/save", headers=HDR, timeout=30)
    assert sv.status_code == 200, sv.text[:500]
    plan = sv.json()["plan"]
    assert (plan.get("metadata") or {}).get("engine_version") == "v2.5"
    assert isinstance(plan.get("portfolio_score"), (int, float))
    assert isinstance(plan.get("confidence_score"), (int, float))
    assert isinstance(plan.get("plan_summary"), str) and plan["plan_summary"]


# ─────────────────────────────────────────────────────────────────────────
# C. Copilot prompts
# ─────────────────────────────────────────────────────────────────────────
def test_copilot_suggested_prompts_ok():
    r = requests.get(f"{API}/copilot/suggested-prompts", headers=HDR, timeout=30)
    assert r.status_code == 200, r.text[:500]
    data = r.json()
    assert "prompts" in data or "suggestions" in data or isinstance(data, (list, dict))


# ─────────────────────────────────────────────────────────────────────────
# D. Scoring primitives — unit tests
# ─────────────────────────────────────────────────────────────────────────
from services.instrument_scoring import (  # noqa: E402
    MF_ADD_WEIGHTS, MF_QUALITY_WEIGHTS, MF_HOLD_WEIGHTS,
    InstrumentScoringEngine, HOLD_THRESHOLD_HIGH,
)


def test_mf_quality_weights_6_components():
    expected = {"performance", "risk_adjusted", "consistency", "drawdown", "expense", "aum_stability"}
    assert set(MF_QUALITY_WEIGHTS.keys()) == expected
    total = sum(MF_QUALITY_WEIGHTS.values())
    assert abs(total - 1.0) < 1e-6, f"MF_QUALITY_WEIGHTS must sum to 1.0, got {total}"


def test_mf_add_weights_have_need_0_15():
    assert "need" in MF_ADD_WEIGHTS and "headroom" not in MF_ADD_WEIGHTS
    assert abs(MF_ADD_WEIGHTS["need"] - 0.15) < 1e-9
    assert abs(sum(MF_ADD_WEIGHTS.values()) - 1.0) < 1e-6


def test_score_mf_hold_fields():
    eng = InstrumentScoringEngine()
    out = eng.score_mf_hold(
        mf_investment={"instrument_id": "MF1", "expense_ratio": 0.5, "aum_cr": 5000},
        portfolio_intelligence={"catalog": {"MF1": {"ratios": {}}}, "pairwise_overlap": []},
        tax_result={"tax_score": 7.0},
    )
    for k in ("hold_score", "strong_hold", "high_quality", "low_overlap", "tax_penalty"):
        assert k in out, f"score_mf_hold missing {k}"
    assert isinstance(out["strong_hold"], bool)


def test_score_mf_switch_fields():
    eng = InstrumentScoringEngine()
    out = eng.score_mf_switch(
        from_fund={"instrument_id": "MF_A", "expense_ratio": 1.8, "aum_cr": 1000, "amount": 500000},
        to_fund={"instrument_id": "MF_B", "expense_ratio": 0.5, "aum_cr": 5000},
        tax_result_from={"tax_liability": 1000, "exit_amount_rs": 500000},
        portfolio_intelligence={"catalog": {"MF_A": {"ratios": {}}, "MF_B": {"ratios": {}}}, "pairwise_overlap": []},
    )
    for k in ("switch_score", "recommended", "quality_improvement", "overlap_reduction",
              "cost_saving", "tax_penalty", "annual_benefit_rs", "tax_cost_rs", "tax_efficiency_score"):
        assert k in out, f"score_mf_switch missing {k}"


def test_score_mf_exit_guardrail_high_quality_low_overlap():
    """Quality ≥ 7.5 (raw quality_score ≤ 2.5) + overlap < 80 ⇒ guardrail_blocked=True, HOLD."""
    eng = InstrumentScoringEngine()
    # Force raw quality low (≤2.5) by supplying very strong ratios and max_overlap below 80.
    pi = {
        "catalog": {"MFX": {"ratios": {
            "ret_1y": 30, "ret_3y": 25, "ret_5y": 20,
            "sharpe": 2.0, "sortino": 2.5, "alpha": 5.0,
            "beta": 0.8, "std_dev": 10, "max_dd": -8,
        }}},
        "pairwise_overlap": [{"a": "MFX", "b": "MFY", "overlap_pct": 40.0}],
    }
    out = eng.score_mf_exit(
        mf_investment={"instrument_id": "MFX", "expense_ratio": 0.3, "aum_cr": 20000, "scheme_name": "X"},
        portfolio_intelligence=pi,
        tax_result={"tax_score": 3.0, "tax_efficiency_score": 2.0},
    )
    assert out["guardrail_blocked"] is True, out
    assert out["action"] == "HOLD"
    assert "BLOCKED_HIGH_QUALITY_FLOOR" in out["reasons"]


def test_score_mf_exit_tax_efficiency_blocks():
    """tax_efficiency_score < 1.0 ⇒ guardrail_blocked=True, HOLD."""
    eng = InstrumentScoringEngine()
    pi = {"catalog": {"MFZ": {"ratios": {}}}, "pairwise_overlap": []}
    out = eng.score_mf_exit(
        mf_investment={"instrument_id": "MFZ", "expense_ratio": 2.0, "aum_cr": 100, "scheme_name": "Z"},
        portfolio_intelligence=pi,
        tax_result={"tax_score": 9.0, "tax_efficiency_score": 0.5},
    )
    assert out["guardrail_blocked"] is True
    assert out["action"] == "HOLD"
    assert "BLOCKED_TAX_EXCEEDS_BENEFIT" in out["reasons"]


def test_score_mf_add_debt_uses_dynamic_target():
    """For a debt fund with portfolio_context.debt_target_pct=30 (low risk) and
    current debt_pct=0, Need score should be maxed (10)."""
    eng = InstrumentScoringEngine()
    fund = {
        "scheme_name": "ABC Debt Fund", "category": "debt short duration",
        "expense_ratio": 0.4, "aum_cr": 3000, "ratios": {"ret_1y": 7, "ret_3y": 6.5},
    }
    ctx = {
        "asset_allocation": {"equity_pct": 90, "debt_pct": 0, "gold_pct": 0},
        "debt_target_pct": 30,
    }
    out = eng.score_mf_add(candidate_fund=fund, portfolio_context=ctx)
    assert "need" in out["score_breakdown"]
    # 30% gap ⇒ need capped at 10
    assert out["score_breakdown"]["need"] == 10.0, out


# ─────────────────────────────────────────────────────────────────────────
# E. Tax efficiency score
# ─────────────────────────────────────────────────────────────────────────
def test_tax_calculator_has_tax_efficiency_score_field():
    from services.tax_calculator import calculate_tax_impact
    from datetime import date, timedelta
    holding = {
        "buy_date": (date.today() - timedelta(days=400)).isoformat(),
        "buy_price": 100.0,
        "current_price": 130.0,
        "quantity": 1000.0,
        "asset_type": "mutual_fund",
        "name": "Test Equity Fund",
    }
    res = calculate_tax_impact(holding, user_slab_rate=30.0)
    assert "tax_efficiency_score" in res, f"tax_calculator missing tax_efficiency_score field. Keys: {list(res.keys())}"


# ─────────────────────────────────────────────────────────────────────────
# F. Rule 3 stricter trigger
# ─────────────────────────────────────────────────────────────────────────
def test_rule3_stricter_underperformer_only_one_condition_fails():
    """A fund with weak quality but strong returns (ret_1y=15) must NOT be flagged."""
    from services.action_plan_manager import ActionPlanManager
    mgr = ActionPlanManager.__new__(ActionPlanManager)  # bypass __init__ deps
    mfs = [{"instrument_id": "MF1", "resolved": True, "scheme_name": "Strong Returns"}]
    pi = {"catalog": {"MF1": {"ratios": {"ret_1y": 15.0, "ret_3y": 14.0}}}}
    cands = [{"instrument_id": "MF1", "score_breakdown": {"quality": 7.0}}]  # weak quality
    out = ActionPlanManager._find_underperformers(mgr, mfs, pi, cands)
    assert out == [], f"Fund with strong returns must NOT be flagged; got {out}"


def test_rule3_flags_when_both_conditions_fail():
    from services.action_plan_manager import ActionPlanManager
    mgr = ActionPlanManager.__new__(ActionPlanManager)
    mfs = [{"instrument_id": "MF1", "resolved": True, "scheme_name": "Weak Everything"}]
    pi = {"catalog": {"MF1": {"ratios": {"ret_1y": 5.0, "ret_3y": 7.0}}}}
    cands = [{"instrument_id": "MF1", "score_breakdown": {"quality": 7.0}}]
    out = ActionPlanManager._find_underperformers(mgr, mfs, pi, cands)
    assert len(out) == 1, f"Fund with weak quality AND weak returns must be flagged; got {out}"


# ─────────────────────────────────────────────────────────────────────────
# G. Rule 5 dynamic debt target
# ─────────────────────────────────────────────────────────────────────────
def test_rule5_debt_targets_by_risk_profile():
    """V2.5 dynamic debt target — config-driven (rules_config.DEFAULTS)."""
    from services import rules_config
    params = rules_config.DEFAULTS["rules"]["rule_5_debt_allocation"]["params"]
    assert params["debt_target_conservative_pct"] == 30.0
    assert params["debt_target_medium_pct"] == 20.0
    assert params["debt_target_aggressive_pct"] == 10.0


# ─────────────────────────────────────────────────────────────────────────
# H. Rule 7 Do-Nothing plan summary text path
# ─────────────────────────────────────────────────────────────────────────
def test_rule7_do_nothing_summary_format():
    from services.action_plan_manager import ActionPlanManager
    mgr = ActionPlanManager.__new__(ActionPlanManager)
    summary = ActionPlanManager._generate_plan_summary(
        mgr,
        actions=[{"type": "HOLD", "priority": "low", "reason_codes": ["PORTFOLIO_HEALTHY"]}],
        portfolio_score=85.0,
        total_tax_impact={},
        portfolio_intelligence={"pairwise_overlap": [], "amc_exposure": {}, "asset_allocation": {}},
        do_nothing=True,
    )
    assert "healthy" in summary.lower()
    assert "85" in summary
