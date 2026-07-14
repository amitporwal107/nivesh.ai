"""Unit tests for the source-schema contract (WORK-0139)."""
from __future__ import annotations

import pytest

from nidp.shared.sources.schema_contract import require_columns, SchemaContractError


def test_all_required_present_ok():
    present = ["SYMBOL", "SERIES", "DATE1", "CLOSE_PRICE"]
    out = require_columns(present, ["SYMBOL", "CLOSE_PRICE"], feed="delivery")
    assert "symbol" in out and "close_price" in out  # normalized, no raise


def test_missing_column_raises_with_detail():
    with pytest.raises(SchemaContractError) as ei:
        require_columns(["SYMBOL", "SERIES"], ["SYMBOL", "CLOSE_PRICE"], feed="delivery")
    msg = str(ei.value)
    assert "delivery" in msg and "close_price" in msg.lower()
    assert ei.value.missing == ["CLOSE_PRICE"]


def test_case_and_whitespace_insensitive():
    # source renamed casing / added spaces — still matches
    require_columns([" scheme code ", "Net Asset Value", "DATE"],
                    ["Scheme Code", "net asset value", "date"], feed="amfi_nav")


def test_extra_columns_allowed():
    # sources add columns without breaking parsers
    require_columns(["A", "B", "C", "D"], ["A", "C"], feed="x")


def test_rename_scenario_is_caught():
    # NSE ClsPric -> ClsgPric: parser needs 'close_price', source dropped it
    with pytest.raises(SchemaContractError):
        require_columns(["symbol", "clsgpric"], ["symbol", "close_price"], feed="bhavcopy")


# ── amfi_nav integration: header-presence check on parse_nav_all ─────────────
from nidp.services.amfi_nav.parser import parse_nav_all

_GOOD = (
    b"Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;"
    b"Scheme Name;Net Asset Value;Date\n"
    b"\nOpen Ended Schemes(Equity Scheme - Large Cap Fund)\n"
    b"Some AMC Mutual Fund\n"
    b"119551;INF209K01YM2;INF209K01YN0;ABSL Frontline Equity - Growth;520.45;07-May-2026\n"
)


def test_amfi_valid_file_parses():
    nav_rows, scheme_rows = parse_nav_all(_GOOD)
    assert len(nav_rows) == 1 and nav_rows[0]["scheme_code"] == "119551"


def test_amfi_html_error_page_raises():
    html = b"<html><head><title>Error</title></head><body>Service unavailable</body></html>"
    with pytest.raises(SchemaContractError):
        parse_nav_all(html)


def test_amfi_missing_required_column_raises():
    # header present but 'Net Asset Value' renamed by the source
    drift = (b"Scheme Code;ISIN;Scheme Name;NAV Value;Date\n"
             b"119551;INF209K01YM2;X - Growth;520.45;07-May-2026\n")
    with pytest.raises(SchemaContractError):
        parse_nav_all(drift)
