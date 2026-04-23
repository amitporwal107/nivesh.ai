"""Unit tests for Groww Stock Scraper primitive mapping + helpers.

HTTP calls are NOT exercised here — we test pure logic (parsers,
transformers, CAGR math). A separate live smoke test is in
test_groww_stock_scraper_live.py (gated behind GROWW_LIVE=1 env var)."""
from __future__ import annotations

import pytest

from services import groww_stock_scraper as gs


# ── CAGR math ─────────────────────────────────────────────────────────
def test_cagr_basic_doubling():
    # ₹100 → ₹200 over 3y → 25.99%
    assert gs._cagr(100, 200, 3) == pytest.approx(25.992, abs=0.1)


def test_cagr_handles_bad_inputs():
    assert gs._cagr(None, 100, 3) is None
    assert gs._cagr(100, None, 3) is None
    assert gs._cagr(100, 200, 0) is None
    assert gs._cagr(0, 200, 3) is None


def test_yearly_cagr_picks_last_n_years():
    series = {"2020": 100, "2021": 120, "2022": 145, "2023": 175, "2024": 210, "2025": 252}
    # years_back=3 → last 4 items (2022:145 → 2025:252, 3 years)
    # CAGR: (252/145)^(1/3) - 1 = 20.22%
    out = gs._yearly_cagr(series, years_back=3)
    assert out is not None
    assert out == pytest.approx(20.23, abs=0.2)


def test_yearly_cagr_too_few_years():
    assert gs._yearly_cagr({"2024": 100}, years_back=3) is None
    assert gs._yearly_cagr({}, years_back=3) is None


def test_yoy_delta_pct():
    series = {"2023": 100, "2024": 120}
    assert gs._yoy_delta_pct(series) == pytest.approx(20.0)


def test_yoy_delta_pct_negative():
    series = {"2023": 100, "2024": 80}
    assert gs._yoy_delta_pct(series) == pytest.approx(-20.0)


def test_yoy_delta_single_year():
    assert gs._yoy_delta_pct({"2024": 100}) is None


# ── Cap bucket classification ─────────────────────────────────────────
def test_cap_bucket_prefers_groww_type():
    assert gs._cap_bucket(1000, "Large Cap") == "large"
    assert gs._cap_bucket(100, "Mid Cap") == "mid"
    assert gs._cap_bucket(100, "Small Cap") == "small"


def test_cap_bucket_fallback_by_mcap():
    assert gs._cap_bucket(100000, None) == "large"
    assert gs._cap_bucket(30000, None) == "mid"
    assert gs._cap_bucket(5000, None) == "small"


def test_cap_bucket_unknown():
    assert gs._cap_bucket(None, None) == "unknown"


# ── Earnings consistency score ────────────────────────────────────────
def test_earnings_consistency_all_positive():
    profits = {"2021": 100, "2022": 110, "2023": 120, "2024": 130, "2025": 140}
    out = gs._earnings_consistency(profits)
    assert out is not None
    assert out >= 80   # very consistent


def test_earnings_consistency_with_losses():
    profits = {"2021": 100, "2022": -50, "2023": 120, "2024": -30, "2025": 140}
    out = gs._earnings_consistency(profits)
    assert out is not None
    assert out <= 60   # 2 loss years dock the score


def test_earnings_consistency_insufficient_data():
    assert gs._earnings_consistency({"2024": 100, "2025": 120}) is None


# ── Promoter holding sum ──────────────────────────────────────────────
def test_total_promoter_holding():
    shp = {
        "Mar '26": {
            "promoters": {
                "individual": {"percent": 50.0},
                "government": {"percent": 0},
                "corporation": {"percent": 5.5},
            }
        }
    }
    assert gs._total_promoter_holding(shp) == pytest.approx(55.5)


def test_total_promoter_holding_empty():
    assert gs._total_promoter_holding(None) is None
    assert gs._total_promoter_holding({}) is None


