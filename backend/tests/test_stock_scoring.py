"""Unit tests for V3 Stock Scoring Engine.

Tests the refined scoring framework:
  - Quality: ROE + D/E + EPS Growth + Promoter + Market-cap + Earnings consistency
  - Health: Revenue growth + Profit margin trend + Debt trend + Earnings surprise
           + Volatility + Dividend
  - Exit: PE overvaluation + Earnings decline + Quality deterioration + Debt spike
         + Liquidity + Tax
  - Add: Sector gap + Low overlap + Relative valuation + Quality + Momentum + Dividend

Default weights are from user-approved Feb 2026 V3 framework.
"""
from __future__ import annotations

import pytest

from services import stock_scoring as ss


# ── Band normalisers ──────────────────────────────────────────────────
@pytest.mark.parametrize("roe,expected", [
    (None, 50.0),
    (5, 0), (10, 0), (22, 100), (30, 100), (16, pytest.approx(50, abs=1)),
])
def test_norm_roe(roe, expected):
    out = ss.norm_roe(roe)
    if isinstance(expected, float) and expected == pytest.approx(0, abs=0.5):
        assert out == pytest.approx(expected, abs=0.5)
    else:
        assert out == expected


def test_norm_debt_to_equity_lower_better():
    assert ss.norm_debt_to_equity(0.2) == 100.0
    assert ss.norm_debt_to_equity(1.5) == 0.0
    assert ss.norm_debt_to_equity(0.9) == pytest.approx(50, abs=1)


def test_norm_eps_growth():
    assert ss.norm_eps_growth(25) == 100.0
    assert ss.norm_eps_growth(5) == 0.0
    assert ss.norm_eps_growth(None) == 50.0


def test_norm_promoter_holding():
    assert ss.norm_promoter_holding(70) == 100.0
    assert ss.norm_promoter_holding(30) == 0.0


def test_norm_market_cap_stability():
    assert ss.norm_market_cap_stability("large") == 90.0
    assert ss.norm_market_cap_stability("mid") == 60.0
    assert ss.norm_market_cap_stability("small") == 40.0
    assert ss.norm_market_cap_stability(None) == 50.0
    assert ss.norm_market_cap_stability("unknown") == 50.0


def test_norm_volatility_lower_better():
    assert ss.norm_volatility(10) == 100.0
    assert ss.norm_volatility(45) == 0.0


def test_norm_dividend_yield_not_penalising_growth():
    assert ss.norm_dividend_yield(0) == 40.0
    assert ss.norm_dividend_yield(4) == 100.0


def test_norm_earnings_decline_flag():
    assert ss.norm_earnings_decline(True) == 100.0
    assert ss.norm_earnings_decline(False) == 0.0


def test_norm_debt_spike_flag():
    assert ss.norm_debt_spike(True) == 100.0
    assert ss.norm_debt_spike(False) == 0.0


def test_norm_low_overlap():
    assert ss.norm_low_overlap(0) == 100.0
    assert ss.norm_low_overlap(100) == 0.0
    assert ss.norm_low_overlap(None) == 70.0


def test_norm_relative_valuation():
    # Cheap vs peer → high Add score
    assert ss.norm_relative_valuation(0.7) == 100.0
    # Expensive vs peer → low Add score
    assert ss.norm_relative_valuation(1.3) == 0.0


# ── Composite scores ──────────────────────────────────────────────────
def test_compute_quality_score_strong_stock():
    prim = {
        "roe_pct": 22, "debt_to_equity": 0.2,
        "eps_growth_3y_cagr_pct": 25,
        "promoter_holding_pct": 65,
        "cap_bucket": "large",
        "earnings_consistency_score": 90,
    }
    out = ss.compute_quality_score(prim)
    assert out["score"] >= 85


def test_compute_quality_score_weak_stock():
    prim = {
        "roe_pct": 5, "debt_to_equity": 2.5,
        "eps_growth_3y_cagr_pct": -5,
        "promoter_holding_pct": 20,
        "cap_bucket": "small",
        "earnings_consistency_score": 20,
    }
    out = ss.compute_quality_score(prim)
    assert out["score"] <= 30


def test_compute_health_score_declining():
    prim = {
        "revenue_growth_3y_cagr_pct": -5,
        "profit_margin_trend_pct": -8,
        "debt_trend_pct": 30,
        "earnings_surprise_pct": -15,
        "volatility_1y_pct": 50,
        "dividend_yield_pct": 0,
    }
    out = ss.compute_health_score(prim)
    assert out["score"] <= 30


