"""Screener.in cash-flow parser — nidp.services.nse_financials.llm_extractor.

The fixture is the real #cash-flow section from Screener's KPEL consolidated page.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from nidp.services.nse_financials.llm_extractor import parse_screener_cash_flow  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "screener_cashflow_kpel.html")


@pytest.fixture(scope="module")
def rows():
    with open(FIXTURE) as fh:
        return parse_screener_cash_flow("KPEL", fh.read(), consolidated=True)


def test_parses_every_annual_column(rows):
    assert len(rows) == 12


def test_periods_are_fiscal_year_ends(rows):
    assert all(r["period_end"].endswith("-03-31") for r in rows)
    assert rows[-1]["period_end"] == "2026-03-31"


def test_consolidated_flag_is_preserved(rows):
    assert all(r["consolidated"] is True for r in rows)


def test_columns_are_aligned_not_just_parsed(rows):
    """CFO + CFI + CFF must reconcile to the reported net change.

    This is the assertion that catches a column-offset bug: values can all parse
    as floats while belonging to the wrong years.
    """
    for r in rows:
        parts = (r["cfo_cr"], r["cfi_cr"], r["cff_cr"], r["net_change_cash_cr"])
        if any(p is None for p in parts):
            continue
        assert abs((r["cfo_cr"] + r["cfi_cr"] + r["cff_cr"]) - r["net_change_cash_cr"]) <= 1.0, r


def test_capex_is_derived_from_free_cash_flow(rows):
    latest = rows[-1]
    assert latest["cfo_cr"] == 123.0
    assert latest["capex_cr"] == 218.0        # CFO 123 - FCF (-95)


def test_missing_section_returns_empty_list():
    assert parse_screener_cash_flow("NOSUCH", "<html><body>no sections</body></html>") == []


def test_rows_without_any_cashflow_figure_are_dropped():
    html = """<section id="cash-flow"><table class="data-table">
      <thead><tr><th></th><th>Mar 2025</th></tr></thead>
      <tbody><tr><td>Some Other Row</td><td>5</td></tr></tbody>
    </table></section>"""
    assert parse_screener_cash_flow("EMPTY", html) == []
