"""Golden-file tests for AMFI NAVAll parser. No network, no DB."""
from __future__ import annotations

from datetime import date
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
    assert by_code["119551"]["nav_date"] == date(2026, 5, 7)
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


# ── Eight-column layout (Plan and Option split out of the scheme name) ──────
_EIGHT_COL = (
    "Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Plan;Option;Net Asset Value;Date\r\n"
    " \r\n"
    "Open Ended Schemes(Equity Scheme - Large Cap Fund)\r\n"
    " \r\n"
    "Alpha Mutual Fund\r\n"
    " \r\n"
    "900001;INF000A01AA1;-;Alpha Large Cap Fund;Direct Plan;Growth Option;29.0745;09-Oct-2026\r\n"
    "900002;INF000A01AB9;INF000A01AC7;Alpha Large Cap Fund;Regular Plan;IDCW Option;26.7829;09-Oct-2026\r\n"
    "900003;-;-;Alpha Legacy Fund;-;-;N.A.;09-Oct-2026\r\n"
).encode()


def test_eight_column_layout_reads_nav_and_date_by_header_name():
    nav_rows, scheme_rows = parse_nav_all(_EIGHT_COL)
    assert [(r["scheme_code"], r["nav"], str(r["nav_date"])) for r in nav_rows] == [
        ("900001", 29.0745, "2026-10-09"),
        ("900002", 26.7829, "2026-10-09"),
    ]
    assert len(scheme_rows) == 2            # the N.A. row has no NAV and is skipped


def test_eight_column_layout_rebuilds_the_descriptive_scheme_name():
    _, scheme_rows = parse_nav_all(_EIGHT_COL)
    by_code = {s["scheme_code"]: s for s in scheme_rows}
    assert by_code["900001"]["scheme_name"] == "Alpha Large Cap Fund - Direct Plan - Growth Option"
    assert by_code["900002"]["scheme_name"] == "Alpha Large Cap Fund - Regular Plan - IDCW Option"
    assert by_code["900001"]["isin_growth"] == "INF000A01AA1" and by_code["900001"]["isin_idcw"] is None
    assert by_code["900002"]["isin_idcw"] == "INF000A01AC7"
    assert by_code["900001"]["amc_name_raw"] == "Alpha Mutual Fund"
    assert by_code["900001"]["scheme_category"] == "Equity Scheme - Large Cap Fund"