def test_compute_exit_score_danger_zone():
    prim = {
        "pe_overvaluation_pct": 60,
        "earnings_decline_flag": True,
        "debt_spike_flag": True,
        "liquidity_score": 20,
    }
    out = ss.compute_exit_score(
        prim, current_quality=40, prior_quality=75,
        tax_ratio=0.05, is_stcg=True,
    )
    assert out["score"] >= 75


def test_compute_add_score_portfolio_gap():
    prim = {"momentum_score": 70, "dividend_yield_pct": 2.0}
    out = ss.compute_add_score(
        prim, sector_gap_pct=12, portfolio_overlap_pct=5,
        quality_score=75, pe_vs_peer_ratio=0.85,
    )
    assert out["score"] >= 70


# ── Full score_stock bundle ───────────────────────────────────────────
def test_score_stock_returns_all_four_scores():
    prim = {
        "roe_pct": 18, "debt_to_equity": 0.4,
        "eps_growth_3y_cagr_pct": 15,
        "promoter_holding_pct": 55,
        "cap_bucket": "large",
        "earnings_consistency_score": 75,
        "revenue_growth_3y_cagr_pct": 12,
        "profit_margin_trend_pct": 1,
        "debt_trend_pct": -5,
        "earnings_surprise_pct": 3,
        "volatility_1y_pct": 20,
        "dividend_yield_pct": 1.2,
        "pe_overvaluation_pct": 10,
        "earnings_decline_flag": False,
        "debt_spike_flag": False,
        "liquidity_score": 80,
        "momentum_score": 65,
    }
    bundle = ss.score_stock(prim, sector_gap_pct=3, portfolio_overlap_pct=15)
    for k in ("quality_score", "health_score", "exit_score", "add_score"):
        assert bundle[k] is not None
        assert 0 <= bundle[k] <= 100
    assert bundle["recommendation"]["action"] in ("BUY", "HOLD", "TRIM", "EXIT", "REVIEW")
    assert bundle["engine_version"] == "v3.stock.1"


# ── Recommendation logic ───────────────────────────────────────────────
def test_derive_recommendation_exit():
    rec = ss.derive_recommendation(40, 40, 80, 20)
    assert rec["action"] == "EXIT"


def test_derive_recommendation_trim():
    rec = ss.derive_recommendation(60, 60, 65, 30)
    assert rec["action"] == "TRIM"


def test_derive_recommendation_buy():
    rec = ss.derive_recommendation(80, 75, 20, 80)
    assert rec["action"] == "BUY"


def test_derive_recommendation_hold():
    rec = ss.derive_recommendation(75, 70, 30, 50)
    assert rec["action"] == "HOLD"


def test_derive_recommendation_review():
    rec = ss.derive_recommendation(30, 40, 20, 30)
    assert rec["action"] == "REVIEW"


def test_derive_recommendation_missing_data():
    rec = ss.derive_recommendation(None, None, None, None)
    assert rec["action"] == "REVIEW"
    assert "Insufficient" in rec["reason"]


# ── Weights management ─────────────────────────────────────────────────
def test_default_weights_quality_sums_to_100():
    q = ss.DEFAULT_STOCK_WEIGHTS["quality"]
    total = sum(q.values())
    assert total == 100, f"quality sums to {total}, expected 100"


def test_default_weights_exit_sums_to_100():
    e = ss.DEFAULT_STOCK_WEIGHTS["exit"]
    assert sum(e.values()) == 100


def test_default_weights_add_sums_to_100():
    a = ss.DEFAULT_STOCK_WEIGHTS["add"]
    assert sum(a.values()) == 100


def test_set_and_get_weights_roundtrip():
    new = {"roe": 40, "debt_to_equity": 15, "eps_growth_3y": 15,
           "promoter_holding": 10, "market_cap_stability": 10,
           "earnings_consistency": 10}
    ss.set_weights("quality", new)
    assert ss.get_weights("quality") == new
    # Reset to defaults for subsequent tests
    ss.set_weights("quality", dict(ss.DEFAULT_STOCK_WEIGHTS["quality"]))


def test_no_overlap_with_mf_weights():
    """Stock weights must NOT leak into MF v3_weights cache."""
    from services import v3_weights as mfw
    mf_cfg = mfw.get_full_config()
    stock_cfg = ss.get_full_config()
    assert set(mf_cfg) != set(stock_cfg)
    assert "quality" not in mf_cfg   # MFs use equity/hybrid/debt top-level
    assert "equity" not in stock_cfg  # Stocks use quality/health/exit/add top-level
