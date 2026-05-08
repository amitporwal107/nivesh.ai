"""Golden-file tests for AMFI NAVAll parser. No network, no DB."""
from __future__ import annotations

from pathlib import Path

import pytest

from nidp.services.amfi_nav.parser import parse_nav_all

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def test_parse_navall_basic():
    body = (FIXTURES / "amfi_navall_sample.txt").read_bytes()
    nav_rows, scheme_rows = parse_nav_all(body)

    # 6 valid data rows; 1 N.A. NAV row dropped.
    nav_codes = sorted(r["scheme_code"] for r in nav_rows)
    assert nav_codes == ["112345", "112346", "113333", "114444", "119551", "119552"]
    # N.A. NAV row dropped from both outputs (parser policy: skip
    # unparseable NAV; downstream queries don't want a NaN row either).
    assert "114445" not in {r["scheme_code"] for r in scheme_rows}


def test_parse_navall_amc_state_machine():
    body = (FIXTURES / "amfi_navall_sample.txt").read_bytes()
    _, scheme_rows = parse_nav_all(body)
    by_code = {r["scheme_code"]: r for r in scheme_rows}

    # AMC name carried correctly through type-header transitions.
    assert by_code["119551"]["amc_name_raw"] == "Aditya Birla Sun Life Mutual Fund"
    assert by_code["112345"]["amc_name_raw"] == "SBI Mutual Fund"
    assert by_code["113333"]["amc_name_raw"] == "HDFC Mutual Fund"
    assert by_code["114444"]["amc_name_raw"] == "ICICI Prudential Mutual Fund"


def test_parse_navall_categories():
    body = (FIXTURES / "amfi_navall_sample.txt").read_bytes()
    _, scheme_rows = parse_nav_all(body)
    by_code = {r["scheme_code"]: r for r in scheme_rows}

    assert by_code["119551"]["scheme_category"] == "Equity Scheme - Large Cap Fund"
    assert by_code["112345"]["scheme_category"] == "Equity Scheme - Large Cap Fund"
    assert by_code["113333"]["scheme_category"] == "Equity Scheme - Mid Cap Fund"
    assert by_code["114444"]["scheme_category"] == "Debt Scheme - Liquid Fund"
    assert by_code["119551"]["scheme_type"] == "Open Ended Schemes"


def test_parse_navall_isin_handling():
    body = (FIXTURES / "amfi_navall_sample.txt").read_bytes()
    _, scheme_rows = parse_nav_all(body)
    by_code = {r["scheme_code"]: r for r in scheme_rows}

    # "-" sentinel collapses to None on either ISIN side.
    assert by_code["112345"]["isin_growth"] == "INF200K01TM5"
    assert by_code["112345"]["isin_idcw"] is None
    assert by_code["112346"]["isin_growth"] is None
    assert by_code["112346"]["isin_idcw"] is None
    # Both ISINs present where AMFI publishes both.
    assert by_code["119551"]["isin_growth"] == "INF209K01YM2"
    assert by_code["119551"]["isin_idcw"] == "INF209K01YN0"


def test_parse_navall_nav_values_and_date():
    body = (FIXTURES / "amfi_navall_sample.txt").read_bytes()
    nav_rows, _ = parse_nav_all(body)
    by_code = {r["scheme_code"]: r for r in nav_rows}

    assert by_code["119551"]["nav"] == pytest.approx(520.45)
    assert by_code["119551"]["nav_date"] == "2026-05-07"
    assert by_code["113333"]["nav"] == pytest.approx(145.78)


def test_parse_navall_empty():
    nav_rows, scheme_rows = parse_nav_all(b"")
    assert nav_rows == []
    assert scheme_rows == []


def test_parse_navall_header_only():
    body = b"Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Net Asset Value;Date\n"
    nav_rows, scheme_rows = parse_nav_all(body)
    assert nav_rows == []
    assert scheme_rows == []
