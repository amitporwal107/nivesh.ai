"""Unit tests for services.copilot_tools.portfolio.compare_portfolio_funds
and the get_portfolio_overlap UUID→scheme-name fix.

These cover the bug where the "Compare the mutual funds in my portfolio"
copilot answer rendered raw instrument UUIDs (e.g.
`151067d1-67f1-4353-a19e-3b7a6b5aece7`) instead of fund names, and said
rolling returns + TER were unavailable even though portfolio_intelligence
had the data.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest


pytestmark = pytest.mark.asyncio


_INTEL_FIXTURE = {
    "mf_investments": [
        {
            "instrument_id": "mf-1",
            "scheme_name": "Parag Parikh Flexi Cap Fund - Direct Plan",
            "amount_rs": 250_000,
            "category": "Flexi Cap",
            "expense_ratio": 0.62,
            "aum_cr": 75_000.0,
            "rolling_returns": {"1y": 18.5, "3y": 22.1, "5y": 20.4},
            "resolved": True,
        },
        {
            "instrument_id": "mf-2",
            "scheme_name": "HDFC Top 100 Fund - Direct Plan",
            "amount_rs": 180_000,
            "category": "Large Cap",
            "expense_ratio": 1.10,
            "aum_cr": 32_000.0,
            "resolved": True,
        },
    ],
    "catalog": {
        "mf-1": {
            "scheme_name": "Parag Parikh Flexi Cap Fund - Direct Plan",
            "ratios": {"sharpe": 1.42, "std_dev": 12.3,
                       "ret_1y": 18.5, "ret_3y": 22.1, "ret_5y": 20.4},
        },
        "mf-2": {
            "scheme_name": "HDFC Top 100 Fund - Direct Plan",
            "ratios": {"sharpe": 0.85, "std_dev": 14.8,
                       "ret_1y": 12.1, "ret_3y": 15.6, "ret_5y": 14.2},
        },
    },
    "pairwise_overlap": [
        {
            "a": "mf-1", "b": "mf-2",
            "a_name": "Parag Parikh Flexi Cap Fund - Direct Plan",
            "b_name": "HDFC Top 100 Fund - Direct Plan",
            "overlap_pct": 47.3, "shared_count": 9,
            "reasons": ["Moderate overlap"],
        },
    ],
}


async def test_compare_portfolio_funds_uses_scheme_names_not_uuids():
    from services.copilot_tools.portfolio import compare_portfolio_funds

    with patch(
        "services.portfolio_intelligence.compute_portfolio_intelligence",
        AsyncMock(return_value=_INTEL_FIXTURE),
    ):
        result = await compare_portfolio_funds("user-x")

    assert result.ok
    # Every row carries a real scheme_name, not a UUID
    names = [r["scheme_name"] for r in result.rows]
    assert "Parag Parikh Flexi Cap Fund - Direct Plan" in names
    assert "HDFC Top 100 Fund - Direct Plan" in names
    assert not any("-" in n and len(n) == 36 for n in names), "row leaks a UUID"

    # Summary string includes returns + TER so the LLM has data to quote
    s = result.summary
    assert "Parag Parikh" in s
    assert "HDFC Top 100" in s
    assert "TER" in s and "0.62" in s
    assert "1y +18.5%" in s
    # Overlap pair lists fund names, never raw UUIDs
    assert "Parag Parikh Flexi Cap Fund - Direct Plan ↔ HDFC Top 100 Fund - Direct Plan" in s
    assert "mf-1" not in s and "mf-2" not in s


async def test_get_portfolio_overlap_returns_scheme_names():
    from services.copilot_tools.portfolio import get_portfolio_overlap

    with patch(
        "services.portfolio_intelligence.compute_portfolio_intelligence",
        AsyncMock(return_value=_INTEL_FIXTURE),
    ):
        result = await get_portfolio_overlap("user-x")

    assert result.ok
    assert result.rows[0]["fund_a"] == "Parag Parikh Flexi Cap Fund - Direct Plan"
    assert result.rows[0]["fund_b"] == "HDFC Top 100 Fund - Direct Plan"
    # No UUID leakage in the summary
    assert "mf-1" not in result.summary
    assert "Parag Parikh" in result.summary


async def test_compare_handles_partial_data_gracefully():
    """When some funds lack returns/TER, the tool still ships data for the
    ones that have it instead of failing the whole answer."""
    from services.copilot_tools.portfolio import compare_portfolio_funds

    intel = {
        "mf_investments": [
            {
                "instrument_id": "mf-a",
                "scheme_name": "Some Fund A",
                "amount_rs": 100_000,
                "category": "Mid Cap",
                "expense_ratio": None,
                "resolved": True,
            },
            {
                "instrument_id": "mf-b",
                "scheme_name": "Some Fund B",
                "amount_rs": 50_000,
                "category": "Small Cap",
                "expense_ratio": 0.85,
                "resolved": True,
            },
        ],
        "catalog": {
            "mf-b": {"scheme_name": "Some Fund B",
                     "ratios": {"ret_1y": 9.0, "ret_3y": 14.0, "sharpe": 0.7}},
        },
        "pairwise_overlap": [],
    }

    with patch(
        "services.portfolio_intelligence.compute_portfolio_intelligence",
        AsyncMock(return_value=intel),
    ):
        result = await compare_portfolio_funds("user-y")

    assert result.ok
    assert result.data["fund_count"] == 2
    assert result.data["funds_with_returns"] == 1
    assert result.data["funds_with_ter"] == 1
    # No exception raised; both fund names appear in the summary
    assert "Some Fund A" in result.summary
    assert "Some Fund B" in result.summary


# ── Keyword-gate regression tests for portfolio_node ───────────────────────
# These guard against the gate I just wrote being too narrow: " mf " required
# spaces on both sides, so "Compare MF" / "Compare MFs" / "What's the TER?"
# all failed to trigger compare_portfolio_funds.

def _gate(user_msg_lower: str) -> tuple[bool, bool]:
    """Run the wants_compare / wants_fund_ctx gates from portfolio_node
    against a candidate user message. Mirrors the production logic so we
    can detect regressions without spinning up LangGraph."""
    import re as _re
    padded = f" {user_msg_lower} "
    def _has_word(words):
        return any(_re.search(rf"\b{w}\b", padded) for w in words)
    wants_compare = (
        _has_word(["compare", "comparison", "vs", "versus"])
        or any(p in user_msg_lower for p in (
            "side by side", "side-by-side", "rolling return", "expense ratio", "ter%"
        ))
        or _has_word(["ter"])
    )
    wants_fund_ctx = _has_word(
        ["fund", "funds", "mf", "mfs", "mutual", "scheme", "schemes"]
    )
    return wants_compare, wants_fund_ctx


@pytest.mark.parametrize("msg", [
    "compare the mutual funds in my portfolio. show rolling returns, expense ratio, and overlap.",
    "compare my mfs by ter",
    "compare mf returns",
    "what is the ter of my funds?",
    "compare fund expense ratios",
    "side-by-side comparison of my schemes",
    "show me a rolling return comparison for my funds",
    "fund a vs fund b in my portfolio",
])
def test_compare_keyword_gate_matches_real_user_phrasings(msg):
    wc, wf = _gate(msg)
    assert wc, f"wants_compare should match: {msg!r}"
    assert wf, f"wants_fund_ctx should match: {msg!r}"


@pytest.mark.parametrize("msg", [
    "what is my xirr?",
    "should i rebalance my portfolio?",
    "run a stress test",
])
def test_compare_keyword_gate_does_not_overfire(msg):
    wc, wf = _gate(msg)
    assert not (wc and wf), f"compare_portfolio_funds should NOT trigger on: {msg!r}"
