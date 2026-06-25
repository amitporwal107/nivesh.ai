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
    # shareholding feed (for the 'Who holds it' expansion)
    "promoter_pct": 50.3,
    "promoter_pct_change_qoq": 0.0,
    "fii_pct": 18.7,
    "fii_pct_change_qoq": -0.4,
    "dii_pct": 20.5,
    "dii_pct_change_qoq": 0.36,
    "mf_pct": 12.1,
    "promoter_pledged_pct": 0.0,
    "shareholding_period_end": "2026-03-31",
}
_SCORES = {
    "quality_score": 49,
    "band": "Average",
    "fundamental_score": 68,
    "sector_rank": 8,
    "sector_size": 20,
    # nested V3 composites (for the 'Explain the score' expansion)
    "quality_components": {
        "weights": {"cycle": 0.2, "technical": 0.3, "fundamental": 0.5},
        "fundamental": {"score": 66.9, "pillars": {"valuation": 33.0, "governance": 72.9, "balance_sheet": 77.2, "_ev_ebitda": 9.03}},
        "technical": {"score": 18.5, "pillars": {"trend": 7.9, "momentum": 16.1, "_rsi": 30.0}},
        "cycle_position": {"score": 49.9, "pillars": {"margin_position": 50.0}},
    },
}
# DaaS screener rows for the 'Compare peers' expansion (same sector).
_PEERS = [
    {"symbol": "ONGC", "quality_score": 71.0, "industry": "Oil", "market_cap_bucket": "LARGE_CAP"},
    {"symbol": "RELIANCE", "quality_score": 55.7, "industry": "Oil", "market_cap_bucket": "LARGE_CAP"},
    {"symbol": "IOC", "quality_score": 48.0, "industry": "Oil", "market_cap_bucket": "LARGE_CAP"},
]
# Pre-parsed quarterly rows (company_financials shape) for 'Quarterly results'.
_QUARTERLY = [
    {"quarter": "Q4 FY26", "revenue_cr": 240000.0, "pat_cr": 18500.0, "eps_basic": 27.3,
     "ebitda_margin_pct": 17.2, "revenue_yoy_pct": 8.5, "pat_yoy_pct": 12.1},
    {"quarter": "Q3 FY26", "revenue_cr": 232000.0, "pat_cr": 17900.0, "eps_basic": 26.4,
     "ebitda_margin_pct": 16.8, "revenue_yoy_pct": 7.1, "pat_yoy_pct": -3.2},
]
# corporate_actions screener rows for 'Corporate events'.
_CORP = [
    {"action_type": "DIVIDEND", "dividend_amount": 10.0, "ex_date": "2026-05-12"},
    {"action_type": "SPLIT", "face_value_pre": 10, "face_value_post": 5, "ex_date": "2025-07-20"},
    {"action_type": "BONUS", "ratio": "1:1", "ex_date": "2024-10-28"},
]


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
    # real nested technical composite (18) is preferred over the derived blend
    assert t["tone"] == "neg" and t["label"] == "Bearish"
    assert t["score"] == 18
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
    # actions expand inline sections; only offered when the section has data
    w_full = build_stock_widget("RELIANCE", _FEAT, _SCORES, peers=_PEERS,
                                quarterly=_QUARTERLY, corporate_events=_CORP)
    by_expand = {a["expands"]: a["label"] for a in w_full["actions"]}
    assert by_expand == {
        "score_breakdown": "Explain the score",
        "quarterly": "Quarterly results",
        "peers": "Compare peers",
        "shareholding": "Who holds it",
        "corporate_events": "Corporate events",
    }


def test_quarterly_expansion():
    w = build_stock_widget("RELIANCE", _FEAT, _SCORES, quarterly=_QUARTERLY)
    rows = w["quarterly"]["rows"]
    assert rows[0]["quarter"] == "Q4 FY26"
    assert rows[0]["revenue"] == "₹240,000 cr" and rows[0]["pat"] == "₹18,500 cr"
    assert rows[0]["pat_yoy"] == "+12.1%" and rows[0]["pat_yoy_positive"] is True
    assert rows[1]["pat_yoy_positive"] is False  # Q3 PAT fell YoY
    assert rows[0]["margin"] == "17.2%"


def test_corporate_events_expansion():
    w = build_stock_widget("RELIANCE", _FEAT, _SCORES, corporate_events=_CORP)
    rows = {r["type"]: r for r in w["corporate_events"]["rows"]}
    assert rows["Dividend"]["detail"] == "₹10.00 / share" and rows["Dividend"]["date"] == "12 May 2026"
    assert rows["Stock split"]["detail"] == "FV ₹10 → ₹5"
    assert rows["Bonus issue"]["detail"] == "1:1 ratio"


def test_recommendation_long_and_short_term():
    w = build_stock_widget("RELIANCE", _FEAT, _SCORES)
    rec = w["recommendation"]
    # fundamental 68 -> long-term Buy; technical 18 (nested) -> short-term Sell
    assert rec["long_term"]["stance"] == "Buy" and rec["long_term"]["tone"] == "pos"
    assert rec["short_term"]["stance"] == "Sell" and rec["short_term"]["tone"] == "neg"
    assert "fundamentals" in rec["long_term"]["rationale"].lower()
    assert "technicals" in rec["short_term"]["rationale"].lower()


def test_shareholding_expansion():
    w = build_stock_widget("RELIANCE", _FEAT, _SCORES)
    sh = w["shareholding"]
    rows = {r["label"]: r for r in sh["rows"]}
    assert rows["Promoters"]["value"] == "50.30%"
    assert rows["FII"]["change"] == "-0.40%" and rows["FII"]["change_positive"] is False
    assert rows["DII"]["change_positive"] is True
    assert sh["as_of"] == "31 Mar 2026"
    assert sh["pledge"]["tone"] == "pos"  # 0% pledged


def test_score_breakdown_expansion():
    w = build_stock_widget("RELIANCE", _FEAT, _SCORES)
    b = w["score_breakdown"]
    assert b["fundamental"]["score"] == 67 and b["technical"]["score"] == 18
    assert b["weights"]["fundamental"] == 50
    flabels = [p["label"] for p in b["fundamental"]["pillars"]]
    assert "Balance sheet" in flabels and "Valuation" in flabels
    assert not any(p["label"].startswith("_") or p["label"] == "Ev ebitda" for p in b["technical"]["pillars"])  # debug keys dropped


def test_peers_expansion():
    w = build_stock_widget("RELIANCE", _FEAT, _SCORES, peers=_PEERS)
    p = w["peers"]
    assert p["sector"] == "Oil, gas & consumable fuels"
    assert p["current_rank"] == 2  # ONGC 71 > RELIANCE 55.7 > IOC 48
    cur = [r for r in p["rows"] if r["is_current"]]
    assert len(cur) == 1 and cur[0]["symbol"] == "RELIANCE" and cur[0]["quality"] == 56
    assert p["rows"][0]["symbol"] == "ONGC"  # ranked by quality desc
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
