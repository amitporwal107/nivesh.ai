"""Unit tests for the NSE financials XBRL parser.

These tests use synthetic fixtures (no network, no external files).
They lock down the contract:

    • `parse_filing_list` extracts manifests from NSE's JSON list shape
    • `parse_xbrl_document`:
        – picks facts whose context.endDate matches manifest.period_end
        – scales raw values by `decimals` then ÷ 1e7 → ₹ crores
        – treats per-share facts as un-scaled
        – detects consolidation from contextRef naming when possible
        – derives ebitda from total_income, expenses, D&A, finance_costs
        – handles XBRL delivered as ZIP
        – emits zero rows when there are no period-matching facts

If NSE shifts the JSON shape or the IND-AS taxonomy adds fresh
local-names we care about, these tests are the canary.
"""
from __future__ import annotations

import io
import json
import zipfile

from nidp.services.nse_financials.parser import (
    parse_filing_list,
    parse_xbrl_document,
)


# ── filing-list parser ──────────────────────────────────────────────
def test_parse_filing_list_extracts_minimum_fields():
    payload = {
        "data": [
            {
                "symbol": "RELIANCE",
                "companyName": "Reliance Industries Ltd",
                "fromDate": "01-Jan-2026",
                "toDate":   "31-Mar-2026",
                "relatingTo": "Consolidated",
                "audited": "Un-Audited",
                "xbrl": "https://archives.nseindia.com/xbrl/RELIANCE_Q4FY26.xml",
                "broadcastDate": "20-Apr-2026 18:30:00",
                "seqNumber": "12345",
            },
        ]
    }
    out = parse_filing_list(json.dumps(payload).encode("utf-8"))
    assert len(out) == 1
    m = out[0]
    assert m["symbol"] == "RELIANCE"
    assert m["period_start"] == "2026-01-01"
    assert m["period_end"]   == "2026-03-31"
    assert m["period_type"]  == "QUARTERLY"
    assert m["consolidated"] is True
    assert m["audited"] is False
    assert m["xbrl_url"].endswith("RELIANCE_Q4FY26.xml")
    assert m["broadcast_at"].startswith("2026-04-20")


def test_parse_filing_list_skips_filings_without_xbrl():
    payload = {
        "data": [
            {"symbol": "ABC", "fromDate": "01-Jan-2026", "toDate": "31-Mar-2026", "xbrl": "-"},
            {"symbol": "DEF", "fromDate": "01-Jan-2026", "toDate": "31-Mar-2026"},
            {"symbol": "GHI", "fromDate": "01-Jan-2026", "toDate": "31-Mar-2026",
             "xbrl": "https://archives.nseindia.com/xbrl/GHI.xml",
             "relatingTo": "Standalone"},
        ]
    }
    out = parse_filing_list(json.dumps(payload).encode("utf-8"))
    assert [m["symbol"] for m in out] == ["GHI"]
    assert out[0]["consolidated"] is False


def test_parse_filing_list_infers_period_type():
    cases = [
        ("01-Jan-2026", "31-Mar-2026", "QUARTERLY"),
        ("01-Oct-2025", "31-Mar-2026", "HALF_YEARLY"),
        ("01-Jul-2025", "31-Mar-2026", "NINE_MONTHS"),
        ("01-Apr-2025", "31-Mar-2026", "ANNUAL"),
    ]
    for f, t, expected in cases:
        payload = {"data": [{"symbol": "X", "fromDate": f, "toDate": t,
                              "xbrl": "https://x/y.xml"}]}
        out = parse_filing_list(json.dumps(payload).encode("utf-8"))
        assert out[0]["period_type"] == expected, (f, t)


def test_parse_filing_list_handles_garbage_input():
    assert parse_filing_list(b"") == []
    assert parse_filing_list(b"<html>error</html>") == []
    assert parse_filing_list(b'{"data": "not-an-array"}') == []


