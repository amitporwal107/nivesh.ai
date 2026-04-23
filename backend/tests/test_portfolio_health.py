"""Unit tests for Portfolio Health & Risk Scoring Engine.

Pure-logic tests — no DB, no network. Covers:
  * HHI / Effective-N concentration math
  * Allocation deviation scoring
  * Overlap inversion
  * Risk: portfolio variance with blanket correlation, band mapping
  * Cost: expense + tax + regular-plan driver
  * Performance: sharpe + alpha + consistency composition
  * Composite Health: 30/25/20/25 weights + driver aggregation
  * Stock market-cap classifier + β/σ heuristic
  * Ideal-allocation horizon cap
"""
from __future__ import annotations

import math

import pytest

from services import portfolio_health as ph
from services import stock_enricher as se


# ── Helpers ─────────────────────────────────────────────────────────────
def _approx(a: float, b: float, tol: float = 0.5) -> bool:
    return abs(a - b) <= tol


# ── 1. HHI + Effective-N ───────────────────────────────────────────────
def test_hhi_single_stock():
    assert ph._hhi([100.0]) == pytest.approx(1.0)


def test_hhi_equal_weights():
    # 10 equal stocks → HHI 0.1, Eff-N 10
    hhi = ph._hhi([1.0] * 10)
    assert hhi == pytest.approx(0.1, abs=0.01)


def test_concentration_reaches_100_with_ideal_N():
    # 40 equal stocks (IDEAL_EFFECTIVE_N) should score 100
    out = ph._diversification_concentration([1.0] * ph.IDEAL_EFFECTIVE_N)
    assert out["score"] == pytest.approx(100.0, abs=0.1)
    assert out["effective_n"] == pytest.approx(40.0, abs=0.1)


def test_concentration_heavy_top_heavy():
    # One stock with 80% weight → very concentrated
    weights = [80.0, 5.0, 5.0, 5.0, 5.0]
    out = ph._diversification_concentration(weights)
    assert out["score"] < 10
    assert out["effective_n"] < 2


def test_concentration_empty_returns_zero():
    out = ph._diversification_concentration([])
    assert out["score"] == 0.0
    assert out["effective_n"] == 0.0


# ── 2. Allocation deviation ────────────────────────────────────────────
def test_allocation_perfect_match_scores_100():
    ideal = {"equity": 60, "debt": 30, "hybrid": 10}
    out = ph._diversification_allocation(ideal, ideal)
    assert out["score"] == 100.0
    assert out["deviation_pp"] == 0.0


def test_allocation_20pp_drift_scores_60():
    actual = {"equity": 70, "debt": 20, "hybrid": 10}
    ideal =  {"equity": 60, "debt": 30, "hybrid": 10}
    out = ph._diversification_allocation(actual, ideal)
    # 10pp drift in equity + 10pp drift in debt = 20pp total
    # 100 - 20*2 = 60
    assert _approx(out["score"], 60.0)
    assert out["deviation_pp"] == pytest.approx(20.0)


# ── 3. Overlap ─────────────────────────────────────────────────────────
def test_overlap_zero_scores_100():
    out = ph._diversification_overlap(0)
    assert out["score"] == 100.0


def test_overlap_full_scores_zero():
    out = ph._diversification_overlap(100)
    assert out["score"] == 0.0


def test_overlap_handles_none():
    out = ph._diversification_overlap(None)
    assert out["score"] == 100.0


# ── 4. Full Diversification component ──────────────────────────────────
def test_compute_diversification_happy_path():
    comp = ph.compute_diversification(
        stock_weights=[1.0] * 40,
        asset_allocation_actual={"equity": 60, "debt": 30, "hybrid": 10},
        asset_allocation_ideal={"equity": 60, "debt": 30, "hybrid": 10},
        portfolio_overlap_pct=0,
    )
    assert comp.name == "Diversification"
    assert comp.weight == 0.30
    # All three perfect → near 100
    assert comp.score >= 99
    assert comp.drivers == []


def test_compute_diversification_drivers_fire():
    # Severely concentrated + allocation off + high overlap
    comp = ph.compute_diversification(
        stock_weights=[80, 5, 5, 5, 5],           # Eff-N ≈ 1.6
        asset_allocation_actual={"equity": 90, "debt": 0, "hybrid": 10},
        asset_allocation_ideal={"equity": 60, "debt": 30, "hybrid": 10},
        portfolio_overlap_pct=45,
    )
    labels = [d["label"] for d in comp.drivers]
    assert any("Too few effective stocks" in l for l in labels)
    assert any("Asset allocation" in l for l in labels)
    assert any("Overlap" in l for l in labels)
    assert comp.score < 60


