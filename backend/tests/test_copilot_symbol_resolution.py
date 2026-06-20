"""Symbol resolution for the Copilot stock node.

Regression cover for the bug where "How is hdfc looking" returned
"I couldn't retrieve the data" — the case-sensitive `[A-Z]{2,10}` extractor
dropped the lowercase ticker, the node fell back to the NIFTY50 index, every
per-stock tool 404'd, and the anti-hallucination rule emitted the error.

These are deterministic unit tests over the curated instrument universe plus
one integration assertion on `stock_node`'s clarification path. No DB / DaaS.
"""
from __future__ import annotations

import pytest

from services.copilot_tools.symbol_resolver import resolve_symbol


# --- the exact reported failure + sibling cases -------------------------------

@pytest.mark.parametrize(
    "text,expected",
    [
        ("How is hdfc looking", "HDFCBANK"),          # the reported bug (lowercase alias)
        ("how is HDFC looking", "HDFCBANK"),           # uppercase shorthand → alias, not delisted HDFC
        ("analyse reliance", "RELIANCE"),              # lowercase company name
        ("tell me about infosys", "INFY"),             # name → ticker
        ("what is TCS doing", "TCS"),                  # uppercase ticker, exact match
        ("how is tata motors", "TATAMOTORS"),          # multi-word name (tata alone is ambiguous)
        ("how is hdfc life looking", "HDFCLIFE"),      # 2-gram beats the "hdfc" alias
        ("sbi share price", "SBIN"),                   # alias
        ("is airtel a buy", "BHARTIARTL"),             # alias
        ("analyse PERSISTENT", "PERSISTENT"),          # uppercase pass-through (not in curated list)
    ],
)
def test_resolves_expected_symbol(text, expected):
    res = resolve_symbol(text)
    assert res.symbol == expected, f"{text!r} → {res.symbol!r} (source={res.source})"


@pytest.mark.parametrize(
    "text",
    [
        "how is my day going",     # no instrument mentioned
        "what should I do today",  # english words only, none ticker-shaped
        "",                        # empty
    ],
)
def test_unresolvable_returns_none(text):
    assert resolve_symbol(text).symbol is None


def test_ambiguous_single_token_does_not_misresolve():
    # "tata" maps to TCS/TATAMOTORS/TATASTEEL — must NOT silently pick one.
    assert resolve_symbol("how is tata").symbol is None


# --- integration: the clarification path replaces the NIFTY50 fallback --------

@pytest.mark.asyncio
async def test_stock_node_asks_when_no_symbol():
    # Skips where langchain isn't installed (e.g. a bare CI sandbox); the
    # resolver units above are the load-bearing regression cover.
    pytest.importorskip("langchain_core")
    from langchain_core.messages import HumanMessage
    from nidp.services.copilot_agent.nodes.stock import stock_node
    from nidp.services.copilot_agent.schemas import (
        AgentName, CopilotState, IntentClassification,
    )

    state = CopilotState(
        messages=[HumanMessage(content="how is my day going")],
        intent=IntentClassification(agent=AgentName.STOCK, confidence=0.92, symbol=None),
    )
    out = await stock_node(state)

    resp = out["response"]
    assert out["tool_results"] == []          # no tools fired → no false "data unavailable"
    assert "which stock" in resp.text.lower()  # it asks instead of analysing NIFTY50
    assert "NIFTY" not in resp.text.upper()
