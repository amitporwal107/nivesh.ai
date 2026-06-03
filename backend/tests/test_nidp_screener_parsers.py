"""Unit tests for Screener.in HTML parsers.

Covers parse_screener_profit_loss(), parse_screener_balance_sheet(),
parse_screener_shareholding(), and their interactions with the generic
_parse_screener_section() helper.

All tests use synthetic HTML fixtures — no network, no DB.
"""
from __future__ import annotations

from typing import Optional

import pytest

from nidp.services.nse_financials.llm_extractor import (
    _parse_screener_section,
    _screener_quarter_label_to_date,
    parse_screener_balance_sheet,
    parse_screener_profit_loss,
    parse_screener_shareholding,
)

# ── Fixture HTML ─────────────────────────────────────────────────────────────

_PL_HTML = """<!DOCTYPE html><html><body>
<section id="profit-loss">
  <table class="data-table">
    <thead>
      <tr>
        <th>Particulars</th>
        <th>Mar 2021</th>
        <th>Mar 2022</th>
        <th>Mar 2023</th>
        <th>Mar 2024</th>
        <th>Mar 2025</th>
      </tr>
    </thead>
    <tbody>
      <tr><td>Sales</td><td>1,000</td><td>1,200</td><td>1,500</td><td>1,800</td><td>2,100</td></tr>
      <tr><td>Expenses</td><td>750</td><td>900</td><td>1,100</td><td>1,300</td><td>1,500</td></tr>
      <tr><td>Operating Profit</td><td>250</td><td>300</td><td>400</td><td>500</td><td>600</td></tr>
      <tr><td>OPM %</td><td>25%</td><td>25%</td><td>27%</td><td>28%</td><td>29%</td></tr>
      <tr><td>Other Income</td><td>10</td><td>15</td><td>20</td><td>25</td><td>30</td></tr>
      <tr><td>Interest</td><td>40</td><td>35</td><td>30</td><td>25</td><td>20</td></tr>
      <tr><td>Depreciation</td><td>50</td><td>55</td><td>60</td><td>65</td><td>70</td></tr>
      <tr><td>Profit before tax</td><td>170</td><td>225</td><td>330</td><td>435</td><td>540</td></tr>
      <tr><td>Tax %</td><td>25%</td><td>25%</td><td>25%</td><td>25%</td><td>25%</td></tr>
      <tr><td>Net Profit</td><td>128</td><td>169</td><td>248</td><td>326</td><td>405</td></tr>
      <tr><td>EPS in Rs</td><td>5.12</td><td>6.76</td><td>9.92</td><td>13.04</td><td>16.20</td></tr>
      <tr><td>Dividend Payout %</td><td>0%</td><td>10%</td><td>12%</td><td>15%</td><td>18%</td></tr>
    </tbody>
  </table>
</section>
</body></html>"""

_BS_HTML = """<!DOCTYPE html><html><body>
<section id="balance-sheet">
  <table class="data-table">
    <thead>
      <tr>
        <th>Particulars</th>
        <th>Mar 2022</th>
        <th>Mar 2023</th>
        <th>Mar 2024</th>
        <th>Mar 2025</th>
      </tr>
    </thead>
    <tbody>
      <tr><td>Equity Capital</td><td>100</td><td>100</td><td>100</td><td>100</td></tr>
      <tr><td>Reserves</td><td>500</td><td>650</td><td>900</td><td>1,200</td></tr>
      <tr><td>Borrowings</td><td>400</td><td>350</td><td>280</td><td>200</td></tr>
      <tr><td>Other Liabilities</td><td>150</td><td>160</td><td>170</td><td>180</td></tr>
      <tr><td>Total Liabilities</td><td>1,150</td><td>1,260</td><td>1,450</td><td>1,680</td></tr>
      <tr><td>Fixed Assets</td><td>600</td><td>650</td><td>700</td><td>750</td></tr>
      <tr><td>CWIP</td><td>50</td><td>60</td><td>70</td><td>80</td></tr>
      <tr><td>Investments</td><td>200</td><td>250</td><td>300</td><td>400</td></tr>
      <tr><td>Other Assets</td><td>300</td><td>300</td><td>380</td><td>450</td></tr>
      <tr><td>Total Assets</td><td>1,150</td><td>1,260</td><td>1,450</td><td>1,680</td></tr>
    </tbody>
  </table>
</section>
</body></html>"""