# ── 5. Risk component ──────────────────────────────────────────────────
def test_risk_equal_weights_mid_vol_score():
    instruments = [
        {"weight_pct": 50, "vol_annual_pct": 18},
        {"weight_pct": 50, "vol_annual_pct": 22},
    ]
    comp = ph.compute_risk(instruments=instruments, portfolio_drawdown_pct=15)
    assert comp.name == "Risk"
    assert 30 <= comp.score <= 70   # moderate risk → moderate score


def test_risk_single_low_vol_high_score():
    instruments = [{"weight_pct": 100, "vol_annual_pct": 5}]
    comp = ph.compute_risk(instruments=instruments, portfolio_drawdown_pct=3)
    assert comp.score > 80


def test_risk_no_holdings():
    comp = ph.compute_risk(instruments=[])
    assert comp.score == 50.0
    assert comp.low_confidence is True


def test_risk_heuristic_fallback_flags_low_confidence():
    instruments = [{"weight_pct": 100, "fallback_vol_annual_pct": 20}]
    comp = ph.compute_risk(instruments=instruments)
    assert comp.low_confidence is True


# ── 6. Cost component ──────────────────────────────────────────────────
def test_cost_cheap_direct_plan():
    comp = ph.compute_cost(
        weighted_expense_ratio_pct=0.4,
        tax_drag_pct=0.3,
        regular_plan_weight_pct=0,
    )
    assert comp.score > 90
    assert comp.drivers == []


def test_cost_expensive_regular_plan_triggers_drivers():
    comp = ph.compute_cost(
        weighted_expense_ratio_pct=1.6,
        tax_drag_pct=3.0,
        regular_plan_weight_pct=40,
    )
    labels = [d["label"] for d in comp.drivers]
    assert any("expense ratio" in l.lower() for l in labels)
    assert any("regular-plan" in l.lower() for l in labels)
    assert any("tax drag" in l.lower() for l in labels)
    assert comp.score < 50


# ── 7. Performance component ───────────────────────────────────────────
def test_performance_strong_returns():
    comp = ph.compute_performance(
        portfolio_return_1y_pct=18, benchmark_return_1y_pct=12,
        sharpe=1.3, consistency_score=85,
    )
    assert comp.score > 70
    assert comp.low_confidence is False


def test_performance_underperforms_benchmark():
    comp = ph.compute_performance(
        portfolio_return_1y_pct=8, benchmark_return_1y_pct=13,
        sharpe=0.4, consistency_score=50,
    )
    labels = [d["label"] for d in comp.drivers]
    assert any("Underperforming benchmark" in l for l in labels)
    assert any("risk-adjusted" in l.lower() for l in labels)


def test_performance_partial_inputs_flag_low_confidence():
    comp = ph.compute_performance(
        portfolio_return_1y_pct=None, benchmark_return_1y_pct=None,
        sharpe=None, consistency_score=None,
    )
    assert comp.low_confidence is True
    assert comp.score == 50.0


# ── 8. Composite Health ────────────────────────────────────────────────
def test_compute_portfolio_health_weights_are_30_25_20_25():
    divers = ph.ComponentScore(name="D", score=100, weight=0.30)
    risk   = ph.ComponentScore(name="R", score=100, weight=0.25)
    cost   = ph.ComponentScore(name="C", score=100, weight=0.20)
    perf   = ph.ComponentScore(name="P", score=100, weight=0.25)
    result = ph.compute_portfolio_health(
        diversification=divers, risk=risk, cost=cost, performance=perf,
    )
    assert result.health_score == 100.0


def test_compute_portfolio_health_worst_case():
    zero = ph.ComponentScore(name="X", score=0, weight=0.25)
    result = ph.compute_portfolio_health(
        diversification=zero, risk=zero, cost=zero, performance=zero,
    )
    assert result.health_score == 0.0


