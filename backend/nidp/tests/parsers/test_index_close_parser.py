"""Golden-file tests for ind_close_all parser."""
from __future__ import annotations

from pathlib import Path

import pytest

from nidp.services.index_close.parser import parse_index_close

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def test_parse_index_close_canonical():
    body = (FIXTURES / "index_close_sample.csv").read_bytes()
    rows = parse_index_close(body)

    assert len(rows) == 3
    n50 = next(r for r in rows if r["index_name"] == "Nifty 50")
    assert n50["as_of_date"] == "2026-05-04"
    assert n50["open_price"]  == pytest.approx(22500.00)
    assert n50["high_price"]  == pytest.approx(22680.45)
    assert n50["close_price"] == pytest.approx(22610.30)
    assert n50["pe_ratio"]    == pytest.approx(22.40)
    assert n50["div_yield"]   == pytest.approx(1.20)
    assert n50["volume"]      == 180_000_000
