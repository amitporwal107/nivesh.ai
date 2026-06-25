"""Deterministic unit tests for the MF chat cards (summary + detail views).

These are pure-function tests over RECORDED DaaS payload shapes (real keys captured
from staging /v1/mf/* for scheme 100119) — no network. They assert two things the
CONTEXT honesty rules require:

  1. Reconciliation: derived numbers (allocation %, top-10 weight, sector roll-ups)
     equal the sum of their inputs — not approximations.
  2. No invented data: when a source field is null/absent the widget OMITS it; the
     builders never default a missing value to a fake number.

Plus the user-visible failure modes called out during design:
  * short-horizon (1M/3M/6M) returns are never surfaced (feed bug),
  * the subject fund is always pinned into its own peer list,
  * fund-name → scheme query extraction for every templated tab prompt.
"""
from __future__ import annotations

from services.copilot_tools.scheme_resolver import extract_scheme_query
from services.copilot_tools.mf_cards import (
    build_mf_overview,
    build_mf_returns,
    build_mf_holdings,
    build_mf_peers,
    quartile_insights,
    _nav_block,
)

# ── recorded shapes (real keys from staging, scheme 100119) ──────────────────

SCORECARD = {
    "scheme_code": "100119",
    "scheme_name": "HDFC Balanced Advantage Fund - Growth Plan",
    "category": "Hybrid Scheme",
    "sub_category": "Dynamic Asset Allocation or Balanced Advantage",
    "scheme_launch_date": "2006-04-03",
    "return_1m": -19.6373, "return_3m": -15.7468, "return_6m": -10.8505,
    "return_1y": -1.8659, "return_3y": 14.5381, "return_5y": 17.0771,
    "return_since_launch_cagr": 17.2035,
    "volatility_1y": 9.1828, "sharpe_1y": -0.911, "beta_1y": 0.1022,
    "ter": None, "aum_cr": None,
    "composite_score": 22.0, "composite_rank": 122, "total_in_category": 153,
    "qtile_ret1y": 3, "qtile_ret3y": 1, "qtile_ret5y": 1, "qtile_alpha": 3,
}
SCHEME = {
    "scheme_code": "100119",
    "scheme_name": "HDFC Balanced Advantage Fund - Growth Plan",
    "scheme_category": "Hybrid Scheme - Dynamic Asset Allocation or Balanced Advantage",
    "latest_nav": 520.725, "latest_nav_date": "2026-06-18",
    "launch_date": "2006-04-03",
    "benchmark_name": None, "ter_pct": None, "ter_pct_direct": None,
    "risk_o_meter": None, "primary_manager": None, "isin_growth": "INF179K01830",
}
NAV_SERIES = [{"nav_date": "2026-06-18", "nav": 520.725},
              {"nav_date": "2026-06-17", "nav": 519.476}]
PRIM = {"category_avg_1y": 6.81, "category_avg_3y": 8.55, "category_avg_5y": 7.79,
        "expense_ratio_regular": None, "aum_cr": None, "primary_manager": None}


# ── scheme-name extraction ───────────────────────────────────────────────────

def test_extract_scheme_query_templated_prompts():
    name = "HDFC Balanced Advantage Fund"
    assert extract_scheme_query("Show the holdings of HDFC Balanced Advantage Fund.") == name
    assert extract_scheme_query("Compare HDFC Balanced Advantage Fund with its peers.") == name
    assert extract_scheme_query("Show the overview of HDFC Balanced Advantage Fund Growth.") == name
    assert extract_scheme_query("Show the returns of HDFC Balanced Advantage Fund across periods.") == name
    assert extract_scheme_query("Help me start a SIP in HDFC Balanced Advantage Fund.") == name
    assert extract_scheme_query("tell me about Parag Parikh Flexi Cap") == "Parag Parikh Flexi Cap"


# ── nav change derivation ────────────────────────────────────────────────────

def test_nav_block_derives_daily_change():
    nb = _nav_block(SCHEME, NAV_SERIES)
    assert nb["value"] == "₹520.73"
    # (520.725 - 519.476) / 519.476 * 100 = +0.24%
    assert nb["change"] == "+0.24%"
    assert nb["change_positive"] is True


def test_nav_block_omits_change_without_two_points():
    nb = _nav_block(SCHEME, NAV_SERIES[:1])
    assert "change" not in nb          # never fabricate a change from one NAV
    assert nb["value"] == "₹520.73"


# ── quartile insights (deterministic, grounded in quartile ranks) ────────────

def test_quartile_insights_maps_quartiles_to_bullets():
    summary, consider, watch = quartile_insights(SCORECARD)
    assert "Top-quartile 3-year returns in its category" in consider
    assert "Top-quartile 5-year returns" in consider
    assert any("Below-median 1-year" in w for w in watch)
    assert summary == "A long-term outperformer going through a short-term rough patch."


def test_quartile_insights_empty_when_no_quartiles():
    summary, consider, watch = quartile_insights({})
    assert consider == [] and watch == [] and summary == ""


# ── overview: omit null facts, never invent ──────────────────────────────────

def test_overview_omits_null_disclosure_facts():
    w = build_mf_overview(SCORECARD, SCHEME, NAV_SERIES, PRIM)
    labels = {f["label"] for f in w.get("facts", [])}
    assert "Category" in labels and "Launched" in labels
    # benchmark / AUM / expense / risk are all null in the feed → omitted
    assert "Benchmark" not in labels
    assert "AUM" not in labels
    assert "Expense ratio" not in labels
    assert "Risk" not in labels
    assert "managers" not in w          # primary_manager null → omitted, not "N/A"


