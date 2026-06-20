"""Pure-function tests for the rich stock instrument_detail widget.

build_stock_widget is a pure dict-in/dict-out assembler, so we feed it a
synthetic DaaS payload modelled on the Reliance target mockup and assert the
derived sections (composite bars, PEG, prose, highlights, benchmarked grid,
price position, indicator cards). No network. The contract these assert is the
exact shape the V5 InstrumentDetailWidget renders.
"""
from __future__ import annotations

from services.copilot_tools.instrument_research import build_stock_widget

# Modelled on the mockup: Reliance, quality 49, fundamentals 68, technicals bearish.
_FEAT = {
    "company_name": "Reliance Industries",
    "sector": "Oil, gas & consumable fuels",
    "market_cap_bucket": "LARGE_CAP",
    "as_of_date": "2026-06-19",
    "close": 1309.50,
    "day_change_pct": 1.44,
    "pe_ttm": 21.9,
    "sector_median_pe": 13.0,
    "pe_vs_sector_pct": 68.5,
    "debt_to_equity": 0.44,
    "roe_pct": 15.4,
    "revenue_growth_yoy_pct": 12.9,
    "pat_growth_yoy_pct": -12.6,
    "eps_growth_yoy_pct": 6.6,
    "rsi14": 46.2,
    "macd": -3.0,
    "macd_hist": -1.0,
    "sma50": 1367.0,
    "sma200": 1400.0,
    "swing_low_20": 1259.0,
    "swing_high_20": 1473.0,
    "momentum_score": 46.0,
    "return_20d_pct": 2.1,
    "return_60d_pct": -1.0,
    "piotroski_score": 6,
}
_SCORES = {
    "quality_score": 49,
    "band": "Average",
    "fundamental_score": 68,
    "sector_rank": 8,
    "sector_size": 20,
}


def test_header_meta_and_price():
    w = build_stock_widget("RELIANCE", _FEAT, _SCORES)
    assert w["name"] == "Reliance Industries"
    assert w["badge"] == "STOCK"
    assert w["subtitle"] == "RELIANCE · NSE"
    assert w["meta"] == "Oil, gas & consumable fuels · Large cap"
    assert w["price"]["value"] == "₹1,309.50"
    assert w["price"]["asof"] == "19 Jun 2026"
    assert w["price"]["change_positive"] is True


def test_composite_score_bars():
    w = build_stock_widget("RELIANCE", _FEAT, _SCORES)
    assert w["quality"]["score"] == 49
    f = w["scores"]["fundamental"]
    assert f["score"] == 68 and f["label"] == "Above average" and f["tone"] == "pos"
    t = w["scores"]["technical"]
    # close below both SMAs + MACD<0 + RSI~46 + momentum 46 → bearish
    assert t["tone"] == "neg" and t["label"] == "Bearish"
    assert 20 <= t["score"] <= 40
    assert "dragged down by weak short-term technicals" in w["scores"]["explainer"]


def test_fundamentals_grid_with_benchmarks():
    w = build_stock_widget("RELIANCE", _FEAT, _SCORES)
    grid = {c["label"]: c for c in w["fundamentals_grid"]}
    assert grid["P / E"]["value"] == "21.9"
    assert "sector median 13.0" in grid["P / E"]["note"] and grid["P / E"]["tone"] == "neg"
    # PEG derived = 21.9 / 6.6 = 3.32
    assert grid["PEG ratio"]["value"] == "3.32" and grid["PEG ratio"]["tone"] == "neg"
    assert grid["ROE"]["value"] == "15.4%" and grid["ROE"]["tone"] == "pos"
    assert grid["Debt / equity"]["value"] == "0.44" and grid["Debt / equity"]["tone"] == "pos"
    assert grid["Sales growth (YoY)"]["value"] == "+12.9%" and grid["Sales growth (YoY)"]["tone"] == "pos"
    assert grid["Profit growth (YoY)"]["value"] == "-12.6%" and grid["Profit growth (YoY)"]["tone"] == "neg"


def test_highlights_and_prose():
    w = build_stock_widget("RELIANCE", _FEAT, _SCORES)
    texts = [h["text"] for h in w["highlights"]]
    assert any("premium to peers" in t for t in texts)
    assert any("Net profit fell 12.6% YoY" in t for t in texts)
    assert any("near support" in t for t in texts)
    assert len(w["highlights"]) <= 3
    assert "full valuation" in w["summary"]
    assert "profit slipped year-on-year" in w["summary"]


