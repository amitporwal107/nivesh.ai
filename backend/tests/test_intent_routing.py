"""Routing tests for the copilot intent classifier's deterministic fast path.

The full `intent.py` node imports langchain/langgraph, so the regex routing table
was extracted to `intent_patterns.py` (import-free) to make exactly this testable.
Pairs with the symbol resolver to prove the end-to-end behaviour the stock node
will see.

Regression under test: "FII / DII holding in <stock>" used to route to the
market analyst (because _P_MARKET matches the bare tokens "fii"/"dii"), which has
only market-wide flows — so the copilot answered "I couldn't retrieve the data".
It must route to the stock analyst, while genuine market-flow questions still
reach the market analyst.
"""
from __future__ import annotations

import pytest

from nidp.services.copilot_agent.nodes.intent_patterns import (
    match_agent, MARKET, STOCK, MF, PORTFOLIO, RISK, RECOMMENDATION,
    STOCKS_INSIGHTS,
)
from services.copilot_tools.symbol_resolver import resolve_symbol


# ── R5-A: company-specific regulatory/legal events → stocks_insights ─────────
# (SEBI action / insolvency / NCLT / IBC against a company or its promoters must
#  reach the disclosures tool, NOT the stock-lookup gate ("promoter") or MARKET
#  ("rbi"). The node then caveats self-disclosure-only scope.)
@pytest.mark.parametrize("text", [
    "Any recent SEBI actions against $RELIANCE or its promoters?",
    "Has SEBI passed any order against Adani promoters?",
    "SEBI penalty on $ZEEL",
    "RBI penalty on $HDFCBANK?",
    "Is there any insolvency case filed against $RCOM?",
    "Any IBC proceedings against $JPASSOCIAT?",
    "NCLT winding-up petition against the company",
])
def test_regulatory_events_route_to_stocks_insights(text):
    assert match_agent(text) == STOCKS_INSIGHTS


@pytest.mark.parametrize("text,agent", [
    ("What is the RBI repo rate?", MARKET),      # regulator word alone ≠ enforcement
    ("SEBI new mutual fund regulation", MF),     # rule-making, not an action; MF wins
])
def test_regulatory_pattern_does_not_oversteal(text, agent):
    assert match_agent(text) == agent


# ── The reported bug: per-stock FII/DII holding → stock analyst ──────────────

def test_fii_dii_holding_in_stock_routes_to_stock():
    text = "FII / DII holding in reliance industries"
    assert match_agent(text) == STOCK
    # …and the stock node will resolve the right symbol from the same text.
    assert resolve_symbol(text).symbol == "RELIANCE"


@pytest.mark.parametrize("text,symbol", [
    ("promoter holding in TCS", "TCS"),
    ("shareholding pattern of infosys", "INFY"),
    ("FII holding in HDFCBANK", "HDFCBANK"),
])
def test_ownership_questions_route_to_stock(text, symbol):
    assert match_agent(text) == STOCK
    assert resolve_symbol(text).symbol == symbol


def test_promoter_pledge_routes_to_stock():
    assert match_agent("promoter pledged shares in reliance") == STOCK


# ── Regression guards: market-flow questions must NOT be stolen ──────────────

@pytest.mark.parametrize("text", [
    "FII DII flows today",
    "FII/DII flows this month — net buy or sell?",
    "How's Nifty / Sensex doing today?",
    "India VIX today",
])
def test_market_flow_questions_still_route_to_market(text):
    assert match_agent(text) == MARKET


# ── Broader regressions: existing routing unchanged ─────────────────────────

@pytest.mark.parametrize("text,agent", [
    ("Build me a portfolio", RECOMMENDATION),
    ("Screen large cap stocks where ROE over 15", RECOMMENDATION),
    ("How risky is my portfolio?", RISK),
    ("Rebalancing suggestions for my portfolio", PORTFOLIO),
    ("HDFC Flexi Cap expense ratio", MF),
    ("too many funds in my portfolio", MF),
])
def test_existing_routes_unchanged(text, agent):
    assert match_agent(text) == agent


def test_no_match_returns_none():
    # No routing keyword at all → no regex hit → caller falls back to the LLM.
    assert match_agent("lorem ipsum dolor sit amet") is None


# ── Deterministic single-stock lookups → stock analyst (no LLM fallback) ─────

@pytest.mark.parametrize("text", [
    "What's RELIANCE's price right now?",
    "RELIANCE 52-week high and low",
    "RELIANCE today's open, high, low, previous close",
    "RELIANCE P/E ratio",
    "RELIANCE P/E vs sector / peers",
    "RELIANCE PEG ratio",
    "RELIANCE EV/EBITDA",
    "RELIANCE market capitalisation",
    "RELIANCE return on equity (ROE)",
    "RELIANCE net / operating / EBITDA / gross margins",
    "RELIANCE revenue growth (YoY / QoQ / CAGR)",
    "RELIANCE debt-to-equity ratio",
    "RELIANCE interest coverage ratio",
    "RELIANCE income statement / balance sheet / cash flow",
    "RELIANCE free cash flow trend",
    "RELIANCE dividend yield",
    "RELIANCE 50-day / 200-day moving average",
    "RELIANCE RSI today",
    "RELIANCE MACD signal",
    "RELIANCE support and resistance levels",
    "RELIANCE returns over 1M/6M/1Y/3Y/5Y/10Y",
    "RELIANCE beta",
    "How volatile is RELIANCE?",
    "RELIANCE vs its sector index",
    "Who are RELIANCE's competitors / market share?",
])
def test_single_stock_lookups_route_to_stock(text):
    assert match_agent(text) == STOCK


def test_stock_only_vocab_routes_without_resolvable_symbol():
    # A real ticker outside the curated resolver universe still routes on the
    # stock-ONLY vocabulary path (no index subject, no fund/portfolio hint).
    assert match_agent("PERSISTENT P/E ratio") == STOCK
    assert match_agent("market capitalisation of NEWLISTEDCO") == STOCK


# ── Guards: the gate must NOT steal fund / portfolio / index / market ────────

@pytest.mark.parametrize("text,agent", [
    # fund metrics stay MF (fund hint present)
    ("HDFC Flexi Cap Fund returns 1Y/3Y/5Y", MF),
    ("HDFC Flexi Cap Fund expense ratio", MF),
    # personal portfolio stays risk/portfolio (portfolio hint present)
    ("my portfolio beta", RISK),
    ("How risky is my portfolio?", RISK),
    ("Is my portfolio too concentrated?", PORTFOLIO),
    # index technicals stay market (index subject, no resolvable stock)
    ("Nifty support / resistance levels", MARKET),
    ("Show sectoral index performance", MARKET),
    # commodities / global / flows stay market (previously mis-grabbed by stock)
    ("Gold price today / gold outlook", MARKET),
    ("Silver price and trend", MARKET),
    ("How did US markets close?", MARKET),
    ("How are European markets doing?", MARKET),
    ("What did FIIs and DIIs do today?", MARKET),
])
def test_gate_does_not_steal_non_stock(text, agent):
    assert match_agent(text) == agent
