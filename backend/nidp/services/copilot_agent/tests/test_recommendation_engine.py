"""TASK-045 — Recommendation engine tests.

Covers:
  1. Component scorers — technical, fundamental, valuation, risk, portfolio_fit
  2. composite_score()  — weighted total, BUY/HOLD/AVOID signal, DAAS error path
  3. composite_score_batch() — sorted by score, top_n limit
  4. screen_stocks()    — param mapping, DAAS error → ScreenerResult(ok=False)
  5. recommend_mf()     — risk band → category, quality filters, DAAS error path
  6. MfRecommendation.as_llm_context() format
  7. CompositeScore.as_llm_context() format

Run from /app/backend:
    PYTHONPATH=. python3 -m pytest nidp/services/copilot_agent/tests/test_recommendation_engine.py -v
"""
from __future__ import annotations

import asyncio
import sys
import types
from unittest.mock import AsyncMock, patch

import pytest

# ── Stub DAAS client before importing recommendation module ──────────────────
# daas_client has no heavy imports itself, but we want _get and
# get_stock_features_latest to be patchable without live creds.

from services.copilot_tools.recommendation import (
    CompositeScore,
    MfRecommendation,
    ScreenerResult,
    _RISK_BAND_CATEGORIES,
    _WEIGHTS,
    _fundamental_score,
    _portfolio_fit_score,
    _risk_score,
    _technical_score,
    _valuation_score,
    composite_score,
    composite_score_batch,
    recommend_mf,
    screen_stocks,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _feat(**kw) -> dict:
    """Build a minimal feature dict with sane defaults."""
    defaults = {
        "symbol": "TEST", "close": 500.0,
        "rsi14": 45.0, "macd": 0.5, "macd_signal": 0.3,
        "sma50": 480.0, "sma200": 450.0,
        "piotroski_score": 6, "roe_pct": 18.0, "debt_to_equity": 0.4,
        "altman_z_score": 3.5,
        "valuation_signal": "fairly_valued", "pe_ttm": 22.0, "sector_median_pe": 24.0,
        "sector": "Technology",
        "beta": 1.1, "atr_pct": 2.5,
    }
    defaults.update(kw)
    return defaults


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Component scorers
# ═══════════════════════════════════════════════════════════════════════════════

class TestTechnicalScore:
    def test_oversold_rsi_scores_high(self):
        s, reasons = _technical_score(_feat(rsi14=25.0))
        assert s >= 7.0
        assert any("oversold" in r.lower() for r in reasons)

    def test_overbought_rsi_scores_low(self):
        # Pair overbought RSI with bearish MACD and price below SMA so the
        # average isn't pulled up by bullish supporting signals.
        s, _ = _technical_score(_feat(rsi14=78.0, macd=-0.5, macd_signal=0.0,
                                       close=460.0, sma50=490.0))
        assert s < 5.0

    def test_bullish_macd_adds_score(self):
        s_bull, _ = _technical_score(_feat(macd=1.0, macd_signal=0.5, rsi14=50.0))
        s_bear, _ = _technical_score(_feat(macd=-1.0, macd_signal=-0.5, rsi14=50.0))
        assert s_bull > s_bear

    def test_price_above_sma50_favoured(self):
        above, _ = _technical_score(_feat(close=510.0, sma50=490.0, rsi14=50.0))
        below, _ = _technical_score(_feat(close=470.0, sma50=490.0, rsi14=50.0))
        assert above > below

    def test_missing_fields_returns_five(self):
        s, _ = _technical_score({})
        assert s == pytest.approx(5.0)

    def test_score_within_bounds(self):
        for rsi in [20, 35, 50, 65, 80]:
            s, _ = _technical_score(_feat(rsi14=rsi))
            assert 0.0 <= s <= 10.0


class TestFundamentalScore:
    def test_high_piotroski_scores_high(self):
        s, reasons = _fundamental_score(_feat(piotroski_score=9))
        assert s >= 7.0
        assert any("piotroski" in r.lower() or "strong" in r.lower() for r in reasons)

    def test_low_piotroski_scores_low(self):
        # Use None for ROE/D/E/Altman so only Piotroski contributes to the average.
        s, reasons = _fundamental_score(_feat(piotroski_score=1,
                                               roe_pct=None, debt_to_equity=None,
                                               altman_z_score=None))
        assert s < 5.0
        assert any("weak" in r.lower() for r in reasons)

    def test_high_roe_boosts_score(self):
        s_high, r = _fundamental_score(_feat(piotroski_score=None, roe_pct=25.0))
        s_low,  _ = _fundamental_score(_feat(piotroski_score=None, roe_pct=5.0))
        assert s_high > s_low
        assert any("high quality" in reason.lower() for reason in r)

    def test_high_leverage_lowers_score(self):
        s_safe, _ = _fundamental_score(_feat(piotroski_score=None, roe_pct=None, debt_to_equity=0.2))
        s_risky, reasons = _fundamental_score(
            _feat(piotroski_score=None, roe_pct=None, debt_to_equity=2.5))
        assert s_safe > s_risky
        assert any("leverage" in r.lower() or "high" in r.lower() for r in reasons)

    def test_altman_z_distress_zone_flagged(self):
        s, reasons = _fundamental_score(_feat(piotroski_score=None, roe_pct=None,
                                               debt_to_equity=None, altman_z_score=1.0))
        assert any("distress" in r.lower() for r in reasons)

    def test_missing_fields_returns_five(self):
        s, _ = _fundamental_score({})
        assert s == pytest.approx(5.0)


class TestValuationScore:
    def test_undervalued_scores_high(self):
        s, reasons = _valuation_score(_feat(valuation_signal="undervalued"))
        assert s >= 7.0
        assert any("undervalued" in r.lower() for r in reasons)

    def test_overvalued_scores_low(self):
        s, reasons = _valuation_score(_feat(valuation_signal="overvalued"))
        assert s <= 4.0
        assert any("overvalued" in r.lower() for r in reasons)

    def test_discount_to_sector_pe_boosts_score(self):
        # PE 15x vs sector 25x = 40% discount
        s, reasons = _valuation_score(_feat(
            valuation_signal="undervalued", pe_ttm=15.0, sector_median_pe=25.0))
        assert s >= 9.0
        assert any("discount" in r.lower() for r in reasons)

    def test_missing_signal_returns_neutral(self):
        s, _ = _valuation_score({})
        assert s == pytest.approx(5.0)


class TestRiskScore:
    def test_low_beta_suits_conservative(self):
        s_cons, _ = _risk_score(_feat(beta=0.6, atr_pct=None), "conservative")
        s_agg,  _ = _risk_score(_feat(beta=0.6, atr_pct=None), "aggressive")
        assert s_cons > s_agg

    def test_high_beta_suits_aggressive(self):
        s_agg,  _ = _risk_score(_feat(beta=1.8, atr_pct=None), "aggressive")
        s_cons, _ = _risk_score(_feat(beta=1.8, atr_pct=None), "conservative")
        assert s_agg > s_cons

    def test_moderate_prefers_beta_near_one(self):
        s_one,  _ = _risk_score(_feat(beta=1.0, atr_pct=None), "moderate")
        s_high, _ = _risk_score(_feat(beta=1.8, atr_pct=None), "moderate")
        assert s_one > s_high

    def test_score_within_bounds(self):
        for beta in [0.3, 0.7, 1.0, 1.5, 2.0]:
            for profile in ("conservative", "moderate", "aggressive"):
                s, _ = _risk_score(_feat(beta=beta), profile)
                assert 0.0 <= s <= 10.0

    def test_missing_fields_returns_default(self):
        s, _ = _risk_score({}, "moderate")
        assert s == pytest.approx(6.0)


class TestPortfolioFitScore:
    def test_no_portfolio_data_returns_neutral(self):
        s, _ = _portfolio_fit_score(_feat(), None)
        assert s == pytest.approx(6.0)

    def test_adds_new_sector_diversification(self):
        s, reasons = _portfolio_fit_score(
            _feat(sector="Energy"),
            {"sector_weights": {"Technology": 30, "Finance": 20}, "equity_pct": 60},
        )
        assert s >= 8.0
        assert any("diversification" in r.lower() for r in reasons)

    def test_over_concentrated_sector_penalised(self):
        s, reasons = _portfolio_fit_score(
            _feat(sector="Technology"),
            {"sector_weights": {"Technology": 35}, "equity_pct": 60},
        )
        assert s <= 4.0
        assert any("concentration" in r.lower() for r in reasons)

    def test_high_equity_high_beta_penalised(self):
        s, reasons = _portfolio_fit_score(
            _feat(sector=None, beta=1.5),
            {"sector_weights": {}, "equity_pct": 85},
        )
        assert s <= 5.0


# ═══════════════════════════════════════════════════════════════════════════════
# 2. composite_score — weights, signal, DAAS error path
# ═══════════════════════════════════════════════════════════════════════════════

_GOOD_FEAT = _feat(
    rsi14=35.0, macd=1.2, macd_signal=0.8,
    close=520.0, sma50=490.0, sma200=460.0,
    piotroski_score=8, roe_pct=22.0, debt_to_equity=0.25, altman_z_score=4.0,
    valuation_signal="undervalued", pe_ttm=16.0, sector_median_pe=24.0,
    sector="Technology", beta=1.0, atr_pct=2.0,
)

_BAD_FEAT = _feat(
    rsi14=78.0, macd=-0.5, macd_signal=0.0,
    close=420.0, sma50=490.0,
    piotroski_score=2, roe_pct=3.0, debt_to_equity=2.5, altman_z_score=1.0,
    valuation_signal="overvalued", pe_ttm=40.0, sector_median_pe=22.0,
    beta=1.8, atr_pct=6.0,
)


class TestCompositeScore:
    def test_strong_stock_scores_buy(self):
        with patch("services.copilot_tools.recommendation.get_stock_features_latest",
                   new=AsyncMock(return_value=_GOOD_FEAT)):
            result = _run(composite_score("TEST"))
        assert result.ok is True
        assert result.total_score >= 7.0
        assert result.signal == "BUY"

    def test_weak_stock_scores_avoid(self):
        with patch("services.copilot_tools.recommendation.get_stock_features_latest",
                   new=AsyncMock(return_value=_BAD_FEAT)):
            result = _run(composite_score("TEST"))
        assert result.ok is True
        assert result.total_score < 5.0
        assert result.signal == "AVOID"

    def test_mid_range_scores_hold(self):
        mid = _feat(
            rsi14=52.0, macd=0.1, close=500.0, sma50=490.0,
            piotroski_score=5, roe_pct=14.0, debt_to_equity=0.7, altman_z_score=2.5,
            valuation_signal="fairly_valued", beta=1.0,
        )
        with patch("services.copilot_tools.recommendation.get_stock_features_latest",
                   new=AsyncMock(return_value=mid)):
            result = _run(composite_score("TEST"))
        assert result.signal == "HOLD"

    def test_weighted_total_formula(self):
        with patch("services.copilot_tools.recommendation.get_stock_features_latest",
                   new=AsyncMock(return_value=_GOOD_FEAT)):
            result = _run(composite_score("TEST"))
        expected = round(
            result.technical_score     * _WEIGHTS["technical"]
            + result.fundamental_score * _WEIGHTS["fundamental"]
            + result.valuation_score   * _WEIGHTS["valuation"]
            + result.risk_score        * _WEIGHTS["risk"]
            + result.portfolio_fit_score * _WEIGHTS["portfolio_fit"],
            2,
        )
        assert result.total_score == pytest.approx(expected, abs=0.01)

    def test_weights_sum_to_one(self):
        assert sum(_WEIGHTS.values()) == pytest.approx(1.0)

    def test_daas_error_returns_not_ok(self):
        from services.copilot_tools.daas_client import DaasError
        with patch("services.copilot_tools.recommendation.get_stock_features_latest",
                   new=AsyncMock(side_effect=DaasError("timeout"))):
            result = _run(composite_score("FAIL"))
        assert result.ok is False
        assert result.signal == "HOLD"
        assert result.error is not None

    def test_no_data_returns_not_ok(self):
        with patch("services.copilot_tools.recommendation.get_stock_features_latest",
                   new=AsyncMock(return_value=None)):
            result = _run(composite_score("GHOST"))
        assert result.ok is False
        assert result.error == "no_data"

    def test_symbol_uppercased(self):
        with patch("services.copilot_tools.recommendation.get_stock_features_latest",
                   new=AsyncMock(return_value=_GOOD_FEAT)):
            result = _run(composite_score("reliance"))
        assert result.symbol == "RELIANCE"

    def test_as_llm_context_format(self):
        with patch("services.copilot_tools.recommendation.get_stock_features_latest",
                   new=AsyncMock(return_value=_GOOD_FEAT)):
            result = _run(composite_score("TEST"))
        ctx = result.as_llm_context()
        assert "COMPOSITE_SCORE" in ctx
        assert "total=" in ctx
        assert "signal=" in ctx

    def test_all_component_scores_in_range(self):
        with patch("services.copilot_tools.recommendation.get_stock_features_latest",
                   new=AsyncMock(return_value=_GOOD_FEAT)):
            result = _run(composite_score("TEST"))
        for attr in ("technical_score", "fundamental_score", "valuation_score",
                     "risk_score", "portfolio_fit_score", "total_score"):
            val = getattr(result, attr)
            assert 0.0 <= val <= 10.0, f"{attr} = {val} out of [0,10]"

    def test_conservative_risk_profile_lowers_high_beta(self):
        high_beta = _feat(beta=1.8, atr_pct=5.0)
        with patch("services.copilot_tools.recommendation.get_stock_features_latest",
                   new=AsyncMock(return_value=high_beta)):
            cons = _run(composite_score("TEST", user_risk_profile="conservative"))
            agg  = _run(composite_score("TEST", user_risk_profile="aggressive"))
        assert agg.risk_score > cons.risk_score

    def test_portfolio_fit_used_when_sector_concentrated(self):
        port = {"sector_weights": {"Technology": 40}, "equity_pct": 70}
        with patch("services.copilot_tools.recommendation.get_stock_features_latest",
                   new=AsyncMock(return_value=_feat(sector="Technology"))):
            result = _run(composite_score("TEST", portfolio_data=port))
        assert result.portfolio_fit_score <= 4.0


# ═══════════════════════════════════════════════════════════════════════════════
# 3. composite_score_batch
# ═══════════════════════════════════════════════════════════════════════════════

class TestCompositeScoreBatch:
    def test_sorted_by_score_descending(self):
        feats = {
            "AAA": _GOOD_FEAT,
            "BBB": _feat(rsi14=55, piotroski_score=4, valuation_signal="fairly_valued"),
            "CCC": _BAD_FEAT,
        }

        async def _fake_get(symbol):
            return feats.get(symbol)

        with patch("services.copilot_tools.recommendation.get_stock_features_latest",
                   new=AsyncMock(side_effect=_fake_get)):
            results = _run(composite_score_batch(["AAA", "BBB", "CCC"]))

        assert len(results) >= 1
        scores = [r.total_score for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_top_n_limits_output(self):
        async def _fake_get(_):
            return _GOOD_FEAT
        with patch("services.copilot_tools.recommendation.get_stock_features_latest",
                   new=AsyncMock(side_effect=_fake_get)):
            results = _run(composite_score_batch(["A", "B", "C", "D", "E"], top_n=2))
        assert len(results) <= 2

    def test_failed_scores_excluded(self):
        from services.copilot_tools.daas_client import DaasError

        async def _fake_get(symbol):
            if symbol == "BAD":
                raise DaasError("timeout")
            return _GOOD_FEAT

        with patch("services.copilot_tools.recommendation.get_stock_features_latest",
                   new=AsyncMock(side_effect=_fake_get)):
            results = _run(composite_score_batch(["GOOD", "BAD"]))
        symbols = [r.symbol for r in results]
        assert "BAD" not in symbols


# ═══════════════════════════════════════════════════════════════════════════════
# 4. screen_stocks
# ═══════════════════════════════════════════════════════════════════════════════

_SCREENER_ROWS = [
    {"symbol": "RELIANCE", "rsi14": 48.0, "pe_ttm": 24.0, "piotroski_score": 7,
     "valuation_signal": "undervalued", "sector": "Energy"},
    {"symbol": "INFY",     "rsi14": 55.0, "pe_ttm": 28.0, "piotroski_score": 6,
     "valuation_signal": "fairly_valued", "sector": "Technology"},
]

_SCREENER_RESP = {"data": _SCREENER_ROWS, "total_scanned": 450}


class TestScreenStocks:
    def test_returns_rows_on_success(self):
        with patch("services.copilot_tools.recommendation._get",
                   new=AsyncMock(return_value=_SCREENER_RESP)):
            result = _run(screen_stocks(rsi_max=60.0))
        assert result.ok is True
        assert len(result.rows) == 2
        assert result.total_scanned == 450

    def test_filter_summary_reflects_params(self):
        with patch("services.copilot_tools.recommendation._get",
                   new=AsyncMock(return_value=_SCREENER_RESP)):
            result = _run(screen_stocks(rsi_max=60.0, max_pe=30.0, min_piotroski=5))
        assert "RSI<60" in result.filter_summary
        assert "PE<30"  in result.filter_summary
        assert "Piotroski" in result.filter_summary

    def test_daas_error_returns_not_ok(self):
        from services.copilot_tools.daas_client import DaasError
        with patch("services.copilot_tools.recommendation._get",
                   new=AsyncMock(side_effect=DaasError("timeout"))):
            result = _run(screen_stocks())
        assert result.ok is False
        assert result.error is not None

    def test_empty_response_returns_empty_rows(self):
        with patch("services.copilot_tools.recommendation._get",
                   new=AsyncMock(return_value={"data": [], "total_scanned": 0})):
            result = _run(screen_stocks())
        assert result.ok is True
        assert result.rows == []

    def test_valuation_filter_in_params(self):
        captured_params: dict = {}

        async def _fake_get(path, params=None):
            captured_params.update(params or {})
            return _SCREENER_RESP

        with patch("services.copilot_tools.recommendation._get", new=_fake_get):
            _run(screen_stocks(valuation="undervalued", min_roe=15.0))

        assert captured_params.get("valuation_signal") == "undervalued"
        assert captured_params.get("roe_min") == 15.0

    def test_limit_passed_to_daas(self):
        captured_params: dict = {}

        async def _fake_get(path, params=None):
            captured_params.update(params or {})
            return {"data": [], "total_scanned": 0}

        with patch("services.copilot_tools.recommendation._get", new=_fake_get):
            _run(screen_stocks(limit=25))

        assert captured_params.get("limit") == 25


# ═══════════════════════════════════════════════════════════════════════════════
# 5. recommend_mf
# ═══════════════════════════════════════════════════════════════════════════════

_MF_ROWS = [
    {"scheme_code": "100001", "scheme_name": "Axis Liquid Fund",
     "return_1y": 7.2, "return_3y": 6.8, "sharpe_1y": 1.8, "ter": 0.2,
     "composite_rank": 1},
    {"scheme_code": "100002", "scheme_name": "HDFC Liquid Fund",
     "return_1y": 7.0, "return_3y": 6.5, "sharpe_1y": 1.6, "ter": 0.25,
     "composite_rank": 2},
    {"scheme_code": "100003", "scheme_name": "ICICI Liquid Fund",
     "return_1y": 6.8, "return_3y": 6.4, "sharpe_1y": 1.4, "ter": 0.35,
     "composite_rank": 3},
]


class TestRecommendMf:
    def test_conservative_band_maps_to_liquid(self):
        assert _RISK_BAND_CATEGORIES["conservative"][0] == "Liquid"

    def test_moderate_band_maps_to_balanced_advantage(self):
        assert _RISK_BAND_CATEGORIES["moderate"][0] == "Balanced Advantage"

    def test_aggressive_band_maps_to_mid_cap(self):
        assert _RISK_BAND_CATEGORIES["aggressive"][0] == "Mid Cap"

    def test_returns_rows_on_success(self):
        with patch("services.copilot_tools.recommendation._get",
                   new=AsyncMock(return_value={"data": _MF_ROWS})):
            result = _run(recommend_mf(risk_band="conservative"))
        assert result.ok is True
        assert result.risk_band == "conservative"
        assert result.category_used == "Liquid"
        assert len(result.rows) >= 1

    def test_explicit_category_overrides_risk_band(self):
        captured_path: list = []

        async def _fake_get(path, params=None):
            captured_path.append(path)
            return {"data": _MF_ROWS}

        with patch("services.copilot_tools.recommendation._get", new=_fake_get):
            result = _run(recommend_mf(category="Mid Cap", risk_band="conservative"))

        assert "/Mid Cap" in captured_path[0]
        assert result.category_used == "Mid Cap"

    def test_quality_filter_min_sharpe(self):
        with patch("services.copilot_tools.recommendation._get",
                   new=AsyncMock(return_value={"data": _MF_ROWS})):
            result = _run(recommend_mf(risk_band="conservative", min_sharpe=1.7))
        # Only Axis (1.8) passes the sharpe filter
        assert all(float(r["sharpe_1y"]) >= 1.7 for r in result.rows)

    def test_quality_filter_max_ter(self):
        with patch("services.copilot_tools.recommendation._get",
                   new=AsyncMock(return_value={"data": _MF_ROWS})):
            result = _run(recommend_mf(risk_band="conservative", max_ter=0.25))
        assert all(float(r["ter"]) <= 0.25 for r in result.rows)

    def test_quality_filter_min_return_1y(self):
        with patch("services.copilot_tools.recommendation._get",
                   new=AsyncMock(return_value={"data": _MF_ROWS})):
            result = _run(recommend_mf(risk_band="conservative", min_return_1y=7.1))
        assert all(float(r["return_1y"]) >= 7.1 for r in result.rows)

    def test_top_n_limits_results(self):
        with patch("services.copilot_tools.recommendation._get",
                   new=AsyncMock(return_value={"data": _MF_ROWS})):
            result = _run(recommend_mf(risk_band="conservative", top_n=2))
        assert len(result.rows) <= 2

    def test_daas_error_returns_not_ok(self):
        from services.copilot_tools.daas_client import DaasError
        with patch("services.copilot_tools.recommendation._get",
                   new=AsyncMock(side_effect=DaasError("timeout"))):
            result = _run(recommend_mf(risk_band="moderate"))
        assert result.ok is False
        assert result.error is not None

    def test_summary_reflects_risk_band(self):
        with patch("services.copilot_tools.recommendation._get",
                   new=AsyncMock(return_value={"data": _MF_ROWS})):
            result = _run(recommend_mf(risk_band="aggressive"))
        assert "aggressive" in result.summary.lower()

    def test_summary_includes_quality_filters(self):
        with patch("services.copilot_tools.recommendation._get",
                   new=AsyncMock(return_value={"data": _MF_ROWS})):
            result = _run(recommend_mf(risk_band="conservative", min_return_1y=7.0, max_ter=0.3))
        assert "1Y>" in result.summary or "7%" in result.summary

    def test_as_llm_context_format(self):
        with patch("services.copilot_tools.recommendation._get",
                   new=AsyncMock(return_value={"data": _MF_ROWS})):
            result = _run(recommend_mf(risk_band="conservative"))
        ctx = result.as_llm_context()
        assert "MF_RECOMMENDATION" in ctx
        assert "risk_band=conservative" in ctx
        assert "category=Liquid" in ctx

    def test_no_qualifying_funds_returns_ok_empty(self):
        with patch("services.copilot_tools.recommendation._get",
                   new=AsyncMock(return_value={"data": _MF_ROWS})):
            result = _run(recommend_mf(risk_band="conservative", min_sharpe=5.0))
        assert result.ok is True
        assert result.rows == []
        assert "no qualifying" in result.summary.lower()
