"""Tests for the FII/DII parser.

NSE serves XLS/XLSX/HTML variants. We test:
  - format-detection short-circuits on unknown bodies (loud failure)
  - HTML fallback path (the easiest to fixture without binary files)

Full XLS golden-file coverage waits on real-world fixtures; the
parser raises NotImplementedError on unrecognised bodies so partial
coverage here doesn't risk silent data corruption.
"""
from __future__ import annotations

import pytest

from nidp.services.fii_dii.parser import _detect_format, parse_fii_dii


def test_detect_format_xlsx():
    body = b"PK\x03\x04rest-of-zip"
    assert _detect_format(body) == "xlsx"


def test_detect_format_xls():
    body = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1rest-of-ole"
    assert _detect_format(body) == "xls"


def test_detect_format_html():
    body = b"<html><body><table></table></body></html>"
    assert _detect_format(body) == "html"


def test_detect_format_unknown_raises():
    with pytest.raises(NotImplementedError, match="unrecognised fii_stats body"):
        _detect_format(b"random gibberish that is not any known format")


def test_html_fallback_extracts_fii_dii():
    pd = pytest.importorskip("pandas")  # noqa: F841
    html = b"""
    <html><body>
    <table>
      <tr><th>Category</th><th>Buy</th><th>Sell</th><th>Net</th></tr>
      <tr><td>FII</td><td>15234.50</td><td>14001.20</td><td>1233.30</td></tr>
      <tr><td>DII</td><td>9802.10</td><td>10245.60</td><td>-443.50</td></tr>
      <tr><td>Total</td><td>25036.60</td><td>24246.80</td><td>789.80</td></tr>
    </table>
    </body></html>
    """
    rows = parse_fii_dii(html, "2026-05-04")
    assert len(rows) == 2
    by_cat = {r["category"]: r for r in rows}
    assert by_cat["FII"]["net_value_cr"] == pytest.approx(1233.30)
    assert by_cat["DII"]["net_value_cr"] == pytest.approx(-443.50)
    assert all(r["segment"] == "EQUITY_CASH" for r in rows)
    assert all(r["as_of_date"] == "2026-05-04" for r in rows)
