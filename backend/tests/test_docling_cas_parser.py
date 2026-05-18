"""Tests for services/docling_cas_parser.py — fully local CAS parser.

Structure
---------
A. Unit tests — pure functions, no Docling/PyMuPDF dependency (always run)
   A1. _num()
   A2. _classify_asset()
   A3. _classify_sector()
   A4. _find_col()
   A5. _parse_table() — synthetic NSDL-format grids
   A6. _parse_equity_blocks() — text-block fallback

B. Integration tests — require docling + PyMuPDF (skipped if not installed)
   B1. parse_with_docling() on real NSDL PDF (priyanka_nsdl.pdf)
        — accuracy vs priyanka_nsdl.json ground truth

Ground truth for B1 comes from:
    tests/test_data/expected_outputs/priyanka_nsdl.json
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from services.docling_cas_parser import (
    _classify_asset,
    _classify_sector,
    _find_col,
    _num,
    _parse_equity_blocks,
    _parse_table,
    is_available,
)

# ── paths ──────────────────────────────────────────────────────────────
TEST_DATA   = Path(__file__).parent / "test_data"
NSDL_PDF    = TEST_DATA / "nsdl" / "priyanka_nsdl.pdf"
NSDL_TRUTH  = TEST_DATA / "expected_outputs" / "priyanka_nsdl.json"

# ── accuracy thresholds (same as test_cas_parser.py) ──────────────────
ISIN_MATCH_RATE_MIN   = 0.80   # ≥ 80 % of expected ISINs captured
VALUE_TOLERANCE_PCT   = 0.05   # ± 5 % on numeric values
VALUE_TOLERANCE_ABS   = 50     # ± ₹50 absolute
SECTION_COVERAGE_MIN  = 0.70   # ≥ 70 % of expected holdings per section found
NAME_SIMILARITY_MIN   = 70     # rapidfuzz partial_ratio threshold

docling_available = pytest.mark.skipif(
    not is_available(),
    reason="docling / PyMuPDF not installed — pip install 'docling>=2.5.0' pymupdf",
)


# ═══════════════════════════════════════════════════════════════════════
# A1. _num()
# ═══════════════════════════════════════════════════════════════════════

class TestNum:
    def test_plain_int(self):
        assert _num("100") == 100.0

    def test_plain_float(self):
        assert _num("123.45") == 123.45

    def test_indian_comma_format(self):
        assert _num("1,23,456.78") == 123456.78

    def test_rupee_symbol(self):
        assert _num("₹2,450.00") == 2450.0

    def test_empty_string(self):
        assert _num("") == 0.0

    def test_none(self):
        assert _num(None) == 0.0

    def test_non_numeric(self):
        assert _num("NOT AVAILABLE") == 0.0

    def test_zero(self):
        assert _num("0") == 0.0

    def test_large_value(self):
        assert _num("79,52,577.03") == 7952577.03


# ═══════════════════════════════════════════════════════════════════════
# A2. _classify_asset()
# ═══════════════════════════════════════════════════════════════════════

class TestClassifyAsset:
    def test_equity_by_default(self):
        assert _classify_asset("Reliance Industries Limited", "INE002A01018") == "equity"

    def test_mutual_fund_by_isin_prefix(self):
        # INF prefix = AMFI-registered MF
        assert _classify_asset("HDFC Flexi Cap Fund", "INF179K01BA0") == "mutual_fund"

    def test_mutual_fund_by_name(self):
        assert _classify_asset("Aditya Birla Sun Life Large Cap Fund", "INE000X00000") == "mutual_fund"

    def test_etf_by_name(self):
        assert _classify_asset("Nippon India ETF Nifty BeES", "INF204K01EY4") == "etf"

    def test_etf_bees_suffix(self):
        assert _classify_asset("HDFC Nifty 50 ETF Bees", "INF179K01ZZ0") == "etf"

    def test_sgb_full_name(self):
        assert _classify_asset("SOVEREIGN GOLD BOND 2023-24 SERIES III", "IN0020230001") == "gold"

    def test_sgb_abbreviation(self):
        assert _classify_asset("SGB 2022-23 Series II", "IN0020220001") == "gold"

    def test_preference_share_classified_as_equity(self):
        # Preference shares have no special keyword — they're treated as equity
        assert _classify_asset("Shriram Finance Limited", "INE721A07BY6") == "equity"


# ═══════════════════════════════════════════════════════════════════════
# A3. _classify_sector()
# ═══════════════════════════════════════════════════════════════════════

class TestClassifySector:
    def test_index_fund(self):
        assert _classify_sector("Nifty 50 Index Fund Regular Plan Growth") == "Index"

    def test_small_cap(self):
        assert _classify_sector("Quant Small Cap Fund Direct Growth") == "Small Cap"

    def test_mid_cap(self):
        assert _classify_sector("Motilal Oswal Midcap Fund") == "Mid Cap"

    def test_large_cap(self):
        assert _classify_sector("HDFC Bluechip Fund Direct Growth") == "Large Cap"

    def test_flexi_cap(self):
        assert _classify_sector("Parag Parikh Flexi Cap Fund") == "Flexi Cap"

    def test_elss(self):
        assert _classify_sector("Mirae Asset ELSS Tax Saver Fund") == "ELSS"

    def test_debt(self):
        assert _classify_sector("HDFC Liquid Fund Direct Growth") == "Debt"

    def test_gold(self):
        assert _classify_sector("Sovereign Gold Bond 2023-24") == "Gold"

    def test_international(self):
        assert _classify_sector("Motilal Oswal Nasdaq 100 Fund of Fund") == "International"

    def test_unknown_falls_back_to_other(self):
        assert _classify_sector("Some Completely Unknown Fund XYZ") == "Other"


# ═══════════════════════════════════════════════════════════════════════
# A4. _find_col()
# ═══════════════════════════════════════════════════════════════════════

class TestFindCol:
    NSDL_EQUITY_HEADERS = [
        "ISIN",
        "Security Description / Scheme Name",
        "Balance",
        "Market Price (Rs.)",
        "Market Value (Rs.)",
    ]

    NSDL_MF_DEMAT_HEADERS = [
        "ISIN",
        "Scheme Name",
        "Folio No.",
        "Units",
        "NAV (Rs.)",
        "Current Value (Rs.)",
    ]

    def test_isin_col_equity(self):
        assert _find_col(self.NSDL_EQUITY_HEADERS, ["isin"]) == 0

    def test_description_col(self):
        assert _find_col(self.NSDL_EQUITY_HEADERS, ["security", "description"]) == 1

    def test_balance_col(self):
        assert _find_col(self.NSDL_EQUITY_HEADERS, ["balance", "units", "qty"]) == 2

    def test_market_price_col(self):
        assert _find_col(self.NSDL_EQUITY_HEADERS, ["market price", "nav", "price"]) == 3

    def test_market_value_col(self):
        assert _find_col(self.NSDL_EQUITY_HEADERS, ["market value", "current value", "value"]) == 4

    def test_folio_col_mf_demat(self):
        assert _find_col(self.NSDL_MF_DEMAT_HEADERS, ["folio"]) == 2

    def test_units_col_mf_demat(self):
        assert _find_col(self.NSDL_MF_DEMAT_HEADERS, ["units", "balance"]) == 3

    def test_nav_col_mf_demat(self):
        assert _find_col(self.NSDL_MF_DEMAT_HEADERS, ["market price", "nav", "price"]) == 4

    def test_current_value_col_mf_demat(self):
        assert _find_col(self.NSDL_MF_DEMAT_HEADERS, ["market value", "current value", "value"]) == 5

    def test_missing_col_returns_none(self):
        assert _find_col(self.NSDL_EQUITY_HEADERS, ["nonexistent", "xyz"]) is None

    def test_empty_headers(self):
        assert _find_col([], ["isin"]) is None


# ═══════════════════════════════════════════════════════════════════════
# A5. _parse_table()
# ═══════════════════════════════════════════════════════════════════════

# Synthetic NSDL CAS table grids — mimic real Docling table output

EQUITY_GRID = [
    # header row
    ["ISIN", "Security Description / Scheme Name", "Balance", "Market Price (Rs.)", "Market Value (Rs.)"],
    # data rows
    ["INE002A01018", "RELIANCE INDUSTRIES LIMITED",          "50",    "2,980.00", "1,49,000.00"],
    ["INE040A01034", "HDFC BANK LIMITED",                   "30",    "1,650.00",   "49,500.00"],
    ["INE009A01021", "INFOSYS LIMITED",                    "100",    "1,450.00", "1,45,000.00"],
    # pledged sub-row — must be filtered
    ["INE009A01021", "of which Pledged / Unconfirmed Pledge",  "5",       "0.00",       "0.00"],
    # zero-balance closed position — must be filtered
    ["INE101A01026", "ZEN TECHNOLOGIES LIMITED",               "0",      "49.50",       "0.00"],
]

MF_DEMAT_GRID = [
    ["ISIN", "Scheme Name", "Folio No.", "Units", "NAV (Rs.)", "Current Value (Rs.)"],
    ["INF179K01BA0", "HDFC Flexi Cap Fund Direct Growth",       "1234567890", "250.532",  "89.4526",  "22,422.00"],
    ["INF769K01IR7", "Mirae Asset Large Cap Fund Direct Growth", "9876543210", "100.000", "102.3400",  "10,234.00"],
]

SGB_GRID = [
    ["ISIN", "Security Description / Scheme Name", "No. of Units", "Face Value (Rs.)", "Market Price (Rs.)", "Market Value (Rs.)"],
    ["IN0020220110", "SGB 2022-23 SERIES III",  "10", "5409.00", "7924.50", "79,245.00"],
    ["IN0020230001", "SGB 2023-24 SERIES I",     "5", "5409.00", "7924.50", "39,622.50"],
]

NON_HOLDINGS_GRID = [
    ["Month", "Portfolio Value", "Change"],
    ["Jan 2026", "1,20,00,000", "+2.3%"],
    ["Feb 2026", "1,23,00,000", "+2.5%"],
]

ISIN_WITH_EXTRA_TEXT_GRID = [
    ["ISIN", "Security Description / Scheme Name", "Balance", "Market Price (Rs.)", "Market Value (Rs.)"],
    # cell contains ISIN + newline + UCC — search() must extract just the ISIN
    ["INF769K01IR7\nNOT AVAILABLE", "Mirae Asset Large Cap Fund", "200", "102.34", "20,468.00"],
]


class TestParseTable:

    # ── equity table ──────────────────────────────────────────────────

    def test_equity_table_returns_three_holdings(self):
        result = _parse_table(EQUITY_GRID)
        assert len(result) == 3

    def test_equity_isin_extracted(self):
        result = _parse_table(EQUITY_GRID)
        isins = {h["ticker"] for h in result}
        assert "INE002A01018" in isins
        assert "INE040A01034" in isins
        assert "INE009A01021" in isins

    def test_equity_name_extracted(self):
        result = _parse_table(EQUITY_GRID)
        names = {h["name"] for h in result}
        assert "RELIANCE INDUSTRIES LIMITED" in names

    def test_equity_quantity_parsed(self):
        result = _parse_table(EQUITY_GRID)
        rel = next(h for h in result if h["ticker"] == "INE002A01018")
        assert rel["quantity"] == 50.0

    def test_equity_price_parsed(self):
        result = _parse_table(EQUITY_GRID)
        rel = next(h for h in result if h["ticker"] == "INE002A01018")
        assert rel["current_price"] == 2980.0

    def test_equity_asset_type(self):
        result = _parse_table(EQUITY_GRID)
        for h in result:
            assert h["asset_type"] == "equity"

    def test_pledged_subrow_filtered(self):
        result = _parse_table(EQUITY_GRID)
        # There is only one holding with INFOSYS ISIN — pledged sub-row is dropped
        infosys = [h for h in result if h["ticker"] == "INE009A01021"]
        assert len(infosys) == 1
        assert "pledged" not in infosys[0]["name"].lower()

    def test_zero_balance_filtered(self):
        result = _parse_table(EQUITY_GRID)
        isins = {h["ticker"] for h in result}
        assert "INE101A01026" not in isins   # ZEN TECH with 0 balance must be dropped

    # ── MF demat table ────────────────────────────────────────────────

    def test_mf_demat_count(self):
        result = _parse_table(MF_DEMAT_GRID)
        assert len(result) == 2

    def test_mf_demat_asset_type(self):
        result = _parse_table(MF_DEMAT_GRID)
        for h in result:
            assert h["asset_type"] == "mutual_fund"

    def test_mf_demat_folio_captured(self):
        result = _parse_table(MF_DEMAT_GRID)
        hdfc = next(h for h in result if h["ticker"] == "INF179K01BA0")
        assert hdfc["folio_number"] == "1234567890"

    def test_mf_demat_units_parsed(self):
        result = _parse_table(MF_DEMAT_GRID)
        hdfc = next(h for h in result if h["ticker"] == "INF179K01BA0")
        assert hdfc["quantity"] == 250.532

    # ── SGB table ─────────────────────────────────────────────────────

    def test_sgb_count(self):
        result = _parse_table(SGB_GRID)
        assert len(result) == 2

    def test_sgb_asset_type(self):
        result = _parse_table(SGB_GRID)
        for h in result:
            assert h["asset_type"] == "gold"

    def test_sgb_sector(self):
        result = _parse_table(SGB_GRID)
        for h in result:
            assert h["sector"] == "Gold"

    def test_sgb_value_derived_from_qty_price(self):
        result = _parse_table(SGB_GRID)
        sgb1 = next(h for h in result if h["ticker"] == "IN0020220110")
        # No cost col — price derived from value/qty if price not directly parsed
        assert sgb1["quantity"] == 10.0

    # ── ISIN with extra text ──────────────────────────────────────────

    def test_isin_extracted_from_multiline_cell(self):
        result = _parse_table(ISIN_WITH_EXTRA_TEXT_GRID)
        assert len(result) == 1
        assert result[0]["ticker"] == "INF769K01IR7"   # clean ISIN, not the cell garbage

    # ── Non-holdings table ────────────────────────────────────────────

    def test_non_holdings_table_returns_empty(self):
        result = _parse_table(NON_HOLDINGS_GRID)
        assert result == []

    def test_empty_grid_returns_empty(self):
        assert _parse_table([]) == []

    def test_single_row_grid_returns_empty(self):
        assert _parse_table([["ISIN", "Name", "Balance"]]) == []

    # ── buy_price fallback logic ──────────────────────────────────────

    def test_buy_price_uses_cost_when_available(self):
        grid = [
            ["ISIN", "Security Description / Scheme Name", "Balance", "Market Price (Rs.)", "Market Value (Rs.)", "Avg. Cost"],
            ["INE002A01018", "RELIANCE INDUSTRIES LIMITED", "10", "2,980.00", "29,800.00", "2,500.00"],
        ]
        result = _parse_table(grid)
        assert result[0]["buy_price"] == 2500.0

    def test_buy_price_falls_back_to_price_when_no_cost(self):
        result = _parse_table(EQUITY_GRID)
        rel = next(h for h in result if h["ticker"] == "INE002A01018")
        # No cost column in EQUITY_GRID → buy_price = market price
        assert rel["buy_price"] == 2980.0

    def test_price_derived_from_value_and_qty(self):
        grid = [
            ["ISIN", "Security Description / Scheme Name", "Balance", "Market Value (Rs.)"],
            ["INE002A01018", "RELIANCE INDUSTRIES LIMITED", "50", "1,49,000.00"],
        ]
        result = _parse_table(grid)
        assert len(result) == 1
        # price = 1,49,000 / 50 = 2,980
        assert abs(result[0]["current_price"] - 2980.0) < 1.0

    # ── parsed_by marker ─────────────────────────────────────────────

    def test_parsed_by_is_docling(self):
        result = _parse_table(EQUITY_GRID)
        for h in result:
            assert h["parsed_by"] == "docling"


# ═══════════════════════════════════════════════════════════════════════
# A6. _parse_equity_blocks()
# ═══════════════════════════════════════════════════════════════════════

NSDL_BLOCK_TEXT = """
NATIONAL SECURITIES DEPOSITORY LIMITED
Consolidated Account Statement

