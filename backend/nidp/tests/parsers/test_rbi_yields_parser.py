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
