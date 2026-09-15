"""Yahoo Finance fundamentals parser — nidp.services.nse_financials.yahoo_fundamentals.

Fixture is a real fundamentals-timeseries payload for RELIANCE.NS.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from nidp.services.nse_financials.yahoo_fundamentals import parse_yahoo_fundamentals  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "yahoo_fundamentals_reliance.json")


@pytest.fixture(scope="module")
def parsed():
    with open(FIXTURE) as fh:
        return parse_yahoo_fundamentals("RELIANCE", json.load(fh))


def test_returns_both_statements(parsed):
    cash, bal = parsed
    assert len(cash) == 4
    assert len(bal) == 4


def test_values_are_converted_to_crore(parsed):
    cash, _ = parsed
    latest = max(cash, key=lambda r: r["period_end"])
    assert latest["period_end"] == "2026-03-31"
    assert round(latest["cfo_cr"]) == 192113        # base INR / 1e7
    assert latest["capex_cr"] < 0                    # outflow sign preserved


def test_net_change_reconciles(parsed):
    """CFO + CFI + CFF must equal the derived net change — catches a field mis-map."""
    cash, _ = parsed
    for r in cash:
        if all(k in r for k in ("cfo_cr", "cfi_cr", "cff_cr")):
            assert abs((r["cfo_cr"] + r["cfi_cr"] + r["cff_cr"]) - r["net_change_cash_cr"]) < 0.01


def test_working_capital_fields_screener_cannot_supply(parsed):
    _, bal = parsed
    latest = max(bal, key=lambda r: r["period_end"])
    assert round(latest["current_assets_cr"]) == 594249
    assert round(latest["current_liabilities_cr"]) == 541254
    assert round(latest["inventory_cr"]) == 166941
    assert round(latest["trade_receivables_cr"]) == 58491
    assert latest["consolidated"] is True


def test_current_ratio_is_now_computable(parsed):
    _, bal = parsed
    latest = max(bal, key=lambda r: r["period_end"])
    ratio = latest["current_assets_cr"] / latest["current_liabilities_cr"]
    assert 1.0 < ratio < 1.2


def test_empty_payload_is_handled():
    assert parse_yahoo_fundamentals("NOSUCH", {}) == ([], [])
    assert parse_yahoo_fundamentals("NOSUCH", {"timeseries": {"result": []}}) == ([], [])
