"""BSE delivery-position file as the nidp.delivery_data fallback.

BSE identifies delivery rows by scrip code alone, so the migration rests
on a two-hop bridge: scrip_code -> ISIN (from the same day's BSE
bhavcopy) -> NSE (symbol, series). These tests pin the parsing and the
first hop against real 2026-08-17 files.

The gap-fill write semantics (NSE precedence, unknown-ISIN drop) need a
live DB and are evidenced by the staging runs recorded in
test_reports/bse_delivery_migration.md.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from nidp.services.bhavcopy.parser import parse_bse_scrip_isin
from nidp.services.delivery.bse_parser import parse_bse_delivery

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "bse"
DELIV = (FIX / "delivery_20260817_slice.txt").read_bytes()
BHAV = (FIX / "bhavcopy_20260817_slice.csv").read_bytes()


def _rows():
    return parse_bse_delivery(DELIV)


def _by_scrip(code):
    for r in _rows():
        if r["scrip_code"] == code:
            return r
    raise AssertionError(f"scrip {code} not parsed")


def test_header_row_is_not_parsed_as_data():
    assert all(r["scrip_code"] != "SCRIP CODE" for r in _rows())
    assert _rows(), "parser returned nothing"


def test_ddmmyyyy_date_becomes_iso():
    assert all(r["as_of_date"] == "2026-08-17" for r in _rows())


def test_zero_padded_quantities_are_stripped():
    """'0000000000195097' must become 195097, not 0 and not a string."""
    r = _by_scrip("500325")                      # RELIANCE
    assert r["deliverable_qty"] == 195097
    assert r["traded_qty"] == 382229
    assert isinstance(r["deliverable_qty"], int)


def test_zero_padded_percentage_is_parsed():
    """'051.04' -> 51.04; a naive int-strip would lose the leading zero."""
    assert _by_scrip("500325")["deliverable_pct"] == pytest.approx(51.04)
    assert _by_scrip("500209")["deliverable_pct"] == pytest.approx(45.67)


def test_deliverable_never_exceeds_traded():
    for r in _rows():
        if r["deliverable_qty"] is None or r["traded_qty"] is None:
            continue
        assert r["deliverable_qty"] <= r["traded_qty"], r


def test_percentage_matches_quantities():
    """deliv_pct must equal deliverable/traded — proves column order."""
    for r in _rows():
        if not r["traded_qty"] or r["deliverable_pct"] is None:
            continue
        implied = 100.0 * r["deliverable_qty"] / r["traded_qty"]
        assert implied == pytest.approx(r["deliverable_pct"], abs=0.05), r


def test_percentages_are_within_range():
    for r in _rows():
        if r["deliverable_pct"] is not None:
            assert 0.0 <= r["deliverable_pct"] <= 100.0, r


def test_short_or_blank_lines_are_skipped():
    body = b"DATE|SCRIP CODE|DELIVERY QTY\n\n17082026|500325\nnot a row\n"
    assert parse_bse_delivery(body) == []


# ── the scrip_code -> ISIN bridge ────────────────────────────────────
def test_bridge_maps_scrip_code_to_isin():
    m = parse_bse_scrip_isin(BHAV)
    assert m["500325"] == "INE002A01018"        # RELIANCE
    assert m["532540"] == "INE467B01029"        # TCS


def test_bridge_is_empty_for_a_non_sebi_layout():
    """A shape change must degrade to 'no bridge', not to wrong mappings."""
    assert parse_bse_scrip_isin(b"SYMBOL,SERIES,CLOSE\nRELIANCE,EQ,1300\n") == {}
