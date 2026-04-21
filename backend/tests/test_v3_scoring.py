"""V3 Engine Phase 1 — scoring layer + NAV analytics unit tests.

All tests are pure-logic (no DB, no network). They lock the scoring contract
against regressions. Integration with live PG is covered separately by the
API smoke test.
"""
from __future__ import annotations
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.v3_scoring import (  # noqa: E402
    compute_quality_score, compute_health_score, compute_exit_score,
    compute_add_score, compute_portfolio_fit_score, compute_switch_score,
    check_guardrails, ENGINE_VERSION,
    _weighted_composite,
    _norm_returns, _norm_risk_adjusted, _norm_drawdown, _norm_cost,
    _norm_manager_tenure, _norm_turnover, _norm_top10,
)
from services.nav_analytics import (  # noqa: E402
    max_drawdown_from_series, consistency_score_from_series,
    downside_capture_from_series, aum_trend_from_series,
)


# ──────────────────────────── NAV analytics ─────────────────────────────
def test_max_drawdown_simple_peak_trough():
    # Peak at 200, trough at 140 → 30% drawdown
    navs = [100.0] * 30 + [200.0, 180.0, 160.0, 140.0, 160.0, 180.0, 210.0]
    assert max_drawdown_from_series(navs) == 30.0


def test_max_drawdown_none_when_too_short():
    assert max_drawdown_from_series([100.0] * 10) is None
    assert max_drawdown_from_series([]) is None


def test_max_drawdown_zero_for_monotonic():
    # Strictly rising NAVs should have 0 drawdown
    navs = [100.0 + i for i in range(60)]
    assert max_drawdown_from_series(navs) == 0.0


def test_consistency_score_needs_sufficient_data():
    short_series = [(date.today() - timedelta(days=i), 100.0) for i in range(30)]
    assert consistency_score_from_series(short_series, 10.0) is None


def test_consistency_score_perfect_beater():
    # Fund grows 20%/yr consistently, category avg is 10% → beats every window
    today = date.today()
    series = [
        (today - timedelta(days=i), 100.0 * (1.2 ** ((500 - i) / 365)))
        for i in range(500, 0, -1)
    ]
    score = consistency_score_from_series(series, category_avg_return_pct=10.0)
    assert score is not None
    assert score >= 9.0, f"expected ≥9 for perfect beater, got {score}"


def test_consistency_score_none_without_category_avg():
    today = date.today()
    series = [(today - timedelta(days=i), 100.0 + i) for i in range(500, 0, -1)]
    assert consistency_score_from_series(series, None) is None


