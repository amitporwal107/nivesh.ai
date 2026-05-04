"""Golden-file tests for sec_bhavdata_full delivery parser."""
from __future__ import annotations

from pathlib import Path

import pytest

from nidp.services.delivery.parser import parse_delivery

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def test_parse_delivery_canonical():
    body = (FIXTURES / "delivery_sample.csv").read_bytes()
    rows = parse_delivery(body)

    # 3 data rows + 1 blank trailing row → 3 parsed.
    assert len(rows) == 3

    rel = next(r for r in rows if r["symbol"] == "RELIANCE")
    assert rel["series"] == "EQ"
    assert rel["as_of_date"] == "2026-05-04"
    assert rel["traded_qty"] == 3_050_000
    assert rel["deliverable_qty"] == 2_287_500
    assert rel["deliverable_pct"] == pytest.approx(75.00)

    # NSE uses "-" for missing delivery on T-segment / illiquid series.
    hdfc = next(r for r in rows if r["symbol"] == "HDFCBANK")
    assert hdfc["deliverable_qty"] is None
    assert hdfc["deliverable_pct"] is None


def test_parse_delivery_empty():
    assert parse_delivery(b"") == []


def test_parse_delivery_missing_columns_raises():
    body = b"SYMBOL,SERIES,DATE1\nFOO,EQ,01-Jan-2026\n"
    with pytest.raises(ValueError, match="missing columns"):
        parse_delivery(body)
