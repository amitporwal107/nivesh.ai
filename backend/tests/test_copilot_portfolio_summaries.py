"""What the copilot model is told about a portfolio.

The model sees only each tool's one-line summary (ToolResult.as_llm_context
drops data and rows), so anything a user can reasonably ask about has to be in
that line. All names and figures below are made up.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from services.copilot_tools import portfolio


def _run(coro):
    return asyncio.run(coro)


def test_returns_summary_names_the_largest_holdings_by_current_value():
    holdings = [
        {"name": "Small Position Ltd", "quantity": 10, "buy_price": 10, "current_price": 10},     #    100
        {"name": "Alpha Flexi Cap Fund", "quantity": 100, "buy_price": 40, "current_price": 60},   #  6,000
        {"name": "Beta Bank Ltd", "quantity": 30, "buy_price": 90, "current_price": 100},          #  3,000
        {"name": "Sold Out Ltd", "quantity": 0, "buy_price": 5, "current_price": 500},             # not held
        {"name": "Gamma Gold ETF", "quantity": 9, "buy_price": 100, "current_price": 100},         #    900
    ]
    ledger = {"reliable": False, "has_ledger": False}
    with patch.object(portfolio, "_load_holdings", AsyncMock(return_value=holdings)), \
         patch("services.portfolio_enrichment.portfolio_xirr_from_ledger", AsyncMock(return_value=ledger)):
        res = _run(portfolio.get_portfolio_xirr("u1"))
    assert res.ok
    tail = res.summary.split("largest holdings: ")[1]
    assert tail == ("Alpha Flexi Cap Fund ₹6,000 (60.0%); Beta Bank Ltd ₹3,000 (30.0%); "
                    "Gamma Gold ETF ₹900 (9.0%); Small Position Ltd ₹100 (1.0%)")
    assert "Sold Out Ltd" not in res.summary


@pytest.mark.parametrize("name, placeholder", [
    ("Others CBLO", True), ("TREPS", True), ("Net Current Assets", True), ("Tri-Party Repo", True),
    ("Cash & Cash Equivalents", True), ("Other", True), (None, True), ("", True),
    ("The Federal Bank Ltd", False), ("Cashew Exports Ltd", False), ("Motherson Sumi Ltd", False),
])
def test_cash_lines_are_not_stocks(name, placeholder):
    assert portfolio._is_placeholder_stock(name) is placeholder


def test_portfolio_summary_reports_the_first_real_stock_and_sector():
    intel = {
        "total_value": 100000,
        "asset_allocation": {"equity_pct": 90, "debt_pct": 10},
        "top_stocks": [
            {"name": "Others CBLO", "exposure_pct": 4.2},
            {"name": "The Federal Bank Ltd", "exposure_pct": 2.1},
        ],
        "sector_exposure": [
            {"sector": "Unspecified", "pct": 31},
            {"sector": "Financial", "pct": 24},
        ],
    }
    with patch("services.portfolio_intelligence.compute_portfolio_intelligence", AsyncMock(return_value=intel)):
        res = _run(portfolio.get_portfolio_summary("u1"))
    assert "top stock The Federal Bank Ltd 2.1%" in res.summary
    assert "top sector Financial 24%" in res.summary
    assert "CBLO" not in res.summary and "Unspecified" not in res.summary


def test_portfolio_summary_omits_stock_and_sector_when_only_placeholders_exist():
    intel = {"total_value": 100000, "asset_allocation": {"equity_pct": 100},
             "top_stocks": [{"name": "TREPS", "exposure_pct": 3}],
             "sector_exposure": [{"sector": "Unspecified", "pct": 100}]}
    with patch("services.portfolio_intelligence.compute_portfolio_intelligence", AsyncMock(return_value=intel)):
        res = _run(portfolio.get_portfolio_summary("u1"))
    assert "top stock" not in res.summary and "top sector" not in res.summary