def test_compute_portfolio_health_mid_case():
    # Weighted: 0.30·60 + 0.25·70 + 0.20·80 + 0.25·50 = 18 + 17.5 + 16 + 12.5 = 64
    d = ph.ComponentScore(name="D", score=60, weight=0.30)
    r = ph.ComponentScore(name="R", score=70, weight=0.25)
    c = ph.ComponentScore(name="C", score=80, weight=0.20)
    p = ph.ComponentScore(name="P", score=50, weight=0.25)
    result = ph.compute_portfolio_health(diversification=d, risk=r, cost=c, performance=p)
    assert _approx(result.health_score, 64.0, tol=0.5)
    assert "Fair" in result.summary


def test_compute_portfolio_health_aggregates_drivers():
    d = ph.ComponentScore(name="D", score=30, weight=0.30,
                           drivers=[{"label": "D-driver", "impact_points": 15}])
    r = ph.ComponentScore(name="R", score=30, weight=0.25,
                           drivers=[{"label": "R-driver", "impact_points": 20}])
    c = ph.ComponentScore(name="C", score=30, weight=0.20,
                           drivers=[{"label": "C-driver", "impact_points": 5}])
    p = ph.ComponentScore(name="P", score=30, weight=0.25,
                           drivers=[{"label": "P-driver", "impact_points": 12}])
    result = ph.compute_portfolio_health(diversification=d, risk=r, cost=c, performance=p)
    assert len(result.risk_drivers) <= 5
    # Highest impact first
    assert result.risk_drivers[0]["label"] == "R-driver"
    assert result.risk_drivers[0]["component"] == "R"


def test_compute_portfolio_health_low_confidence_propagates():
    d = ph.ComponentScore(name="D", score=70, weight=0.30)
    r = ph.ComponentScore(name="R", score=70, weight=0.25, low_confidence=True)
    c = ph.ComponentScore(name="C", score=70, weight=0.20)
    p = ph.ComponentScore(name="P", score=70, weight=0.25)
    result = ph.compute_portfolio_health(diversification=d, risk=r, cost=c, performance=p)
    assert result.low_confidence is True


# ── 9. Risk profile + horizon helpers ──────────────────────────────────
@pytest.mark.parametrize("raw,expected", [
    ("Moderate", "moderate"), ("MEDIUM", "moderate"), ("balanced", "moderate"),
    ("aggressive", "aggressive"), ("growth", "aggressive"),
    ("conservative", "conservative"), ("low", "conservative"),
    (None, "moderate"), ("", "moderate"), ("unknown-thing", "moderate"),
])
def test_normalise_risk_profile(raw, expected):
    assert ph._normalise_risk(raw) == expected


def test_ideal_allocation_long_horizon_aggressive():
    out = ph._ideal_allocation("aggressive", horizon_years=15.0)
    assert out["equity"] == 80
    assert out["debt"] == 10


def test_ideal_allocation_short_horizon_caps_equity():
    out = ph._ideal_allocation("aggressive", horizon_years=3.0)
    assert out["equity"] == ph.SHORT_HORIZON_CAP_EQUITY
    # Gap should be moved to debt
    assert out["debt"] == 10 + (80 - ph.SHORT_HORIZON_CAP_EQUITY)


# ── 10. Stock enricher classifier + heuristics ─────────────────────────
def test_classify_market_cap_large():
    assert se.classify_market_cap(100000) == "large"
    assert se.classify_market_cap(67000) == "large"


def test_classify_market_cap_mid():
    assert se.classify_market_cap(30000) == "mid"
    assert se.classify_market_cap(20000) == "mid"


def test_classify_market_cap_small():
    assert se.classify_market_cap(5000) == "small"
    assert se.classify_market_cap(500) == "small"


def test_classify_market_cap_unknown():
    assert se.classify_market_cap(None) == "unknown"
    assert se.classify_market_cap(0) == "unknown"
    assert se.classify_market_cap(-100) == "unknown"


def test_primitives_from_bucket_table():
    assert se.stock_primitives_from_bucket("large") == {"beta": 0.9, "vol_annual_pct": 18.0}
    assert se.stock_primitives_from_bucket("mid")   == {"beta": 1.1, "vol_annual_pct": 22.0}
    assert se.stock_primitives_from_bucket("small") == {"beta": 1.3, "vol_annual_pct": 30.0}
    assert se.stock_primitives_from_bucket("unknown") == {"beta": 1.0, "vol_annual_pct": 20.0}


