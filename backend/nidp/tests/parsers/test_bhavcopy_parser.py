"""Golden-file tests for bhavcopy parser. No network, no DB."""
from __future__ import annotations

from pathlib import Path

import pytest

from nidp.services.bhavcopy.parser import parse_bhavcopy

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def test_parse_post2024_format():
    body = (FIXTURES / "bhavcopy_post2024_sample.csv").read_bytes()
    rows = parse_bhavcopy(body)

    # 4 valid CM/STK rows: RELIANCE, TCS, INFY, HDFCBANK.
    # NIFTY future (Sgmt=FO) is filtered out.
    # BADCO has no prices but parser does NOT validate — that's the
    # service's job. So we expect 5 (4 good + 1 BADCO with nulls).
    symbols = sorted(r["symbol"] for r in rows)
    assert symbols == ["BADCO", "HDFCBANK", "INFY", "RELIANCE", "TCS"]

    rel = next(r for r in rows if r["symbol"] == "RELIANCE")
    assert rel["series"] == "EQ"
    assert rel["isin"] == "INE002A01018"
    assert rel["open_price"] == pytest.approx(2853.00)
    assert rel["high_price"] == pytest.approx(2880.50)
    assert rel["low_price"] == pytest.approx(2845.10)
    assert rel["close_price"] == pytest.approx(2865.40)
    assert rel["volume"] == 3_050_000
    assert rel["turnover"] == pytest.approx(8_740_100_000.00)
    assert rel["trades"] == 72_500
    assert rel["as_of_date"] == "2026-05-04"

    # BE-series row should still parse (validate is downstream)
    hdfc = next(r for r in rows if r["symbol"] == "HDFCBANK")
    assert hdfc["series"] == "BE"


def test_parse_legacy_format():
    body = (FIXTURES / "bhavcopy_legacy_sample.csv").read_bytes()
    rows = parse_bhavcopy(body)

    assert len(rows) == 2
    rel = next(r for r in rows if r["symbol"] == "RELIANCE")
    assert rel["isin"] == "INE002A01018"
    assert rel["close_price"] == pytest.approx(2865.40)
    assert rel["as_of_date"] == "2024-07-03"


def test_parse_unknown_format_raises():
    body = b"foo,bar,baz\n1,2,3\n"
    with pytest.raises(ValueError, match="Unknown bhavcopy header"):
        parse_bhavcopy(body)


def test_parse_empty():
    assert parse_bhavcopy(b"") == []
