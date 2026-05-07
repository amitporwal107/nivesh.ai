"""Unit tests for the NSE shareholding-pattern XBRL parser.

Synthetic fixtures only. Locks the contract:

    • `parse_filing_list` extracts manifests from NSE's JSON list shape
      (asOnDate / xbrl URL / symbol)
    • `parse_xbrl_document`:
        – picks Reg-31 percentage facts whose context.instant matches
          manifest.period_end
        – derives public_pct from 100 − promoter_pct when missing
        – tolerates ZIP-wrapped XBRL
        – returns no rows when nothing matches
"""
from __future__ import annotations

import io
import json
import zipfile

from nidp.services.nse_shareholding.parser import (
    parse_filing_list,
    parse_xbrl_document,
)


def test_parse_filing_list_basic_shape():
    payload = {
        "data": [
            {
                "symbol": "INFY",
                "companyName": "Infosys Ltd",
                "asOnDate": "31-Mar-2026",
                "xbrl": "https://archives.nseindia.com/xbrl/INFY_SHP.xml",
                "broadcastDate": "10-Apr-2026 17:00:00",
                "seqNumber": "777",
            },
        ]
    }
    out = parse_filing_list(json.dumps(payload).encode("utf-8"))
    assert len(out) == 1
    assert out[0]["symbol"] == "INFY"
    assert out[0]["period_end"] == "2026-03-31"
    assert out[0]["xbrl_url"].endswith("INFY_SHP.xml")
    assert out[0]["broadcast_at"].startswith("2026-04-10")


def test_parse_filing_list_skips_when_no_xbrl_or_no_date():
    payload = {
        "data": [
            {"symbol": "AAA", "asOnDate": "31-Mar-2026"},                 # no xbrl
            {"symbol": "BBB", "asOnDate": "31-Mar-2026", "xbrl": "-"},    # placeholder
            {"symbol": "CCC", "xbrl": "https://x/y.xml"},                  # no date
            {"symbol": "DDD", "asOnDate": "31-Mar-2026", "xbrl": "https://x/y.xml"},
        ]
    }
    out = parse_filing_list(json.dumps(payload).encode("utf-8"))
    assert [m["symbol"] for m in out] == ["DDD"]


def test_parse_filing_list_handles_garbage():
    assert parse_filing_list(b"") == []
    assert parse_filing_list(b"<html/>") == []
    assert parse_filing_list(b'{"data": "scalar"}') == []


# ── XBRL document ───────────────────────────────────────────────────
_SHP_XBRL = """<?xml version="1.0" encoding="UTF-8"?>
<xbrli:xbrl
    xmlns:xbrli="http://www.xbrl.org/2003/instance"
    xmlns:in-shp="http://www.nseindia.com/xbrl/shp">

  <xbrli:context id="OnDate">
    <xbrli:entity><xbrli:identifier scheme="http://www.nseindia.com">XX</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:instant>2026-03-31</xbrli:instant></xbrli:period>
  </xbrli:context>

  <xbrli:context id="OnDate_Promoter">
    <xbrli:entity><xbrli:identifier scheme="http://www.nseindia.com">XX</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:instant>2026-03-31</xbrli:instant></xbrli:period>
  </xbrli:context>

  <xbrli:context id="StaleDate">
    <xbrli:entity><xbrli:identifier scheme="http://www.nseindia.com">XX</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:instant>2025-12-31</xbrli:instant></xbrli:period>
  </xbrli:context>

  <in-shp:PercentageOfShareholdingPromoterAndPromoterGroup contextRef="OnDate" decimals="2">52.84</in-shp:PercentageOfShareholdingPromoterAndPromoterGroup>
  <in-shp:PercentageOfShareholdingForeignPortfolioInvestors contextRef="OnDate" decimals="2">21.50</in-shp:PercentageOfShareholdingForeignPortfolioInvestors>
  <in-shp:PercentageOfShareholdingMutualFunds contextRef="OnDate" decimals="2">14.20</in-shp:PercentageOfShareholdingMutualFunds>
  <in-shp:PercentageOfShareholdingInsuranceCompanies contextRef="OnDate" decimals="2">3.10</in-shp:PercentageOfShareholdingInsuranceCompanies>
  <in-shp:PercentageOfShareholdingPublicShareholders contextRef="OnDate" decimals="2">47.16</in-shp:PercentageOfShareholdingPublicShareholders>
  <in-shp:PercentageOfShareholdingIndividualShareholders contextRef="OnDate" decimals="2">5.42</in-shp:PercentageOfShareholdingIndividualShareholders>

  <!-- Pledged: scoped to promoter context to test the heuristic -->
  <in-shp:PercentageOfShareholdingPledgedOrOtherwiseEncumbered contextRef="OnDate_Promoter" decimals="2">3.20</in-shp:PercentageOfShareholdingPledgedOrOtherwiseEncumbered>
  <in-shp:PercentageOfSharesPledgedOrOtherwiseEncumberedToTotalShares contextRef="OnDate" decimals="2">1.69</in-shp:PercentageOfSharesPledgedOrOtherwiseEncumberedToTotalShares>

  <!-- Stale-date facts must be ignored -->
  <in-shp:PercentageOfShareholdingPromoterAndPromoterGroup contextRef="StaleDate" decimals="2">99.99</in-shp:PercentageOfShareholdingPromoterAndPromoterGroup>

  <!-- Share counts -->
  <in-shp:TotalNumberOfShares contextRef="OnDate" decimals="0">4150000000</in-shp:TotalNumberOfShares>
  <in-shp:NumberOfSharesPromoterAndPromoterGroup contextRef="OnDate" decimals="0">2192300000</in-shp:NumberOfSharesPromoterAndPromoterGroup>
</xbrli:xbrl>
"""