# ── XBRL document parser ────────────────────────────────────────────
_XBRL_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<xbrli:xbrl
    xmlns:xbrli="http://www.xbrl.org/2003/instance"
    xmlns:in-bse-fin="http://www.bseindia.com/xbrl/fin/2025-09-30/in-bse-fin">

  <xbrli:context id="OneD">
    <xbrli:entity><xbrli:identifier scheme="http://www.nseindia.com">XX</xbrli:identifier></xbrli:entity>
    <xbrli:period>
      <xbrli:startDate>2026-01-01</xbrli:startDate>
      <xbrli:endDate>2026-03-31</xbrli:endDate>
    </xbrli:period>
  </xbrli:context>

  <xbrli:context id="OneD_Consolidated">
    <xbrli:entity><xbrli:identifier scheme="http://www.nseindia.com">XX</xbrli:identifier></xbrli:entity>
    <xbrli:period>
      <xbrli:startDate>2026-01-01</xbrli:startDate>
      <xbrli:endDate>2026-03-31</xbrli:endDate>
    </xbrli:period>
  </xbrli:context>

  <xbrli:context id="Instant_BS">
    <xbrli:entity><xbrli:identifier scheme="http://www.nseindia.com">XX</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:instant>2026-03-31</xbrli:instant></xbrli:period>
  </xbrli:context>

  <xbrli:context id="WrongPeriod">
    <xbrli:entity><xbrli:identifier scheme="http://www.nseindia.com">XX</xbrli:identifier></xbrli:entity>
    <xbrli:period>
      <xbrli:startDate>2025-10-01</xbrli:startDate>
      <xbrli:endDate>2025-12-31</xbrli:endDate>
    </xbrli:period>
  </xbrli:context>

  <!-- Standalone facts (raw rupees → 100,00,00,000 = ₹100 cr) -->
  <in-bse-fin:RevenueFromOperations contextRef="OneD" unitRef="INR" decimals="-5">10000000000</in-bse-fin:RevenueFromOperations>
  <in-bse-fin:OtherIncome contextRef="OneD" unitRef="INR" decimals="-5">500000000</in-bse-fin:OtherIncome>
  <in-bse-fin:Income contextRef="OneD" unitRef="INR" decimals="-5">10500000000</in-bse-fin:Income>
  <in-bse-fin:Expenses contextRef="OneD" unitRef="INR" decimals="-5">8500000000</in-bse-fin:Expenses>
  <in-bse-fin:FinanceCosts contextRef="OneD" unitRef="INR" decimals="-5">200000000</in-bse-fin:FinanceCosts>
  <in-bse-fin:DepreciationAndAmortisationExpense contextRef="OneD" unitRef="INR" decimals="-5">300000000</in-bse-fin:DepreciationAndAmortisationExpense>
  <in-bse-fin:ProfitLossBeforeTax contextRef="OneD" unitRef="INR" decimals="-5">2000000000</in-bse-fin:ProfitLossBeforeTax>
  <in-bse-fin:TaxExpense contextRef="OneD" unitRef="INR" decimals="-5">500000000</in-bse-fin:TaxExpense>
  <in-bse-fin:ProfitLoss contextRef="OneD" unitRef="INR" decimals="-5">1500000000</in-bse-fin:ProfitLoss>
  <in-bse-fin:BasicEarningsLossPerShare contextRef="OneD" unitRef="INRPerShares" decimals="2">12.50</in-bse-fin:BasicEarningsLossPerShare>
  <in-bse-fin:DilutedEarningsLossPerShare contextRef="OneD" unitRef="INRPerShares" decimals="2">12.30</in-bse-fin:DilutedEarningsLossPerShare>

  <!-- Consolidated facts (different revenue) -->
  <in-bse-fin:RevenueFromOperations contextRef="OneD_Consolidated" unitRef="INR" decimals="-5">15000000000</in-bse-fin:RevenueFromOperations>
  <in-bse-fin:ProfitLoss contextRef="OneD_Consolidated" unitRef="INR" decimals="-5">2000000000</in-bse-fin:ProfitLoss>

  <!-- Wrong-period fact: should be ignored -->
  <in-bse-fin:RevenueFromOperations contextRef="WrongPeriod" unitRef="INR" decimals="-5">9999999999</in-bse-fin:RevenueFromOperations>

  <!-- Balance-sheet (instant) facts -->
  <in-bse-fin:Equity contextRef="Instant_BS" unitRef="INR" decimals="-5">5000000000</in-bse-fin:Equity>
  <in-bse-fin:LongTermBorrowings contextRef="Instant_BS" unitRef="INR" decimals="-5">3000000000</in-bse-fin:LongTermBorrowings>
  <in-bse-fin:CashAndCashEquivalents contextRef="Instant_BS" unitRef="INR" decimals="-5">800000000</in-bse-fin:CashAndCashEquivalents>