_SHP_HTML = """<!DOCTYPE html><html><body>
<section id="shareholding">
  <table class="data-table">
    <thead>
      <tr>
        <th>Particulars</th>
        <th>Sep 2024</th>
        <th>Dec 2024</th>
        <th>Mar 2025</th>
      </tr>
    </thead>
    <tbody>
      <tr><td>Promoters</td><td>55.00</td><td>55.00</td><td>55.00</td></tr>
      <tr><td>FIIs</td><td>18.50</td><td>19.00</td><td>19.50</td></tr>
      <tr><td>DIIs</td><td>12.00</td><td>11.50</td><td>11.00</td></tr>
      <tr><td>Public</td><td>14.50</td><td>14.50</td><td>14.50</td></tr>
    </tbody>
  </table>
</section>
</body></html>"""

_EMPTY_SECTION_HTML = """<!DOCTYPE html><html><body>
<section id="quarters"><p>No data</p></section>
</body></html>"""

_NO_SECTION_HTML = """<!DOCTYPE html><html><body>
<p>Company page with no financial sections</p>
</body></html>"""

_COMBINED_HTML = _PL_HTML.replace("</body></html>", "") + _BS_HTML.replace(
    "<!DOCTYPE html><html><body>", ""
).replace("</body></html>", "") + _SHP_HTML.replace(
    "<!DOCTYPE html><html><body>", ""
)


# ── parse_screener_profit_loss ───────────────────────────────────────────────

class TestParseScreenerProfitLoss:

    def test_returns_five_annual_entries(self):
        result = parse_screener_profit_loss("TESTCO", _PL_HTML)
        assert len(result) == 5

    def test_period_end_iso_format(self):
        result = parse_screener_profit_loss("TESTCO", _PL_HTML)
        ends = [r["period_end"] for r in result]
        assert ends == [
            "2021-03-31", "2022-03-31", "2023-03-31", "2024-03-31", "2025-03-31"
        ]

    def test_period_type_is_annual(self):
        result = parse_screener_profit_loss("TESTCO", _PL_HTML)
        for r in result:
            assert r["period_type"] == "annual"

    def test_revenue_values(self):
        result = parse_screener_profit_loss("TESTCO", _PL_HTML)
        assert result[0]["revenue_from_ops_cr"] == 1000.0
        assert result[4]["revenue_from_ops_cr"] == 2100.0

    def test_pat_values(self):
        result = parse_screener_profit_loss("TESTCO", _PL_HTML)
        assert result[0]["pat_cr"] == 128.0
        assert result[4]["pat_cr"] == 405.0

    def test_ebitda_maps_to_operating_profit(self):
        result = parse_screener_profit_loss("TESTCO", _PL_HTML)
        assert result[2]["ebitda_cr"] == 400.0

    def test_finance_costs(self):
        result = parse_screener_profit_loss("TESTCO", _PL_HTML)
        assert result[0]["finance_costs_cr"] == 40.0
        assert result[4]["finance_costs_cr"] == 20.0

    def test_depreciation(self):
        result = parse_screener_profit_loss("TESTCO", _PL_HTML)
        assert result[0]["depreciation_cr"] == 50.0

    def test_eps_basic(self):
        result = parse_screener_profit_loss("TESTCO", _PL_HTML)
        assert result[0]["eps_basic"] == 5.12
        assert result[4]["eps_basic"] == 16.20

    def test_consolidated_flag_propagated(self):
        result = parse_screener_profit_loss("TESTCO", _PL_HTML, consolidated=True)
        for r in result:
            assert r["consolidated"] is True

    def test_since_year_filters_old_entries(self):
        result = parse_screener_profit_loss("TESTCO", _PL_HTML, since_year=2023)
        ends = [r["period_end"] for r in result]
        assert all(e >= "2023-01-01" for e in ends)
        assert "2021-03-31" not in ends
        assert "2022-03-31" not in ends
        assert len(result) == 3

    def test_returns_empty_for_missing_section(self):
        assert parse_screener_profit_loss("TESTCO", _NO_SECTION_HTML) == []

    def test_returns_empty_for_section_without_table(self):
        assert parse_screener_profit_loss("TESTCO", _EMPTY_SECTION_HTML) == []

    def test_returns_empty_for_blank_html(self):
        assert parse_screener_profit_loss("TESTCO", "") == []

    def test_pbt_values(self):
        result = parse_screener_profit_loss("TESTCO", _PL_HTML)
        assert result[0]["pbt_cr"] == 170.0
        assert result[4]["pbt_cr"] == 540.0

    def test_other_income_values(self):
        result = parse_screener_profit_loss("TESTCO", _PL_HTML)
        assert result[0]["other_income_cr"] == 10.0

    def test_total_expenses_values(self):
        result = parse_screener_profit_loss("TESTCO", _PL_HTML)
        assert result[0]["total_expenses_cr"] == 750.0


