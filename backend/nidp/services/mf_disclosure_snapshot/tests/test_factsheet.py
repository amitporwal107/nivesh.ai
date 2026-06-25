"""Deterministic tests for the factsheet AAUM parser.

The page-text fixtures below are the EXACT text pypdf extracts from the
real AMC monthly factsheets, so these assert against ground truth without
committing multi-MB PDFs. Run:

    python -m pytest nidp/services/mf_disclosure_snapshot/tests/test_factsheet.py
"""
from __future__ import annotations

from datetime import date

from nidp.services.mf_disclosure_snapshot.factsheet import (
    FACTSHEET_SOURCES,
    _parse_page,
    _recent_data_months,
)

_HDFC = FACTSHEET_SOURCES["hdfc"]
_DSP = FACTSHEET_SOURCES["dsp"]
_HSBC = FACTSHEET_SOURCES["hsbc"]

# Real extracted text of the HDFC Flexi Cap Fund page (April 2026 factsheet).
_HDFC_FLEXI_PAGE = (
    "7  |  April 2026 \nHDFC Flexi Cap Fund \n"
    "An open ended dynamic equity scheme investing across large cap, mid cap & small cap stocks. \n"
    "CATEGORY OF SCHEME \nFLEXI CAP FUND \n"
    "NAV \nRegular Plan - Growth Option \n1,944.502 \n"
    "ASSETS UNDER MANAGEMENT € \nAs on April 30, 2026 \n"
    "Average for Month of April, \n2026 \n₹100,479.23Cr. \n₹99,221.43Cr. \n"
    "QUANTITATIVE DATA \nPortfolio Turnover \n"
)

_HDFC_BALADV_PAGE = (
    "42  |  April 2026 \nHDFC Balanced Advantage Fund \n"
    "An open ended balanced advantage scheme. \n"
    "ASSETS UNDER MANAGEMENT € \nAs on April 30, 2026 \n"
    "Average for Month of April, \n2026 \n₹105,377.58Cr. \n₹104,098.10Cr. \n"
)

# Real extracted text of a DSP fund page (May 2026 factsheet).
_DSP_PAGE = (
    "DSP Flexi Cap Fund \nAn open ended dynamic equity scheme. \n"
    "NAV \nRegular Plan\nGrowth: ` 492.5940\n"
    "TOTAL AUM\n7,175 Cr.\nMONTHLY AVERAGE AUM\n7,222 Cr.\n"
    "Portfolio Turnover Ratio \n"
)

# Real extracted text of an HSBC fund page (May 2026 "The Asset" factsheet).
_HSBC_PAGE = (
    "HSBC Midcap Fund \nAn open ended equity scheme predominantly investing in mid cap stocks. \n"
    "Date of Inception \n09 Aug 2004 \n"
    "AAUM (for the month \nof May) ₹ 13801.72 Cr. \nMonth End Expense Ratios \n"
)

# A non-fund page (disclaimer/riskometer) — must NOT yield a record.
_NON_FUND_PAGE = (
    "Product label and Riskometers. \nThis product is suitable for investors. \n"
    "The Fund manager's view. No AUM block here. \n"
)


def test_hdfc_extracts_average_aum_not_month_end():
    rec = _parse_page(_HDFC_FLEXI_PAGE, _HDFC)
    assert rec is not None
    assert rec["scheme_name"] == "HDFC Flexi Cap Fund"
    # Captures the AAUM (average for the month), NOT the month-end 100,479.23.
    assert rec["aaum_cr"] == 99221.43


def test_hdfc_balanced_advantage():
    rec = _parse_page(_HDFC_BALADV_PAGE, _HDFC)
    assert rec is not None
    assert rec["scheme_name"] == "HDFC Balanced Advantage Fund"
    assert rec["aaum_cr"] == 104098.10


def test_dsp_extracts_monthly_average_not_total():
    rec = _parse_page(_DSP_PAGE, _DSP)
    assert rec is not None
    assert rec["scheme_name"] == "DSP Flexi Cap Fund"
    # MONTHLY AVERAGE AUM (7,222), not TOTAL AUM (7,175).
    assert rec["aaum_cr"] == 7222.0


def test_hsbc_extracts_aaum_for_the_month():
    rec = _parse_page(_HSBC_PAGE, _HSBC)
    assert rec is not None
    assert rec["scheme_name"] == "HSBC Midcap Fund"
    assert rec["aaum_cr"] == 13801.72


def test_cross_config_does_not_false_match():
    # Each AMC's label format is distinct; configs must not cross-match.
    assert _parse_page(_DSP_PAGE, _HDFC) is None
    assert _parse_page(_HDFC_FLEXI_PAGE, _DSP) is None
    assert _parse_page(_HSBC_PAGE, _DSP) is None
    assert _parse_page(_DSP_PAGE, _HSBC) is None


def test_non_fund_page_yields_none():
    assert _parse_page(_NON_FUND_PAGE, _HDFC) is None
    assert _parse_page(_NON_FUND_PAGE, _DSP) is None
    assert _parse_page(_NON_FUND_PAGE, _HSBC) is None


def test_rejects_objective_sentence_as_name():
    rec = _parse_page(_HDFC_FLEXI_PAGE, _HDFC)
    assert "investing" not in rec["scheme_name"].lower()
    assert len(rec["scheme_name"]) < 70


def test_recent_data_months_newest_first():
    # From 2026-06-25 the newest completed data month is May 2026.
    assert _recent_data_months(date(2026, 6, 25), n=3) == [(2026, 5), (2026, 4), (2026, 3)]


def test_recent_data_months_year_rollover():
    assert _recent_data_months(date(2026, 1, 10), n=2) == [(2025, 12), (2025, 11)]


def test_hdfc_url_uses_next_month_folder_and_encodes_spaces():
    # April 2026 data → uploaded to the 2026-05 folder; spaces percent-encoded.
    url = _HDFC.urls(2026, 4)[0]
    assert "/s3fs-public/2026-05/" in url
    assert "%20" in url and " " not in url
    assert url.endswith("April%202026.pdf")


def test_dsp_url_uses_data_month():
    url = _DSP.urls(2026, 5)[0]
    assert url.endswith("dsp-factsheet-may-2026.pdf")