</xbrli:xbrl>
"""


_MANIFEST = {
    "symbol": "TESTCO",
    "period_start": "2026-01-01",
    "period_end":   "2026-03-31",
    "period_type":  "QUARTERLY",
    "consolidated": False,         # hint — actual context detection wins
    "audited":      False,
    "filing_id":    "T-1",
    "xbrl_url":     "https://x/test.xml",
    "broadcast_at": None,
}


def test_xbrl_extracts_income_statement_with_correct_scaling():
    rows = parse_xbrl_document(_XBRL_TEMPLATE.encode("utf-8"), _MANIFEST)
    standalone = next(r for r in rows if r["consolidated"] is False)

    # Raw 10_000_000_000 ÷ 1e7 = 1_000 crore
    assert standalone["revenue_from_ops_cr"] == 1000.0
    assert standalone["other_income_cr"]   == 50.0
    assert standalone["total_income_cr"]   == 1050.0
    assert standalone["total_expenses_cr"] == 850.0
    assert standalone["finance_costs_cr"]  == 20.0
    assert standalone["depreciation_cr"]   == 30.0
    assert standalone["pbt_cr"]            == 200.0
    assert standalone["tax_expense_cr"]    == 50.0
    assert standalone["pat_cr"]            == 150.0


def test_xbrl_per_share_facts_are_unscaled():
    rows = parse_xbrl_document(_XBRL_TEMPLATE.encode("utf-8"), _MANIFEST)
    standalone = next(r for r in rows if r["consolidated"] is False)
    assert standalone["eps_basic"] == 12.5
    assert standalone["eps_diluted"] == 12.3


def test_xbrl_emits_one_row_per_consolidation_detected():
    rows = parse_xbrl_document(_XBRL_TEMPLATE.encode("utf-8"), _MANIFEST)
    flags = sorted(r["consolidated"] for r in rows)
    assert flags == [False, True]
    consolidated = next(r for r in rows if r["consolidated"] is True)
    assert consolidated["revenue_from_ops_cr"] == 1500.0
    assert consolidated["pat_cr"] == 200.0


def test_xbrl_period_mismatch_facts_are_ignored():
    """The WrongPeriod context's RevenueFromOperations (9,999 cr) must
    NOT appear — it's outside the manifest's period_end."""
    rows = parse_xbrl_document(_XBRL_TEMPLATE.encode("utf-8"), _MANIFEST)
    for r in rows:
        # Standalone revenue is 1000 cr, consolidated is 1500 cr.
        assert r["revenue_from_ops_cr"] in (1000.0, 1500.0)


def test_xbrl_balance_sheet_via_instant_period():
    rows = parse_xbrl_document(_XBRL_TEMPLATE.encode("utf-8"), _MANIFEST)
    standalone = next(r for r in rows if r["consolidated"] is False)
    # Instant period 2026-03-31 matches manifest.period_end
    assert standalone["total_equity_cr"]   == 500.0
    assert standalone["long_term_debt_cr"] == 300.0
    assert standalone["cash_and_equiv_cr"] == 80.0


def test_xbrl_derives_ebitda_from_components():
    """ebitda = total_income − (total_expenses − D&A − finance_costs)
    For our fixture: 1050 − (850 − 30 − 20) = 1050 − 800 = 250"""
    rows = parse_xbrl_document(_XBRL_TEMPLATE.encode("utf-8"), _MANIFEST)
    standalone = next(r for r in rows if r["consolidated"] is False)
    assert standalone["ebitda_cr"] == 250.0


def test_xbrl_handles_zip_wrapped_xml():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("RELIANCE_Q4FY26.xml", _XBRL_TEMPLATE)
    rows = parse_xbrl_document(buf.getvalue(), _MANIFEST)
    assert any(r["pat_cr"] == 150.0 for r in rows)


def test_xbrl_returns_empty_when_no_period_match():
    """Manifest period that doesn't match any context → no rows."""
    bad_manifest = {**_MANIFEST, "period_end": "2030-12-31"}
    rows = parse_xbrl_document(_XBRL_TEMPLATE.encode("utf-8"), bad_manifest)
    assert rows == []


def test_xbrl_invalid_input_returns_empty():
    assert parse_xbrl_document(b"", _MANIFEST) == []
    assert parse_xbrl_document(b"not xml or zip", _MANIFEST) == []
    assert parse_xbrl_document(b"<not-xbrl/>", _MANIFEST) == []