def test_price_position_and_indicator_cards():
    w = build_stock_widget("RELIANCE", _FEAT, _SCORES)
    pp = w["price_position"]
    assert pp["support_label"] == "₹1,259" and pp["resistance_label"] == "₹1,473"
    assert pp["sma50_label"] == "₹1,367" and pp["current_label"] == "₹1,310"
    assert pp["trend"]["label"] == "Bearish trend"
    cards = {c["label"]: c for c in w["technicals_cards"]}
    assert cards["RSI (14)"]["value"] == "46.2" and cards["RSI (14)"]["note"] == "neutral"
    assert cards["MACD"]["value"] == "Bearish"
    assert cards["Momentum"]["value"] == "46" and "recovering" in cards["Momentum"]["note"]


def test_actions_and_footer():
    w = build_stock_widget("RELIANCE", _FEAT, _SCORES)
    assert [a["label"] for a in w["actions"]] == ["Explain the score", "Compare peers", "Who holds it"]
    assert w["source"] == "NIDP DaaS"
    assert w["disclaimer_note"] == "Not investment advice"


def test_reads_real_nested_composite_scores():
    # Live DaaS exposes the composites NESTED under quality_components, and uses
    # `industry` for the readable classification. Mirror that exact shape.
    feat = {
        "close": 1263.3, "as_of_date": "2026-06-08",
        "sector": "Oil Gas", "industry": "Oil Gas & Consumable Fuels",
        "market_cap_bucket": "LARGE_CAP",
        "pe_ttm": 13.72, "sector_median_pe": 8.78, "pe_vs_sector_pct": None,
        "debt_to_equity": 0.44, "roe_pct": 15.44,
        "revenue_growth_yoy_pct": 12.5, "pat_growth_yoy_pct": -8.94,
        "eps_growth_yoy_pct": -12.55,  # negative → PEG must be omitted
        "rsi14": 31.38, "macd": -20.86, "sma50": 1367.0, "sma200": None,
        "swing_low_20": 1259.2, "swing_high_20": 1473.4,
        "momentum_score": 28.8, "return_20d_pct": -11.7, "return_60d_pct": -10.2,
        "piotroski_score": 5,
    }
    scores = {
        "quality_score": 48.97,
        "quality_components": {
            "fundamental": {"score": 66.89},
            "technical": {"score": 18.47},
        },
        "health_score": 18.47,
    }
    w = build_stock_widget("RELIANCE", feat, scores)
    # readable industry, not the terse sector bucket
    assert w["meta"] == "Oil Gas & Consumable Fuels · Large cap"
    # real nested composites drive the bars (NOT the Piotroski/derived fallback)
    assert w["scores"]["fundamental"]["score"] == 67 and w["scores"]["fundamental"]["tone"] == "pos"
    assert w["scores"]["technical"]["score"] == 18 and w["scores"]["technical"]["tone"] == "neg"
    assert "dragged down by weak short-term technicals" in w["scores"]["explainer"]
    # PEG correctly absent when EPS growth is negative (ratio is meaningless)
    grid_labels = [c["label"] for c in w["fundamentals_grid"]]
    assert "PEG ratio" not in grid_labels
    assert "P / E" in grid_labels


def test_one_day_change_from_prev_close():
    # features/latest has no prev_close; get_stock_research injects it from the
    # prior session. build_stock_widget then derives the 1-day change.
    feat = dict(_FEAT)
    feat.pop("day_change_pct", None)
    feat["prev_close"] = 1291.0  # 1309.50 vs 1291.0 → +1.43%
    w = build_stock_widget("RELIANCE", feat, _SCORES)
    assert w["price"]["change"] == "+1.43%"
    assert w["price"]["change_positive"] is True


def test_sparse_stock_omits_missing_sections():
    # Only price + quality available — derived sections must be absent, not faked.
    w = build_stock_widget("XYZ", {"close": 100.0}, {"quality_score": 55})
    assert w["quality"]["score"] == 55
    assert "fundamentals_grid" not in w
    assert "price_position" not in w
    assert "scores" not in w  # no fundamental_score, no piotroski, no technicals inputs
    assert "highlights" not in w
