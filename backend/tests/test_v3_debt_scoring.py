"""Unit tests for debt-category primitive normalisers in v3_scoring."""
from __future__ import annotations

from services import v3_scoring as vs


def test_norm_credit_quality_clamps_and_rounds():
    assert vs._norm_credit_quality(None) is None
    assert vs._norm_credit_quality(9.0) == 9.0
    assert vs._norm_credit_quality(15.0) == 10.0
    assert vs._norm_credit_quality(-3.0) == 0.0


def test_norm_yield_vs_cat_delta_mapping():
    # +0.5% premium → +1 point above the 5 baseline = 6.0
    assert vs._norm_yield_vs_cat(7.5, 7.0) == 6.0
    # -0.5% → 4.0
    assert vs._norm_yield_vs_cat(6.5, 7.0) == 4.0
    # large premium clamps at 10
    assert vs._norm_yield_vs_cat(20.0, 7.0) == 10.0
    # missing data → None
    assert vs._norm_yield_vs_cat(None, 7.0) is None
    assert vs._norm_yield_vs_cat(7.0, None) is None


def test_norm_duration_risk_from_modified_duration():
    assert vs._norm_duration_risk(0.0) == 10.0
    assert vs._norm_duration_risk(3.0) == 7.0
    assert vs._norm_duration_risk(10.0) == 0.0
    assert vs._norm_duration_risk(15.0) == 0.0
    assert vs._norm_duration_risk(None) is None


def test_norm_duration_risk_flex_prefers_direct_score():
    """Pre-normalised score should win over raw modified_duration."""
    assert vs._norm_duration_risk_flex(6.0, None) == 6.0
    # Even if both are supplied, direct wins
    assert vs._norm_duration_risk_flex(9.0, 5.0) == 9.0
    # Fallback to derivation when direct is None
    assert vs._norm_duration_risk_flex(None, 3.0) == 7.0
    # Both None
    assert vs._norm_duration_risk_flex(None, None) is None
    # Clamps oversized direct scores
    assert vs._norm_duration_risk_flex(11.5, None) == 10.0


def test_norm_credit_concentration_curve():
    assert vs._norm_credit_concentration(None) is None
    assert vs._norm_credit_concentration(20.0) == 10.0
    assert vs._norm_credit_concentration(80.0) == 0.0
    # Ensure clamping on extreme values
    assert vs._norm_credit_concentration(200.0) == 0.0
    assert vs._norm_credit_concentration(0.0) == 10.0


def test_debt_quality_uses_moneycontrol_primitives():
    """Verify compute_quality_score picks the debt weight profile for a debt
    fund and factors credit_quality_score + duration_risk_score into the
    composite (not modified_duration)."""
    fund = {
        "category": "Debt",
        "sub_category": "Corporate Bond",
        "scheme_name": "HDFC Corporate Bond Direct Growth",
        "credit_quality_score": 9.0,
        "duration_risk_score": 9.0,
        "ytm": None,
        "cat_avg_ytm": None,
        "expense_ratio_direct": 0.36,
        "aum_cr": 31000.0,
        "fund_age_years": 14.0,
        "ret_3y": 7.5,
        "ret_5y": 7.2,
        "sharpe": 0.75,
        "sortino": 1.1,
        "consistency_score": 8.5,
        "max_drawdown_pct": 3.1,
    }
    result = vs.compute_quality_score(fund)
    assert result["category"] == "debt"
    # Quality should be healthy given the strong debt primitives.
    assert result["score"] is not None
    assert result["score"] >= 60
    comps = result.get("components", {})
    # The debt profile must have used our MC primitives.
    assert "credit_quality" in comps or "credit_quality" in result.get("effective_weights", {})
