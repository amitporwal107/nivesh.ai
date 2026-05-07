"""Tests for the RBI yields HTML parser. Skipped if bs4 isn't
installed (CI / minimal envs). Live RBI page structure is
fingerprinted via fixtures rather than bare HTML to keep the parser
honest as RBI rotates layouts."""
from __future__ import annotations

import pytest

bs4 = pytest.importorskip("bs4")  # noqa: F841

from nidp.services.rbi_yields.parser import parse_rbi_yields


def test_parses_simple_two_row_table():
    html = b"""
    <html><body>
    <table>
      <tr><th>Date</th><th>91D T-Bill</th><th>10 Year G-Sec</th></tr>
      <tr><td>03-05-2026</td><td>6.92</td><td>7.05</td></tr>
      <tr><td>04-05-2026</td><td>6.95</td><td>7.10</td></tr>
    </table>
    </body></html>
    """
    rows = parse_rbi_yields(html)
    by_tenor = {r["tenor"]: r for r in rows}
    assert "10Y" in by_tenor
    assert "91D" in by_tenor
    # Most-recent dated row wins
    assert by_tenor["10Y"]["yield_pct"] == pytest.approx(7.10)
    assert by_tenor["10Y"]["as_of_date"] == "2026-05-04"
    assert by_tenor["91D"]["yield_pct"] == pytest.approx(6.95)


def test_ignores_unrelated_table():
    html = b"""
    <html><body>
    <table>
      <tr><th>Currency</th><th>Rate</th></tr>
      <tr><td>USD</td><td>83.20</td></tr>
    </table>
    </body></html>
    """
    rows = parse_rbi_yields(html)
    assert rows == []


def test_handles_missing_yield_cells():
    html = b"""
    <html><body>
    <table>
      <tr><th>Date</th><th>10 Year G-Sec</th></tr>
      <tr><td>04-05-2026</td><td>-</td></tr>
    </table>
    </body></html>
    """
    rows = parse_rbi_yields(html)
    # No usable values → no rows
    assert rows == []


def test_parses_nsdp_multi_row_header_layout():
    """Regression: RBI's BS_NSDPDisplay.aspx?param=4 (live page as of
    2026-05) has a multi-row header — year on row N, month-day on
    row N+1, then tenor rows. A 112KB archive of this exact page was
    yielding 0 rows before this parser path landed."""
    html = b"""
    <html><body>
    <table>
      <tr><td>(Per cent)</td></tr>
      <tr><td>Item/Week Ended</td><td>2025</td><td>2026</td></tr>
      <tr><td>Apr. 25</td><td>Mar. 27</td><td>Apr. 24</td></tr>
      <tr><td>1</td><td>2</td><td>3</td></tr>
      <tr><td>Policy Repo Rate</td><td>6.00</td><td>5.25</td><td>5.25</td></tr>
      <tr><td>91-Day Treasury Bill (Primary) Yield</td><td>5.90</td><td>..</td><td>5.22</td></tr>
      <tr><td>364-Day Treasury Bill (Primary) Yield</td><td>5.95</td><td>..</td><td>5.60</td></tr>
      <tr><td>10-Year G-Sec Par Yield (FBIL)</td><td>6.40</td><td>7.02</td><td>7.02</td></tr>
    </table>
    </body></html>
    """
    rows = parse_rbi_yields(html)
    by_tenor = {r["tenor"]: r for r in rows}
    # Rightmost column (most recent) wins → 2026-04-24
    assert by_tenor["10Y"]["yield_pct"] == pytest.approx(7.02)
    assert by_tenor["10Y"]["as_of_date"] == "2026-04-24"
    assert by_tenor["91D"]["yield_pct"] == pytest.approx(5.22)
    assert by_tenor["364D"]["yield_pct"] == pytest.approx(5.60)
    assert by_tenor["OVERNIGHT"]["yield_pct"] == pytest.approx(5.25)
    assert by_tenor["OVERNIGHT"]["instrument"] == "POLICY_REPO"