# ── parse_screener_balance_sheet ─────────────────────────────────────────────

class TestParseScreenerBalanceSheet:

    def test_returns_four_annual_entries(self):
        result = parse_screener_balance_sheet("TESTCO", _BS_HTML)
        assert len(result) == 4

    def test_period_end_iso_format(self):
        result = parse_screener_balance_sheet("TESTCO", _BS_HTML)
        ends = [r["period_end"] for r in result]
        assert "2022-03-31" in ends
        assert "2025-03-31" in ends

    def test_equity_share_capital(self):
        result = parse_screener_balance_sheet("TESTCO", _BS_HTML)
        latest = next(r for r in result if r["period_end"] == "2025-03-31")
        assert latest["equity_share_capital_cr"] == 100.0

    def test_total_equity_is_capital_plus_reserves(self):
        result = parse_screener_balance_sheet("TESTCO", _BS_HTML)
        latest = next(r for r in result if r["period_end"] == "2025-03-31")
        # 100 + 1200 = 1300
        assert latest["total_equity_cr"] == 1300.0

    def test_borrowings(self):
        result = parse_screener_balance_sheet("TESTCO", _BS_HTML)
        earliest = next(r for r in result if r["period_end"] == "2022-03-31")
        assert earliest["long_term_debt_cr"] == 400.0
        latest = next(r for r in result if r["period_end"] == "2025-03-31")
        assert latest["long_term_debt_cr"] == 200.0

    def test_debt_declining(self):
        result = parse_screener_balance_sheet("TESTCO", _BS_HTML)
        result_sorted = sorted(result, key=lambda r: r["period_end"])
        debts = [r["long_term_debt_cr"] for r in result_sorted]
        assert debts == [400.0, 350.0, 280.0, 200.0]

    def test_returns_empty_for_missing_section(self):
        assert parse_screener_balance_sheet("TESTCO", _NO_SECTION_HTML) == []


# ── parse_screener_shareholding ──────────────────────────────────────────────

class TestParseScreenerShareholding:

    def test_returns_three_quarterly_entries(self):
        result = parse_screener_shareholding("TESTCO", _SHP_HTML)
        assert len(result) == 3

    def test_period_end_iso_format(self):
        result = parse_screener_shareholding("TESTCO", _SHP_HTML)
        ends = sorted(r["period_end"] for r in result)
        assert ends == ["2024-09-30", "2024-12-31", "2025-03-31"]

    def test_promoter_pct(self):
        result = parse_screener_shareholding("TESTCO", _SHP_HTML)
        latest = next(r for r in result if r["period_end"] == "2025-03-31")
        assert latest["promoter_pct"] == 55.0

    def test_fii_pct(self):
        result = parse_screener_shareholding("TESTCO", _SHP_HTML)
        latest = next(r for r in result if r["period_end"] == "2025-03-31")
        assert latest["fii_pct"] == 19.5

    def test_dii_pct(self):
        result = parse_screener_shareholding("TESTCO", _SHP_HTML)
        latest = next(r for r in result if r["period_end"] == "2025-03-31")
        assert latest["dii_pct"] == 11.0

    def test_promoter_stable_over_quarters(self):
        result = parse_screener_shareholding("TESTCO", _SHP_HTML)
        promoter_vals = [r["promoter_pct"] for r in result]
        assert all(v == 55.0 for v in promoter_vals)

    def test_returns_empty_for_missing_section(self):
        assert parse_screener_shareholding("TESTCO", _NO_SECTION_HTML) == []