# ── Primitive mapping integration ─────────────────────────────────────
def test_map_to_primitives_full_payload():
    # Snippet from a real Groww RELIANCE payload (trimmed)
    raw = {
        "stats": {
            "marketCap": 1844349.19, "peRatio": 18.86, "pbRatio": 2.1,
            "roe": 9.47, "debtToEquity": 0.43, "epsTtm": 72.25,
            "netProfitMargin": 6.66, "divYield": 0.4, "cappedType": "Large Cap",
            "sectorPe": 14.76, "roic": 9.75,
        },
        "shareHoldingPattern": {
            "Mar '26": {
                "promoters": {
                    "individual": {"percent": 50.0},
                    "government": {"percent": 0},
                    "corporation": {"percent": 0},
                }
            }
        },
        "financialStatementV2": {
            "CONSOLIDATED": [
                {"title": "Revenue", "yearly": {"2021": 483251, "2022": 710906,
                                                  "2023": 889569, "2024": 917121, "2025": 982671}},
                {"title": "Profit", "yearly": {"2021": 53739, "2022": 66184,
                                                 "2023": 73670, "2024": 78633, "2025": 80787}},
            ]
        },
        "priceData": {"nse": {"yearHighPrice": 1611.8, "yearLowPrice": 1285.4}},
    }
    prim = gs.map_to_primitives(raw)

    assert prim["pe_ratio"] == 18.86
    assert prim["roe_pct"] == 9.47
    assert prim["debt_to_equity"] == 0.43
    assert prim["promoter_holding_pct"] == 50.0
    assert prim["cap_bucket"] == "large"
    assert prim["market_cap_cr"] == 1844349.19
    assert prim["dividend_yield_pct"] == 0.4
    # PE over sector: 18.86 / 14.76 - 1 = 0.278 → 27.78%
    assert prim["pe_overvaluation_pct"] == pytest.approx(27.78, abs=0.1)
    # Revenue CAGR 2022→2025: 710906→982671, 3y → ~11.4%
    assert prim["revenue_growth_3y_cagr_pct"] is not None
    assert 10 <= prim["revenue_growth_3y_cagr_pct"] <= 15
    # Earnings consistency: 5 positive years, low-moderate CV → strong
    assert prim["earnings_consistency_score"] >= 70
    # No earnings decline (revenue YoY is positive)
    assert prim["earnings_decline_flag"] is False
    # Liquidity: mcap > ₹50,000 Cr → high
    assert prim["liquidity_score"] == 85.0


def test_map_to_primitives_missing_fields_safe():
    raw = {"stats": {}, "shareHoldingPattern": {}, "financialStatementV2": {}}
    prim = gs.map_to_primitives(raw)
    # Everything should be None, no crashes
    assert prim["pe_ratio"] is None
    assert prim["roe_pct"] is None
    assert prim["cap_bucket"] == "unknown"
    assert prim["earnings_decline_flag"] is False


# ── __NEXT_DATA__ extraction ──────────────────────────────────────────
def test_extract_next_data_basic():
    html = '<html><body><script id="__NEXT_DATA__" type="application/json">{"a": 1, "b": "hello"}</script></body></html>'
    out = gs._extract_next_data(html)
    assert out == {"a": 1, "b": "hello"}


def test_extract_next_data_no_match():
    assert gs._extract_next_data("<html>no script</html>") is None
    assert gs._extract_next_data(None) is None


def test_extract_next_data_malformed_json():
    html = '<script id="__NEXT_DATA__">{not valid json}</script>'
    assert gs._extract_next_data(html) is None


# ── End-to-end scoring from primitives ─────────────────────────────────
def test_scraper_output_feeds_scoring_engine():
    """Ensure the mapped primitives produce a scoring bundle with all 4
    composite scores populated."""
    from services import stock_scoring

    raw = {
        "stats": {
            "marketCap": 500000, "peRatio": 25, "roe": 22,
            "debtToEquity": 0.3, "epsTtm": 45, "divYield": 1.2,
            "netProfitMargin": 18, "cappedType": "Large Cap", "sectorPe": 22,
        },
        "shareHoldingPattern": {
            "Mar '26": {"promoters": {"individual": {"percent": 60}}}
        },
        "financialStatementV2": {"CONSOLIDATED": [
            {"title": "Revenue", "yearly": {"2021": 100, "2022": 120,
                                              "2023": 145, "2024": 175, "2025": 210}},
            {"title": "Profit", "yearly": {"2021": 15, "2022": 20,
                                             "2023": 26, "2024": 34, "2025": 42}},
        ]},
        "priceData": {"nse": {"yearHighPrice": 500, "yearLowPrice": 400}},
    }
    prim = gs.map_to_primitives(raw)
    bundle = stock_scoring.score_stock(prim)
    for k in ("quality_score", "health_score", "exit_score", "add_score"):
        assert bundle[k] is not None
    # This is a strong stock — Quality should be high
    assert bundle["quality_score"] >= 70
