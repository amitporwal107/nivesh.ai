"""BSE bhavcopy as the prices_eod fallback when NSE's edge blocks us.

The migration rests on one claim: BSE publishes the same SEBI-standard
layout NSE does, so `parse_bhavcopy` handles it unchanged. These tests
pin that claim against a real slice of BSE's 2026-08-17 file, plus the
URL builders the fallback depends on.

The gap-fill *write* semantics (NSE precedence, ISIN re-keying) need a
live DB and are covered by the staging run recorded in
test_reports/nse_to_nsdl_bse_migration.md.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from nidp.services.bhavcopy.parser import parse_bhavcopy
from nidp.shared.sources.bse_fetcher import bhavcopy_url, delivery_url

FIXTURE = (Path(__file__).resolve().parents[1]
           / "fixtures" / "bse" / "bhavcopy_20260817_slice.csv")
BODY = FIXTURE.read_bytes()


def _rows():
    return parse_bhavcopy(BODY)


def _by_isin(isin):
    for r in _rows():
        if r.get("isin") == isin:
            return r
    raise AssertionError(f"{isin} not parsed")


def test_bse_file_parses_with_the_unmodified_nse_parser():
    rows = _rows()
    assert rows, "BSE bhavcopy produced no rows"
    assert all(r["as_of_date"] == "2026-08-17" for r in rows)


def test_every_row_has_a_close_price():
    """BSE spells the column ClsPric, NSE ClsgPric — a silent None here
    would zero out the fallback day's closes."""
    assert [r for r in _rows() if r.get("close_price") is None] == []


def test_isin_is_present_for_identity_rekeying():
    """Gap-fill re-keys BSE rows onto NSE symbol/series via ISIN, so a
    missing ISIN would silently drop the row."""
    rows = _rows()
    with_isin = [r for r in rows if (r.get("isin") or "").startswith("INE")]
    assert len(with_isin) >= len(rows) * 0.8


def test_known_large_caps_carry_sane_ohlc():
    r = _by_isin("INE002A01018")          # RELIANCE
    assert r["symbol"] == "RELIANCE"
    assert r["low_price"] <= r["close_price"] <= r["high_price"]
    assert r["volume"] > 0


@pytest.mark.parametrize("isin,sym", [
    ("INE467B01029", "TCS"),
    ("INE009A01021", "INFY"),
    ("INE040A01034", "HDFCBANK"),
])
def test_bse_tickers_match_nse_tickers_for_dual_listed(isin, sym):
    assert _by_isin(isin)["symbol"] == sym


def test_ohlc_invariants_hold_for_every_row():
    for r in _rows():
        lo, hi = r.get("low_price"), r.get("high_price")
        if lo is None or hi is None:
            continue
        assert lo <= hi, r
        for k in ("open_price", "close_price"):
            if r.get(k) is not None:
                assert lo <= r[k] <= hi, (k, r)


def test_bse_url_builders():
    d = date(2026, 8, 17)
    assert bhavcopy_url(d).endswith("BhavCopy_BSE_CM_0_0_0_20260817_F_0000.CSV")
    assert delivery_url(d).endswith("/2026/SCBSEALL1708.zip")