# ── _parse_screener_section (generic) ────────────────────────────────────────

class TestParseScreenerSection:

    def test_returns_col_labels_and_row_map(self):
        result = _parse_screener_section(_PL_HTML, "profit-loss")
        assert result is not None
        col_labels, raw_table = result
        assert "Mar 2025" in col_labels
        assert any("sales" in k for k in raw_table)

    def test_returns_none_for_wrong_id(self):
        assert _parse_screener_section(_PL_HTML, "balance-sheet") is None

    def test_row_label_normalised_to_lowercase(self):
        result = _parse_screener_section(_PL_HTML, "profit-loss")
        assert result is not None
        _, raw_table = result
        # All keys should be lowercase
        for k in raw_table:
            assert k == k.lower(), f"key not lowercase: {k!r}"

    def test_numeric_values_parsed_correctly(self):
        result = _parse_screener_section(_BS_HTML, "balance-sheet")
        assert result is not None
        _, raw_table = result
        # "equity capital" row: 100, 100, 100, 100
        eq_row = next((v for k, v in raw_table.items() if "equity capital" in k), None)
        assert eq_row is not None
        assert all(v == 100.0 for v in eq_row)

    def test_commas_stripped_from_numbers(self):
        result = _parse_screener_section(_BS_HTML, "balance-sheet")
        assert result is not None
        _, raw_table = result
        # "reserves" Mar 2025 = 1,200 → should parse as 1200.0
        reserves_row = next((v for k, v in raw_table.items() if "reserves" in k), None)
        assert reserves_row is not None
        assert 1200.0 in reserves_row

    def test_correct_column_count(self):
        result = _parse_screener_section(_PL_HTML, "profit-loss")
        assert result is not None
        col_labels, raw_table = result
        assert len(col_labels) == 5
        for row in raw_table.values():
            assert len(row) == 5


# ── Integration: combined HTML with all sections ─────────────────────────────

class TestCombinedHTMLParsing:
    """Verify all three parsers work correctly against a single combined HTML blob
    (as it would be fetched from a real Screener.in page)."""

    def test_profit_loss_on_combined_html(self):
        result = parse_screener_profit_loss("TESTCO", _COMBINED_HTML)
        assert len(result) == 5
        assert result[-1]["revenue_from_ops_cr"] == 2100.0

    def test_balance_sheet_on_combined_html(self):
        result = parse_screener_balance_sheet("TESTCO", _COMBINED_HTML)
        assert len(result) == 4
        latest = next(r for r in result if r["period_end"] == "2025-03-31")
        assert latest["total_equity_cr"] == 1300.0

    def test_shareholding_on_combined_html(self):
        result = parse_screener_shareholding("TESTCO", _COMBINED_HTML)
        assert len(result) == 3
        latest = next(r for r in result if r["period_end"] == "2025-03-31")
        assert latest["promoter_pct"] == 55.0

    def test_parsers_are_independent(self):
        """Each parser extracts its own section without contaminating others."""
        pl = parse_screener_profit_loss("TESTCO", _COMBINED_HTML)
        bs = parse_screener_balance_sheet("TESTCO", _COMBINED_HTML)
        shp = parse_screener_shareholding("TESTCO", _COMBINED_HTML)
        # P&L entries should have revenue; BS entries should have equity; shp should have promoter_pct
        assert all("revenue_from_ops_cr" in r for r in pl)
        assert all("equity_share_capital_cr" in r for r in bs)
        assert all("promoter_pct" in r for r in shp)


# ── Revenue CAGR computation (integration with primitives engine) ─────────────

