"""Tests for the AdvisorKhoj disclosure parser + month-URL matcher.

The workbook fixture mirrors the real SEBI disclosure layout (leading blank
column, title rows, a section-subtotal row with a weight but no ISIN, real
holdings, and a no-ISIN cash row) so the ISIN-keyed filter and weight
normalisation are asserted against ground truth.

    python -m pytest nidp/services/mf_holdings/tests/test_advisorkhoj.py
"""
from __future__ import annotations

import io
import zipfile
from datetime import date

import openpyxl

from nidp.services.mf_holdings.advisorkhoj import (
    _file_url_for_month,
    _month_patterns,
    parse_disclosure_zip,
)


def _make_disclosure_zip() -> bytes:
    """One per-fund xlsx (filename = scheme name) in the standard SEBI shape.
    % to Nav is given as a FRACTION (sum ≈ 1) like ICICI's real files."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "EQ"
    ws.append([None, "Some AMC Mutual Fund"])
    ws.append([None, "Acme Flexi Cap Fund"])
    ws.append([None, "Portfolio as on May 31, 2026"])
    ws.append([None, "Company/Issuer/Instrument Name", "ISIN", "Coupon",
               "Industry/Rating", "Quantity", "Exposure/Market Value(Rs.Lakh)", "% to Nav"])
    # section subtotal: weight but NO ISIN → must be dropped (else double-counts)
    ws.append([None, "Equity & Equity Related Instruments", None, None, None, None, 9000.0, 0.90])
    ws.append([None, "TVS Motor Company Ltd.", "INE494B01023", None, "Automobiles", 100, 6000.0, 0.60])
    ws.append([None, "ICICI Bank Ltd.", "INE090A01021", None, "Banks", 200, 3000.0, 0.30])
    # cash / TREPS row: no ISIN → dropped
    ws.append([None, "TREPS", None, None, None, None, 1000.0, 0.10])
    ws.append([None, "Total Net Assets", None, None, None, None, 10000.0, 1.00])
    buf = io.BytesIO()
    wb.save(buf)

    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, "w") as z:
        z.writestr("Acme Flexi Cap Fund.xlsx", buf.getvalue())
    return zbuf.getvalue()


def test_keeps_only_isin_rows_and_drops_aggregates():
    rows = parse_disclosure_zip(_make_disclosure_zip(), date(2026, 5, 1), "ak://x", "TEST_TAG")
    names = {r["security_name"] for r in rows}
    assert names == {"TVS Motor Company Ltd.", "ICICI Bank Ltd."}     # 2 real holdings only
    assert "Equity & Equity Related Instruments" not in names         # subtotal dropped
    assert "TREPS" not in names                                       # cash dropped


def test_weights_scaled_to_percent_and_sum_under_100():
    rows = parse_disclosure_zip(_make_disclosure_zip(), date(2026, 5, 1), "ak://x", "TEST_TAG")
    by_name = {r["security_name"]: r for r in rows}
    # fraction 0.60 → 60.0%, 0.30 → 30.0% (sum 90 < 100, since cash is excluded)
    assert by_name["TVS Motor Company Ltd."]["weight_pct"] == 60.0
    assert by_name["ICICI Bank Ltd."]["weight_pct"] == 30.0
    assert sum(r["weight_pct"] for r in rows) == 90.0


def test_market_value_lakh_to_inr_and_fields():
    rows = parse_disclosure_zip(_make_disclosure_zip(), date(2026, 5, 1), "ak://x", "TEST_TAG")
    tvs = next(r for r in rows if r["security_name"].startswith("TVS"))
    assert tvs["security_isin"] == "INE494B01023"
    assert tvs["market_value_inr"] == 6000.0 * 100000.0      # ₹lakh → ₹
    assert tvs["sector"] == "Automobiles"
    assert tvs["source"] == "TEST_TAG"
    assert tvs["as_of_month"] == "2026-05-01"
    assert tvs["scheme_code"] == "Acme Flexi Cap Fund"       # from filename; adapter resolves


def test_month_matcher_handles_amc_url_variants():
    may = date(2026, 5, 1)
    pats = _month_patterns(may)

    def matches(url):
        import re
        low = url.lower()
        return any(re.search(p, low) for p in pats)

    assert matches("https://x/blob/Monthly Portfolio Disclosures/2026/May/MP.zip")   # ICICI path
    assert matches("https://x/Consolidated-Portfolio-as-on-May-2026.zip")            # Kotak name
    assert matches("https://x/uti_mf_scheme_portfolios_31.05.2026.zip")              # UTI DD.MM.YYYY
    assert matches("https://x/Monthly_Portfolio_31_05_26.xlsx")                      # Axis DD_MM_YY
    # must NOT match a different month
    assert not matches("https://x/uti_mf_scheme_portfolios_30.04.2026.zip")
    assert not matches("https://x/Portfolio-as-on-April-2026.zip")


def test_file_url_for_month_picks_right_link():
    html = '''
      <a href="/files/Portfolio-as-on-April-2026.zip">Apr</a>
      <a href="/files/Portfolio-as-on-May-2026.zip">May</a>
    '''
    url = _file_url_for_month(html, "https://amc.example.com/", date(2026, 5, 1))
    assert url == "https://amc.example.com/files/Portfolio-as-on-May-2026.zip"