def test_downside_capture_balanced_fund():
    # Fund loses half as much as benchmark in down months → capture < 100%
    today = date.today()
    fund, bench = [], []
    cum_f, cum_b = 100.0, 100.0
    for m in range(24):
        d = date(today.year - 2 + m // 12, (m % 12) + 1, 1)
        if m % 2 == 0:
            cum_b *= 0.95  # -5% down month
            cum_f *= 0.975  # -2.5% down month (fund captures half)
        else:
            cum_b *= 1.04
            cum_f *= 1.04
        bench.append((d, cum_b))
        fund.append((d, cum_f))
    score = downside_capture_from_series(fund, bench)
    assert score is not None
    # A 50%-capture fund should land clearly under 100
    assert 30 <= score <= 80, f"expected capture 30-80%, got {score}"


def test_aum_trend_flat_scores_near_5():
    # 12 monthly snapshots all at ₹1000 Cr → score should be ~5
    today = date.today()
    series = [(today - timedelta(days=30 * i), 1000.0) for i in range(12, 0, -1)]
    score = aum_trend_from_series(series)
    assert score is not None
    assert 4.0 <= score <= 6.0


def test_aum_trend_strong_growth_scores_high():
    today = date.today()
    series = [(today - timedelta(days=30 * i), 500.0 * (1.03 ** (12 - i))) for i in range(12, 0, -1)]
    score = aum_trend_from_series(series)
    assert score is not None
    assert score >= 8.0


def test_aum_trend_sharp_decline_scores_low():
    today = date.today()
    series = [(today - timedelta(days=30 * i), 1000.0 * (0.97 ** (12 - i))) for i in range(12, 0, -1)]
    score = aum_trend_from_series(series)
    assert score is not None
    assert score <= 4.0


# ───────────────────────────── Normalisers ─────────────────────────────
def test_norm_returns_beats_category():
    # 15% 1y, 18% 3y, 20% 5y vs category 10/11/12 — all strong excess returns
    s = _norm_returns(15, 18, 20, 10, 11, 12)
    assert s is not None and s >= 7.0


def test_norm_returns_none_when_all_missing():
    assert _norm_returns(None, None, None, None, None, None) is None


def test_norm_risk_adjusted_excellent_sharpe():
    s = _norm_risk_adjusted(sharpe=1.5, sortino=1.6)
    assert s is not None and s >= 9.9


def test_norm_drawdown_monotonic():
    # Lower drawdown must score higher
    assert _norm_drawdown(10) > _norm_drawdown(30)
    assert _norm_drawdown(0) == 10.0
    assert _norm_drawdown(50) == 0.0


def test_norm_cost_cheap_direct_plan_scores_high():
    assert _norm_cost(0.5) == 10.0
    assert _norm_cost(1.5) == 5.0
    assert _norm_cost(2.5) == 0.0


def test_norm_manager_tenure_thresholds():
    assert _norm_manager_tenure(7) == 10.0
    assert _norm_manager_tenure(5) == 8.0
    assert _norm_manager_tenure(3) == 6.0
    assert _norm_manager_tenure(0) == 0.0


def test_norm_turnover_peaks_at_60():
    assert _norm_turnover(60) == 10.0
    assert _norm_turnover(0) == 0.0
    # Extreme churn must score near zero (allow small tolerance for the
    # linear decay after the 60% peak)
    assert _norm_turnover(300) <= 0.5
    assert _norm_turnover(400) == 0.0


def test_norm_top10_inverse():
    # Less concentrated → higher score
    assert _norm_top10(30) == 10.0
    assert _norm_top10(70) == 0.0


# ─────────────────────── Weighted composite helper ──────────────────────
def test_weighted_composite_full_data():
    comps = {"a": (8.0, 50), "b": (6.0, 50)}
    out = _weighted_composite(comps)
    # (8*0.5 + 6*0.5) * 10 = 70
    assert out["score"] == 70.0
    assert out["missing_primitives"] == []
    assert out["effective_weights"] == {"a": 50.0, "b": 50.0}


def test_weighted_composite_redistribution():
    comps = {"a": (8.0, 25), "b": (None, 25), "c": (6.0, 50)}
    out = _weighted_composite(comps)
    # 'b' missing → redistribute: a=25/75=33.3%, c=50/75=66.7%
    # score = (8*0.333 + 6*0.667) * 10 = 66.67
    assert 66.0 <= out["score"] <= 67.0
    assert out["missing_primitives"] == ["b"]
    assert abs(out["effective_weights"]["a"] - 33.3) < 0.1
    assert abs(out["effective_weights"]["c"] - 66.7) < 0.1
    # Effective weights must still sum to ~100
    assert abs(sum(out["effective_weights"].values()) - 100.0) < 0.5


def test_weighted_composite_all_missing():
    comps = {"a": (None, 50), "b": (None, 50)}
    out = _weighted_composite(comps)
    assert out["score"] is None
    assert set(out["missing_primitives"]) == {"a", "b"}


# ─────────────────── 5 composite scores — full / partial ─────────────────
def _excellent_fund() -> dict:
    return {
        "ret_1y": 15, "ret_3y": 18, "ret_5y": 20,
        "cat_avg_1y": 10, "cat_avg_3y": 11, "cat_avg_5y": 12,
        "sharpe": 1.4, "sortino": 1.6, "consistency_score": 9.0,
        "max_drawdown_pct": 12.0, "expense_ratio_direct": 0.5, "expense_ratio": 0.5,
        "aum_cr": 10000.0, "fund_age_years": 15,
        "manager_tenure_years": 8.0, "aum_trend_score": 9.0, "turnover_ratio": 55,
        "top10_concentration_pct": 28, "downside_capture_pct": 60, "expense_trend_delta": -0.15,
    }


def _poor_fund() -> dict:
    return {
        "ret_1y": 4, "ret_3y": 6, "ret_5y": 8,
        "cat_avg_1y": 10, "cat_avg_3y": 11, "cat_avg_5y": 12,
        "sharpe": 0.2, "sortino": 0.3, "consistency_score": 2.0,
        "max_drawdown_pct": 40.0, "expense_ratio_direct": 2.4, "expense_ratio": 2.4,
        "aum_cr": 50.0, "fund_age_years": 2,
        "manager_tenure_years": 1.0, "aum_trend_score": 2.0, "turnover_ratio": 300,
        "top10_concentration_pct": 70, "downside_capture_pct": 140, "expense_trend_delta": 0.25,
    }


def test_quality_score_excellent_fund_high():
    out = compute_quality_score(_excellent_fund())
    assert out["score"] >= 85, f"excellent fund should score ≥85, got {out['score']}"
    assert out["missing_primitives"] == []


def test_quality_score_poor_fund_low():
    out = compute_quality_score(_poor_fund())
    assert out["score"] <= 35, f"poor fund should score ≤35, got {out['score']}"


def test_quality_score_missing_nav_analytics_redistributes():
    f = _excellent_fund()
    f["max_drawdown_pct"] = None
    f["consistency_score"] = None
    out = compute_quality_score(f)
    assert out["score"] is not None
    assert "drawdown" in out["missing_primitives"]
    assert "consistency" in out["missing_primitives"]
    # Effective weights must renormalise and sum to ~100
    assert abs(sum(out["effective_weights"].values()) - 100.0) < 0.5


def test_health_score_excellent_fund_high():
    out = compute_health_score(_excellent_fund())
    assert out["score"] >= 85, f"excellent fund should score ≥85, got {out['score']}"


def test_health_score_poor_fund_low():
    out = compute_health_score(_poor_fund())
    assert out["score"] <= 40, f"poor fund should score ≤40, got {out['score']}"


def test_exit_score_high_when_overlap_and_quality_low():
    f = _poor_fund()
    ctx = {"overlap_pct": 85, "tax_liability_rs": 1000, "tax_benefit_rs": 50000,
           "quality_score": 20, "portfolio_fit_score": 40}
    out = compute_exit_score(f, ctx)
    assert out["score"] >= 50, f"should be exit-worthy, got {out['score']}"


def test_exit_score_low_when_fund_is_excellent():
    f = _excellent_fund()
    ctx = {"overlap_pct": 10, "tax_liability_rs": 50000, "tax_benefit_rs": 5000,
           "quality_score": 90, "portfolio_fit_score": 85}
    out = compute_exit_score(f, ctx)
    assert out["score"] <= 40, f"excellent fund w/ low overlap shouldn't exit, got {out['score']}"


def test_add_score_excellent_fund_with_gap():
    f = _excellent_fund()
    ctx = {"gap_fit_0_10": 9, "avg_overlap_pct_with_portfolio": 15,
           "quality_score": 90, "need_score_0_10": 8}
    out = compute_add_score(f, ctx)
    assert out["score"] >= 80


def test_portfolio_fit_balanced_portfolio_high():
    p = {"diversification_0_10": 9, "avg_overlap_pct": 15,
         "top_amc_pct": 18, "avg_expense_ratio": 0.7,
         "asset_alloc_fit_0_10": 9}
    out = compute_portfolio_fit_score(p)
    assert out["score"] >= 80


# ──────────────────────────── Switch formula ────────────────────────────
def test_switch_score_meaningful_upgrade_recommended():
    # +15 pt quality, -30pp overlap, ₹40k cost saving, ₹5k tax → strong switch
    out = compute_switch_score(
        quality_new=80, quality_old=65, overlap_reduction_pct=30,
        cost_saving_rs_per_yr=40000, tax_cost_rs=5000,
    )
    assert out["recommended"] is True
    assert out["score"] > 2.0


def test_switch_score_tax_kills_weak_switch():
    # Marginal benefits destroyed by tax
    out = compute_switch_score(
        quality_new=70, quality_old=68, overlap_reduction_pct=5,
        cost_saving_rs_per_yr=3000, tax_cost_rs=50000,
    )
    assert out["recommended"] is False


# ──────────────────────────── Guardrails ───────────────────────────────
def test_guardrail_high_quality_blocks_exit():
    r = check_guardrails(quality_score=85, health_score=80, overlap_pct=40,
                         tax_liability_rs=None, tax_benefit_rs=None,
                         holding_age_months=24, confidence_score=90)
    assert r.blocked is True
    assert "high_quality_protection" in r.reasons


def test_guardrail_high_overlap_overrides_quality_protection():
    r = check_guardrails(quality_score=85, health_score=80, overlap_pct=85,
                         tax_liability_rs=None, tax_benefit_rs=None,
                         holding_age_months=24, confidence_score=90)
    assert r.blocked is False


def test_guardrail_tax_exceeds_benefit_blocks():
    r = check_guardrails(quality_score=50, health_score=50, overlap_pct=50,
                         tax_liability_rs=80000, tax_benefit_rs=10000,
                         holding_age_months=12, confidence_score=90)
    assert r.blocked is True
    assert "tax_exceeds_benefit" in r.reasons


def test_guardrail_recent_investment_blocks():
    r = check_guardrails(quality_score=50, health_score=50, overlap_pct=50,
                         tax_liability_rs=None, tax_benefit_rs=None,
                         holding_age_months=3, confidence_score=90)
    assert r.blocked is True
    assert "recent_investment_lockout" in r.reasons


def test_guardrail_low_confidence_flags_but_does_not_block():
    r = check_guardrails(quality_score=50, health_score=50, overlap_pct=50,
                         tax_liability_rs=None, tax_benefit_rs=None,
                         holding_age_months=24, confidence_score=40)
    assert r.blocked is False
    assert "low_confidence" in r.reasons
    assert r.confidence_penalty > 0


def test_engine_version_is_v3_phase1():
    assert ENGINE_VERSION == "v3.0-phase1"