class TestProfitLossForCAGRComputation:
    """Verify that data returned by parse_screener_profit_loss() is sufficient
    to compute the 3-year revenue CAGR and profit margin trend primitives."""

    def test_three_year_revenue_cagr(self):
        """revenue_growth_3y_cagr = ((rev_t / rev_t-3) ** (1/3) - 1) * 100"""
        result = parse_screener_profit_loss("TESTCO", _PL_HTML)
        by_year = {r["period_end"]: r for r in result}
        rev_2022 = by_year["2022-03-31"]["revenue_from_ops_cr"]
        rev_2025 = by_year["2025-03-31"]["revenue_from_ops_cr"]
        cagr = ((rev_2025 / rev_2022) ** (1 / 3) - 1) * 100
        assert abs(cagr - 20.51) < 0.1  # 1200→2100 over 3y ≈ 20.5%

    def test_profit_margin_trend_fields_present(self):
        """profit_margin_trend needs pat_cr and revenue_from_ops_cr."""
        result = parse_screener_profit_loss("TESTCO", _PL_HTML)
        for r in result:
            assert r.get("revenue_from_ops_cr") is not None
            assert r.get("pat_cr") is not None

    def test_debt_trend_fields_in_balance_sheet(self):
        """debt_trend needs long_term_debt_cr over multiple years."""
        result = parse_screener_balance_sheet("TESTCO", _BS_HTML)
        sorted_result = sorted(result, key=lambda r: r["period_end"])
        debts = [r["long_term_debt_cr"] for r in sorted_result if r.get("long_term_debt_cr") is not None]
        assert len(debts) >= 2  # need at least 2 points for trend


# ── _screener_quarter_label_to_date — format coverage ────────────────────────

class TestQuarterLabelToDate:
    """Ensure all Screener.in column-header formats parse to correct ISO dates."""

    # Standard "Mon YYYY" format
    def test_standard_mar_2025(self):
        assert _screener_quarter_label_to_date("Mar 2025") == "2025-03-31"

    def test_standard_dec_2024(self):
        assert _screener_quarter_label_to_date("Dec 2024") == "2024-12-31"

    def test_standard_jun_2023(self):
        assert _screener_quarter_label_to_date("Jun 2023") == "2023-06-30"

    def test_standard_sep_2022(self):
        assert _screener_quarter_label_to_date("Sep 2022") == "2022-09-30"

    # FY quarter format "Q{N} FY{YY}" — Indian FY (Apr-Mar)
    def test_fy_q1_fy24(self):
        # Q1 FY24 = Apr-Jun 2023 → period_end Jun 30, 2023
        assert _screener_quarter_label_to_date("Q1 FY24") == "2023-06-30"

    def test_fy_q2_fy24(self):
        assert _screener_quarter_label_to_date("Q2 FY24") == "2023-09-30"

    def test_fy_q3_fy24(self):
        assert _screener_quarter_label_to_date("Q3 FY24") == "2023-12-31"

    def test_fy_q4_fy24(self):
        # Q4 FY24 = Jan-Mar 2024 → period_end Mar 31, 2024
        assert _screener_quarter_label_to_date("Q4 FY24") == "2024-03-31"

    def test_fy_q1_fy26(self):
        assert _screener_quarter_label_to_date("Q1 FY26") == "2025-06-30"

    def test_fy_q4_fy26(self):
        assert _screener_quarter_label_to_date("Q4 FY26") == "2026-03-31"

    def test_fy_no_space_q1fy24(self):
        # "Q1FY24" variant (no space between Q and FY)
        assert _screener_quarter_label_to_date("Q1FY24") == "2023-06-30"

    # Annual FY format
    def test_annual_fy24(self):
        assert _screener_quarter_label_to_date("FY24") == "2024-03-31"

    def test_annual_fy25(self):
        assert _screener_quarter_label_to_date("FY25") == "2025-03-31"

    def test_annual_fy2024_four_digit(self):
        assert _screener_quarter_label_to_date("FY2024") == "2024-03-31"

    # Labels that should return None
    def test_ttm_returns_none(self):
        assert _screener_quarter_label_to_date("TTM") is None

    def test_annual_string_returns_none(self):
        assert _screener_quarter_label_to_date("Annual") is None

    def test_empty_returns_none(self):
        assert _screener_quarter_label_to_date("") is None

    def test_garbage_returns_none(self):
        assert _screener_quarter_label_to_date("Particulars") is None

    # Edge: Q1 FY24 is in window since 2023-05-28 (Jun 30 2023 > May 28 2023)
    def test_q1_fy24_is_after_since_date(self):
        result = _screener_quarter_label_to_date("Q1 FY24")
        assert result is not None
        assert result > "2023-05-28"
