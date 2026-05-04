"""Golden-file tests for bulk-deals parser. No network, no DB."""
from __future__ import annotations

from pathlib import Path

import pytest

from nidp.services.bulk_deals.parser import parse_bulk_deals

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def test_parse_bulk_deals_canonical():
    body = (FIXTURES / "bulk_deals_sample.csv").read_bytes()
    rows = parse_bulk_deals(body)

    assert len(rows) == 5

    # First row — basic field check
    r0 = rows[0]
    assert r0["as_of_date"] == "2026-05-04"
    assert r0["symbol"] == "RELIANCE"
    assert r0["client_name"] == "GOLDMAN SACHS (SINGAPORE) PTE"
    assert r0["deal_type"] == "BUY"
    assert r0["quantity"] == 1_500_000
    assert r0["avg_price"] == pytest.approx(2865.50)
    assert r0["deal_seq"] == 1
    # NSE uses "-" for empty remarks; parser maps to None
    assert r0["remarks"] is None

    # Multi-tranche dedup — same (date, symbol, client, side) gets seq 1,2
    sbi = [r for r in rows if r["client_name"] == "SBI MUTUAL FUND"]
    assert len(sbi) == 2
    seqs = sorted(r["deal_seq"] for r in sbi)
    assert seqs == [1, 2]
    assert sbi[1]["remarks"] == "Second tranche"


def test_parse_bulk_deals_empty():
    assert parse_bulk_deals(b"") == []


def test_parse_bulk_deals_header_only():
    csv = b"Date,Symbol,Security Name,Client Name,Buy/Sell,Quantity Traded,Trade Price / Wght. Avg. Price,Remarks\n"
    assert parse_bulk_deals(csv) == []


def test_parse_bulk_deals_skips_malformed_row():
    body = (
        b"Date,Symbol,Security Name,Client Name,Buy/Sell,Quantity Traded,Trade Price / Wght. Avg. Price,Remarks\n"
        b"04-May-2026,GOOD,Good Co,FOO,BUY,100,99.50,-\n"
        b"NOT-A-DATE,BAD,Bad Co,FOO,BUY,100,99.50,-\n"
    )
    rows = parse_bulk_deals(body)
    # The bad-date row is skipped, the good one persists.
    assert len(rows) == 1
    assert rows[0]["symbol"] == "GOOD"


def test_parse_bulk_deals_missing_required_column_raises():
    body = b"Date,Symbol,WrongColumn\n04-May-2026,FOO,BAR\n"
    with pytest.raises(ValueError, match="missing required columns"):
        parse_bulk_deals(body)
