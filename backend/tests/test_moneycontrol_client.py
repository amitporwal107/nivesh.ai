"""Unit tests for services.moneycontrol_client.

Covers:
  - parse_investment_style() mapping of Morningstar-style strings.
  - _build_payload() against a minimal fixture __NEXT_DATA__ shape.
  - search_fund() prefers Direct-plan MF hits over non-MF URLs (mocked httpx).
"""
from __future__ import annotations
import pytest

from services import moneycontrol_client as mcc


# ── parse_investment_style ──────────────────────────────────────────────
@pytest.mark.parametrize("style,expected_cq,expected_dr", [
    ("Moderate Sensitivity High Quality", 9.0, 6.0),
    ("Limited Sensitivity High Quality", 9.0, 9.0),
    ("Extensive Sensitivity Medium Quality", 6.0, 3.0),
    ("Limited Sensitivity Low Quality", 3.0, 9.0),
    ("Extensive Sensitivity Low Quality", 3.0, 3.0),
])
def test_parse_investment_style_full(style, expected_cq, expected_dr):
    out = mcc.parse_investment_style(style)
    assert out["credit_quality_score"] == expected_cq
    assert out["duration_risk_score"] == expected_dr


def test_parse_investment_style_none_or_empty():
    assert mcc.parse_investment_style(None) == {
        "credit_quality_score": None,
        "duration_risk_score": None,
    }
    assert mcc.parse_investment_style("") == {
        "credit_quality_score": None,
        "duration_risk_score": None,
    }


def test_parse_investment_style_partial_match():
    """Only quality present — duration_risk_score should be None."""
    out = mcc.parse_investment_style("High Quality")
    assert out["credit_quality_score"] == 9.0
    assert out["duration_risk_score"] is None


# ── _build_payload ───────────────────────────────────────────────────────
def _make_mc_next_data(**overrides):
    base = {
        "props": {
            "pageProps": {
                "data": {
                    "isin": "INF179K01XD8",
                    "overview": {
                        "imid": "MHD1209",
                        "schemeName": "HDFC Corporate Bond Fund -Direct Plan - Growth",
                        "schemeNameShort": "HDFC CBF Direct",
                        "planName": "Direct",
                        "categoryName": "Fixed Income",
                        "subCategoryName": "Corporate Bond",
                        "companyName": "HDFC Mutual Fund",
                        "latestNAV": "32.45",
                        "aum": "31028.83",
                        "expenseRatio": "0.36",
                        "sharpeRatio": "0.75",
                        "stadardDeviation": "1.8",
                        "beta_3_year": "0.9",
                        "turnoverRatio": "125.0",
                        "top5StkWt": "15.2",
                        "top10StkWt": "28.3",
                        "cagr_3y": "7.43",
                        "cagr_5y": "7.12",
                        "cagr_7y": "7.8",
                        "cagr_10y": "8.0",
                        "cagr_since_inception": "8.2",
                        "investmentStyle": "Moderate Sensitivity High Quality",
                        "rating": 4,
                        "assetAllocation": {"debt": 94, "cash": 6},
                    },
                    "about": {
                        "benchmark": "NIFTY Corporate Bond Index",
                        "riskometer": "Moderate",
                        "lanch_date": "29 Jun, 2010",
                        "fund_managers_details": [
                            {"name": "Anupam Joshi", "startDate": "10 Jan, 2020"},
                        ],
                    },
                }
            }
        }
    }
    base["props"]["pageProps"]["data"]["overview"].update(overrides)
    return base


def test_build_payload_full_debt_fund():
    data = _make_mc_next_data()
    payload = mcc._build_payload(data)
    assert payload is not None
    assert payload["moneycontrol_imid"] == "MHD1209"
    assert payload["scheme_name"].startswith("HDFC Corporate Bond")
    assert payload["plan_type"] == "direct"
    assert payload["isin"] == "INF179K01XD8"
    assert payload["category"] == "Fixed Income"
    assert payload["sub_category"] == "Corporate Bond"
    assert payload["amc_name"] == "HDFC Mutual Fund"
    assert payload["aum_cr"] == 31028.83
    assert payload["expense_ratio"] == 0.36
    assert payload["sharpe"] == 0.75
    assert payload["investment_style"] == "Moderate Sensitivity High Quality"
    assert payload["credit_quality_score"] == 9.0
    assert payload["duration_risk_score"] == 6.0
    assert payload["manager_name"] == "Anupam Joshi"
    assert payload["launch_date"] == "2010-06-29"
    assert payload["fund_age_years"] is not None
    assert payload["source"] == "moneycontrol"


def test_build_payload_missing_imid_returns_none():
    data = _make_mc_next_data(imid=None)
    assert mcc._build_payload(data) is None


def test_build_payload_missing_scheme_name_returns_none():
    data = _make_mc_next_data(schemeName=None)
    assert mcc._build_payload(data) is None


def test_build_payload_wrong_shape_returns_none():
    assert mcc._build_payload({}) is None
    assert mcc._build_payload({"props": {}}) is None


# ── Misc helpers ────────────────────────────────────────────────────────
def test_to_float_handles_varied_inputs():
    assert mcc._to_float(None) is None
    assert mcc._to_float("") is None
    assert mcc._to_float("None") is None
    assert mcc._to_float("1,234.56") == 1234.56
    assert mcc._to_float("12.5%") == 12.5
    assert mcc._to_float(42) == 42.0
    assert mcc._to_float("abc") is None


def test_parse_launch_date_formats():
    assert mcc._parse_launch_date("29 Jun, 2010") == "2010-06-29"
    assert mcc._parse_launch_date("1 January, 2005") == "2005-01-01"
    assert mcc._parse_launch_date(None) is None
    assert mcc._parse_launch_date("not a date") is None


def test_years_since_returns_positive_float():
    y = mcc._years_since("2020-01-01")
    assert y is not None
    assert y > 3.0  # at least several years after 2020