def test_overview_returns_snapshot_uses_sane_horizons_only():
    w = build_mf_overview(SCORECARD, SCHEME, NAV_SERIES, PRIM)
    labels = [r["label"] for r in w["returns_snapshot"]]
    assert labels == ["1Y", "3Y", "5Y", "Since launch"]
    assert all(x not in labels for x in ("1M", "3M", "6M"))


def test_overview_quality_carries_real_score_and_rank():
    w = build_mf_overview(SCORECARD, SCHEME, NAV_SERIES, PRIM)
    assert w["quality"]["score"] == 22
    assert w["quality"]["rank"] == 122 and w["quality"]["of"] == 153


# ── returns: sane horizons + fund-vs-category, no benchmark fabrication ───────

def test_returns_cagr_omits_short_horizons_and_adds_category():
    w = build_mf_returns(SCORECARD, SCHEME, NAV_SERIES, PRIM)
    by_label = {r["label"]: r for r in w["cagr"]}
    assert set(by_label) == {"3 years", "5 years", "1 year"}     # no 1M/3M/6M
    assert by_label["3 years"]["fund"] == 14.54
    assert by_label["3 years"]["category"] == 8.55               # from primitives
    assert "benchmark" not in by_label["3 years"]                # not in feed → absent


def test_returns_empty_when_no_return_data():
    w = build_mf_returns({"scheme_name": "X"}, {}, [], {})
    assert "cagr" not in w                                       # nothing invented


# ── holdings: reconciliation of derived aggregates ───────────────────────────

HOLDINGS = [
    {"security_name": "HDFC Bank", "security_isin": "I1", "instrument_type": "EQUITY", "sector": "Banks", "weight_pct": 6.0},
    {"security_name": "ICICI Bank", "security_isin": "I2", "instrument_type": "EQUITY", "sector": "Banks", "weight_pct": 4.0},
    {"security_name": "Reliance", "security_isin": "I3", "instrument_type": "EQUITY", "sector": "Oil & gas", "weight_pct": 3.0},
    {"security_name": "GOI 2032", "security_isin": "D1", "instrument_type": "DEBT", "rating": "Sovereign", "weight_pct": 20.0},
    {"security_name": "NABARD", "security_isin": "D2", "instrument_type": "DEBT", "rating": "AAA", "weight_pct": 10.0},
    {"security_name": "TREPS", "security_isin": "C1", "instrument_type": "CASH", "weight_pct": 57.0},
]


def test_holdings_allocation_and_stats_reconcile():
    w = build_mf_holdings(SCORECARD, SCHEME, NAV_SERIES, HOLDINGS)
    alloc = {a["label"]: a["pct"] for a in w["asset_allocation"]}
    assert alloc["Equity"] == 13.0          # 6+4+3
    assert alloc["Debt"] == 30.0            # 20+10
    assert alloc["Cash"] == 57.0
    assert round(sum(alloc.values()), 2) == 100.0

    sectors = {s["label"]: s["pct"] for s in w["sectors"]}
    assert sectors["Banks"] == 10.0         # 6+4 rolled up
    assert sectors["Oil & gas"] == 3.0

    dq = {d["label"]: d["pct"] for d in w["debt_quality"]}
    assert dq == {"Sovereign": 20.0, "AAA": 10.0}

    stats = {s["label"]: s["value"] for s in w["stats"]}
    assert stats["Stocks held"] == "3"
    assert stats["Top-10 weight"] == "13.0%"      # all 3 equities
    assert stats["Equity exposure"] == "13.0%"
    assert w["top_holdings"][0]["name"] == "HDFC Bank"


# ── peers: dedupe plan variants + pin the subject fund ───────────────────────

PEERS = [
    {"scheme_code": "151882", "scheme_name": "UTI Balanced Advantage Fund - Regular Plan - Growth", "aum_cr": 3012.99, "return_1y": -3.79, "return_3y": None, "ter": 1.86, "composite_score": 41.0},
    {"scheme_code": "151885", "scheme_name": "UTI Balanced Advantage Fund - Direct Plan - Growth", "aum_cr": 3012.99, "return_1y": -2.43, "ter": 1.0, "composite_score": 36.0},
    {"scheme_code": "999999", "scheme_name": "HSBC Balanced Advantage Fund - Growth", "aum_cr": 1500.0, "return_1y": -6.87, "return_3y": 2.7, "ter": 1.5, "composite_score": 50.0},
]


def test_peers_dedupes_variants_and_pins_subject():
    w = build_mf_peers(SCORECARD, SCHEME, NAV_SERIES, PEERS)
    rows = w["rows"]
    # subject fund (100119, absent from the leaderboard page) is synthesised + pinned first
    assert rows[0]["is_current"] is True
    assert rows[0]["name"] == "HDFC Balanced Advantage Fund"
    assert rows[0]["ret3y"] == 14.5381
    # UTI Reg + Direct collapse to ONE family row
    uti = [r for r in rows if r["name"] == "UTI Balanced Advantage Fund"]
    assert len(uti) == 1
    assert w["highlight_code"] == "100119"


def test_peers_empty_when_no_peers():
    w = build_mf_peers(SCORECARD, SCHEME, NAV_SERIES, [])
    # only the synthesised subject row (no peers) — still pinned, never crashes
    assert all(r.get("is_current") for r in w.get("rows", []))
