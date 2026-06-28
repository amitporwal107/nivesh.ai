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
)
from services.copilot_tools.symbol_resolver import resolve_symbol


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