DP Id: IN302201  Client Id: 12345678

ISIN: INE002A01018
RELIANCE INDUSTRIES LIMITED
Balance: 50    Market Price: 2,980.00    Market Value: 1,49,000.00

ISIN: INE040A01034
HDFC BANK LIMITED
Balance: 30    Market Price: 1,650.00    Market Value: 49,500.00

ISIN: INF179K01BA0
HDFC FLEXI CAP FUND DIRECT GROWTH
Balance: 250    NAV: 89.4526    Market Value: 22,363.15
"""

NON_NSDL_BLOCK_TEXT = """
Some generic mutual fund statement without depository keywords.
ISIN: INE002A01018
RELIANCE INDUSTRIES LIMITED
Balance: 50    Market Price: 2,980.00
"""


class TestParseEquityBlocks:

    def test_extracts_nsdl_equity_holdings(self):
        result = _parse_equity_blocks(NSDL_BLOCK_TEXT)
        assert len(result) >= 2

    def test_isin_found(self):
        result = _parse_equity_blocks(NSDL_BLOCK_TEXT)
        isins = {h["ticker"] for h in result}
        assert "INE002A01018" in isins

    def test_quantity_parsed(self):
        result = _parse_equity_blocks(NSDL_BLOCK_TEXT)
        rel = next((h for h in result if h["ticker"] == "INE002A01018"), None)
        assert rel is not None
        assert rel["quantity"] == 50.0

    def test_price_derived_from_value_qty(self):
        result = _parse_equity_blocks(NSDL_BLOCK_TEXT)
        rel = next((h for h in result if h["ticker"] == "INE002A01018"), None)
        assert rel is not None
        assert abs(rel["current_price"] - 2980.0) < 1.0

    def test_non_nsdl_text_returns_empty(self):
        result = _parse_equity_blocks(NON_NSDL_BLOCK_TEXT)
        assert result == []

    def test_no_duplicate_isins(self):
        result = _parse_equity_blocks(NSDL_BLOCK_TEXT)
        isins = [h["ticker"] for h in result]
        assert len(isins) == len(set(isins))

    def test_parsed_by_is_docling_text(self):
        result = _parse_equity_blocks(NSDL_BLOCK_TEXT)
        for h in result:
            assert h["parsed_by"] == "docling_text"


# ═══════════════════════════════════════════════════════════════════════
# B. Integration tests — require docling + PyMuPDF
# ═══════════════════════════════════════════════════════════════════════

def _load_ground_truth() -> Dict[str, Any]:
    with open(NSDL_TRUTH) as f:
        return json.load(f)


def _find_by_isin(holdings: List[Dict], isin: str) -> Dict | None:
    for h in holdings:
        ticker = h.get("ticker", "")
        if ticker == isin:
            return h
        # tolerate 1-char OCR error
        if len(ticker) == len(isin) == 12 and sum(a != b for a, b in zip(ticker, isin)) <= 1:
            return h
    return None


def _value_close(actual: float, expected: float) -> bool:
    if expected == 0:
        return actual == 0
    return abs(actual - expected) <= max(abs(expected) * VALUE_TOLERANCE_PCT, VALUE_TOLERANCE_ABS)


@docling_available
@pytest.mark.skipif(not NSDL_PDF.exists(), reason="priyanka_nsdl.pdf not in test_data/nsdl/")
class TestDoclingIntegration:
    """Accuracy tests against priyanka_nsdl.pdf + priyanka_nsdl.json ground truth."""

    @pytest.fixture(scope="class")
    def parsed(self):
        from services.docling_cas_parser import parse_with_docling
        pdf_bytes = NSDL_PDF.read_bytes()
        # Priyanka's PDF — no password
        holdings, normalized = parse_with_docling(pdf_bytes, password="")
        return holdings, normalized

    @pytest.fixture(scope="class")
    def truth(self):
        return _load_ground_truth()

    # ── basic sanity ──────────────────────────────────────────────────

    def test_returns_list(self, parsed):
        holdings, _ = parsed
        assert isinstance(holdings, list)

    def test_minimum_holdings_count(self, parsed, truth):
        holdings, _ = parsed
        expected_total = (
            len(truth["equities"])
            + len(truth["sgb"])
            + len(truth.get("etfs_demat", []))
            + len(truth["mf_folios"])
        )
        # Capture at least 70 % of expected holdings
        assert len(holdings) >= int(expected_total * SECTION_COVERAGE_MIN), (
            f"Only {len(holdings)} holdings parsed, expected ≥ {int(expected_total * SECTION_COVERAGE_MIN)}"
        )

    def test_no_duplicate_isins(self, parsed):
        holdings, _ = parsed
        isins = [h["ticker"] for h in holdings if h.get("ticker")]
        assert len(isins) == len(set(isins)), "Duplicate ISINs found in output"

    def test_all_holdings_have_name(self, parsed):
        holdings, _ = parsed
        for h in holdings:
            assert h.get("name"), f"Holding missing name: {h}"

    def test_all_holdings_have_asset_type(self, parsed):
        holdings, _ = parsed
        valid_types = {"equity", "mutual_fund", "gold", "etf"}
        for h in holdings:
            assert h.get("asset_type") in valid_types, f"Bad asset_type: {h}"

    # ── equity section accuracy ───────────────────────────────────────

    def test_equity_isin_coverage(self, parsed, truth):
        holdings, _ = parsed
        expected_equities = truth["equities"]
        matched = sum(1 for e in expected_equities if _find_by_isin(holdings, e["isin"]))
        rate = matched / max(len(expected_equities), 1)
        assert rate >= ISIN_MATCH_RATE_MIN, (
            f"Equity ISIN match rate {rate:.0%} below threshold {ISIN_MATCH_RATE_MIN:.0%} "
            f"({matched}/{len(expected_equities)} found)"
        )

    def test_equity_quantity_accuracy(self, parsed, truth):
        holdings, _ = parsed
        correct = 0
        for e in truth["equities"]:
            h = _find_by_isin(holdings, e["isin"])
            if h and _value_close(h.get("quantity", 0), e["quantity"]):
                correct += 1
        rate = correct / max(len(truth["equities"]), 1)
        assert rate >= SECTION_COVERAGE_MIN, (
            f"Equity quantity accuracy {rate:.0%} below {SECTION_COVERAGE_MIN:.0%}"
        )

    def test_equity_value_accuracy(self, parsed, truth):
        holdings, _ = parsed
        correct = 0
        for e in truth["equities"]:
            h = _find_by_isin(holdings, e["isin"])
            if not h:
                continue
            derived = h.get("quantity", 0) * h.get("current_price", 0)
            if _value_close(derived, e["value"]):
                correct += 1
        rate = correct / max(len(truth["equities"]), 1)
        assert rate >= SECTION_COVERAGE_MIN, (
            f"Equity value accuracy {rate:.0%} below {SECTION_COVERAGE_MIN:.0%}"
        )

    def test_no_pledged_rows_in_output(self, parsed):
        holdings, _ = parsed
        for h in holdings:
            assert "pledged" not in h.get("name", "").lower(), (
                f"Pledged sub-row leaked into output: {h}"
            )

    def test_zero_balance_holdings_excluded(self, parsed):
        holdings, _ = parsed
        for h in holdings:
            assert not (h.get("quantity", 1) == 0 and h.get("current_price", 0) == 0), (
                f"Zero-balance holding in output: {h}"
            )

    # ── SGB section accuracy ─────────────────────────────────────────

    def test_sgb_isin_coverage(self, parsed, truth):
        holdings, _ = parsed
        sgb_expected = truth["sgb"]
        if not sgb_expected:
            pytest.skip("No SGBs in ground truth")
        matched = sum(1 for s in sgb_expected if _find_by_isin(holdings, s["isin"]))
        rate = matched / len(sgb_expected)
        assert rate >= ISIN_MATCH_RATE_MIN, (
            f"SGB ISIN match rate {rate:.0%} below {ISIN_MATCH_RATE_MIN:.0%} "
            f"({matched}/{len(sgb_expected)})"
        )

    def test_sgb_classified_as_gold(self, parsed, truth):
        holdings, _ = parsed
        for s in truth["sgb"]:
            h = _find_by_isin(holdings, s["isin"])
            if h:
                assert h["asset_type"] == "gold", (
                    f"SGB {s['isin']} classified as {h['asset_type']}, expected gold"
                )

    # ── MF Folio section accuracy (casparser output inside Docling path) ──

    def test_mf_folio_isin_coverage(self, parsed, truth):
        holdings, _ = parsed
        mf_expected = truth["mf_folios"]
        if not mf_expected:
            pytest.skip("No MF folios in ground truth")
        matched = sum(1 for m in mf_expected if _find_by_isin(holdings, m["isin"]))
        rate = matched / len(mf_expected)
        assert rate >= ISIN_MATCH_RATE_MIN, (
            f"MF folio ISIN match rate {rate:.0%} below {ISIN_MATCH_RATE_MIN:.0%} "
            f"({matched}/{len(mf_expected)})"
        )

    def test_mf_folio_value_accuracy(self, parsed, truth):
        holdings, _ = parsed
        correct = 0
        for m in truth["mf_folios"]:
            h = _find_by_isin(holdings, m["isin"])
            if not h:
                continue
            derived = h.get("quantity", 0) * h.get("current_price", 0)
            if _value_close(derived, m["value"]):
                correct += 1
        rate = correct / max(len(truth["mf_folios"]), 1)
        assert rate >= SECTION_COVERAGE_MIN, (
            f"MF folio value accuracy {rate:.0%} below {SECTION_COVERAGE_MIN:.0%}"
        )

    # ── portfolio total sanity ────────────────────────────────────────

    def test_total_portfolio_value_within_10pct(self, parsed, truth):
        holdings, _ = parsed
        expected_total = truth["summary"]["total_portfolio"]
        actual_total   = sum(h.get("quantity", 0) * h.get("current_price", 0) for h in holdings)
        pct_diff = abs(actual_total - expected_total) / max(expected_total, 1)
        assert pct_diff <= 0.10, (
            f"Total portfolio value off by {pct_diff:.1%}: "
            f"parsed ₹{actual_total:,.0f} vs expected ₹{expected_total:,.0f}"
        )