_MANIFEST = {
    "symbol":       "TESTCO",
    "period_end":   "2026-03-31",
    "filing_id":    "S-1",
    "xbrl_url":     "https://x/test.xml",
    "broadcast_at": None,
}


def test_xbrl_extracts_percent_facts():
    rows = parse_xbrl_document(_SHP_XBRL.encode("utf-8"), _MANIFEST)
    assert len(rows) == 1
    row = rows[0]
    assert row["promoter_pct"]   == 52.84
    assert row["fii_pct"]        == 21.50
    assert row["mf_pct"]         == 14.20
    assert row["insurance_pct"]  == 3.10
    assert row["public_pct"]     == 47.16
    assert row["individual_pct"] == 5.42


def test_xbrl_pledge_heuristic():
    rows = parse_xbrl_document(_SHP_XBRL.encode("utf-8"), _MANIFEST)
    row = rows[0]
    # Promoter-context pledged → promoter_pledged_pct
    assert row["promoter_pledged_pct"]          == 3.20
    # Total-context pledged → promoter_pledged_to_total_pct
    assert row["promoter_pledged_to_total_pct"] == 1.69


def test_xbrl_share_counts():
    rows = parse_xbrl_document(_SHP_XBRL.encode("utf-8"), _MANIFEST)
    row = rows[0]
    assert row["total_shares"]    == 4_150_000_000
    assert row["promoter_shares"] == 2_192_300_000


def test_xbrl_stale_period_ignored():
    """The StaleDate context's promoter % (99.99) must NOT appear."""
    rows = parse_xbrl_document(_SHP_XBRL.encode("utf-8"), _MANIFEST)
    assert rows[0]["promoter_pct"] == 52.84


def test_xbrl_public_pct_falls_back_to_100_minus_promoter():
    """If only promoter is filed, public is derived as 100 − promoter."""
    promoter_only = """<?xml version="1.0" encoding="UTF-8"?>
<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:s="http://x">
  <xbrli:context id="C">
    <xbrli:entity><xbrli:identifier scheme="http://x">X</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:instant>2026-03-31</xbrli:instant></xbrli:period>
  </xbrli:context>
  <s:PercentageOfShareholdingPromoterAndPromoterGroup contextRef="C" decimals="2">62.50</s:PercentageOfShareholdingPromoterAndPromoterGroup>
</xbrli:xbrl>
"""
    rows = parse_xbrl_document(promoter_only.encode("utf-8"), _MANIFEST)
    assert rows[0]["promoter_pct"] == 62.50
    assert rows[0]["public_pct"]   == 37.50


def test_xbrl_zip_wrapped():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("INFY_SHP.xml", _SHP_XBRL)
    rows = parse_xbrl_document(buf.getvalue(), _MANIFEST)
    assert rows and rows[0]["promoter_pct"] == 52.84


def test_xbrl_returns_empty_on_no_matches():
    bad_manifest = {**_MANIFEST, "period_end": "2031-03-31"}
    assert parse_xbrl_document(_SHP_XBRL.encode("utf-8"), bad_manifest) == []
    assert parse_xbrl_document(b"", _MANIFEST) == []
    assert parse_xbrl_document(b"not xml", _MANIFEST) == []