# ── 11. Concentration combining direct equity + MF look-through ───────
def test_stock_weights_concentration_helper():
    equities = [
        {"quantity": 10, "current_price": 100},   # ₹1,000
        {"quantity": 5,  "current_price": 200},   # ₹1,000
    ]
    mf_top = [{"value_rs": 5000}, {"value_rs": 3000}]
    w = ph._stock_weights_for_concentration(equities, mf_top)
    assert sorted(w) == [1000.0, 1000.0, 3000.0, 5000.0]


def test_stock_weights_skips_zero_value():
    equities = [{"quantity": 0, "current_price": 100}]
    mf_top = [{"value_rs": 0}, {"value_rs": 500}]
    w = ph._stock_weights_for_concentration(equities, mf_top)
    assert w == [500.0]


# ── 12. to_dict shape ──────────────────────────────────────────────────
# ── 12. to_dict shape ──────────────────────────────────────────────────
def test_health_result_to_dict_shape():
    d = ph.ComponentScore(name="Diversification", score=70, weight=0.30)
    r = ph.ComponentScore(name="Risk", score=70, weight=0.25)
    c = ph.ComponentScore(name="Cost", score=70, weight=0.20)
    p = ph.ComponentScore(name="Performance", score=70, weight=0.25)
    result = ph.compute_portfolio_health(diversification=d, risk=r, cost=c, performance=p)
    out = result.to_dict()
    assert set(out) >= {
        "health_score", "grade", "low_confidence", "summary",
        "components", "risk_drivers",
    }
    assert set(out["components"]) == {"diversification", "risk", "cost", "performance"}
    for comp in out["components"].values():
        assert set(comp) >= {"name", "score", "weight", "sub_scores", "drivers"}


# ── 13. Letter grade mapping ───────────────────────────────────────────
@pytest.mark.parametrize("score,expected", [
    (100, "A+"), (92, "A+"), (90, "A+"),
    (89, "A"), (85, "A"), (80, "A"),
    (79, "B+"), (70, "B+"),
    (69, "B"), (60, "B"),
    (59, "C"), (50, "C"),
    (49, "D"), (40, "D"),
    (39, "F"), (0, "F"),
])
def test_score_to_grade(score, expected):
    assert ph.score_to_grade(score) == expected


def test_score_to_grade_none():
    assert ph.score_to_grade(None) == "N/A"


def test_health_result_exposes_grade():
    d = ph.ComponentScore(name="D", score=85, weight=0.30)
    r = ph.ComponentScore(name="R", score=85, weight=0.25)
    c = ph.ComponentScore(name="C", score=85, weight=0.20)
    p = ph.ComponentScore(name="P", score=85, weight=0.25)
    result = ph.compute_portfolio_health(diversification=d, risk=r, cost=c, performance=p)
    out = result.to_dict()
    assert "grade" in out
    assert out["grade"] == "A"


# ── 14. Stock cost proxy + cap→benchmark ───────────────────────────────
def test_stock_cost_proxy_applied():
    # Pure stock portfolio: no MFs, ₹1,00,000 equity → expense = 0.2%
    out = ph._weighted_mf_expense(
        mf_investments=[], v3_by_id={}, equity_value_rs=100000.0,
    )
    assert out["expense_pct"] == pytest.approx(ph.STOCK_COST_PROXY_PCT, abs=0.001)
    assert out["regular_plan_weight_pct"] == 0.0


def test_stock_cost_blends_with_mf_expense():
    # 50% stock + 50% MF (1.0% expense) → weighted 0.6%
    out = ph._weighted_mf_expense(
        mf_investments=[{"scheme_name": "Test Direct", "instrument_id": "x", "value": 100000}],
        v3_by_id={}, equity_value_rs=100000.0,
    )
    # 0.5 * 0.2 + 0.5 * 1.0 = 0.6
    assert out["expense_pct"] == pytest.approx(0.6, abs=0.01)


def test_cap_benchmark_table_values():
    assert ph.CAP_BENCHMARK_RETURN_1Y_PCT["large"] == 12.0
    assert ph.CAP_BENCHMARK_RETURN_1Y_PCT["mid"] == 14.0
    assert ph.CAP_BENCHMARK_RETURN_1Y_PCT["small"] == 16.0
    assert ph.CAP_BENCHMARK_RETURN_1Y_PCT["unknown"] == 12.0

