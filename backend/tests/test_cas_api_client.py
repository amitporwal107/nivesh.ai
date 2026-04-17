"""Tests for the CAS Parser API client (casparser.in)."""
import os
import pytest

from services import cas_api_client


def test_api_configured():
    """Sanity: CASPARSER_API_KEY or sandbox key is available."""
    assert cas_api_client.is_configured(), "No CAS Parser API key in environment"


def test_sandbox_parse_and_map(monkeypatch):
    """
    Hit the sandbox endpoint (no credits consumed, no real PDF needed)
    and confirm that the response maps into internal holding dicts.
    """
    monkeypatch.setenv("CASPARSER_USE_SANDBOX", "true")
    # Reload module to pick up env change
    import importlib
    importlib.reload(cas_api_client)

    # Sandbox returns deterministic sample data regardless of PDF content
    data = cas_api_client.parse_cas_pdf(b"dummy-pdf-content", password="ABCDE1234F")
    assert data is not None, "Sandbox call failed — check network / keys"
    assert data.get("meta", {}).get("cas_type") in ("NSDL", "CDSL", "CAMS", "KFintech")
    assert isinstance(data.get("demat_accounts"), list)
    assert isinstance(data.get("mutual_funds"), list)

    holdings = cas_api_client.map_api_response_to_holdings(data)
    assert len(holdings) > 0, "Sample data should yield >0 mapped holdings"

    # Schema check on every mapped holding
    required = {"name", "ticker", "asset_type", "quantity", "buy_price", "current_price"}
    for h in holdings:
        assert required.issubset(h.keys()), f"Holding missing fields: {h}"
        assert h["asset_type"] in {
            "equity", "etf", "mutual_fund", "bond", "gold", "nps", "other"
        }, f"Unexpected asset_type: {h['asset_type']}"
        assert isinstance(h["ticker"], str) and len(h["ticker"]) >= 3
        assert h["quantity"] >= 0
        assert h["current_price"] >= 0


def test_convenience_helper_returns_list(monkeypatch):
    """parse_cas_via_api returns a (possibly empty) list, never None."""
    monkeypatch.setenv("CASPARSER_USE_SANDBOX", "true")
    import importlib
    importlib.reload(cas_api_client)

    holdings = cas_api_client.parse_cas_via_api(b"dummy", password="ABCDE1234F")
    assert isinstance(holdings, list)
    assert len(holdings) > 0


def test_mapping_equity_row_shape():
    """Unit: map a minimal equity row correctly."""
    row = {
        "isin": "INE002A01018",
        "name": "Reliance Industries Limited",
        "units": 100,
        "value": 250000.00,
    }
    h = cas_api_client._holding_from_equity(row)
    assert h["ticker"] == "INE002A01018"
    assert h["asset_type"] == "equity"
    assert h["quantity"] == 100
    assert h["current_price"] == 2500.0  # derived from value/units


def test_mapping_mf_scheme_uses_cost_as_total():
    """Unit: the API returns `cost` as TOTAL invested; mapper must divide by units."""
    scheme = {
        "isin": "INF179K01UT0",
        "name": "HDFC Flexi Cap Fund - Regular - Growth",
        "units": 100,
        "nav": 123.45,
        "value": 12345.00,
        "cost": 10000.00,  # total invested
    }
    h = cas_api_client._holding_from_mf_scheme(scheme)
    assert h["ticker"] == "INF179K01UT0"
    assert h["asset_type"] == "mutual_fund"
    assert h["quantity"] == 100
    assert h["current_price"] == 123.45
    assert h["buy_price"] == 100.0  # 10000 / 100
    assert h["plan"] == "Regular"
    assert h["option"] == "Growth"
