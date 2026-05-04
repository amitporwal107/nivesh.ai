"""Golden-file tests for index-constituents parser."""
from __future__ import annotations

from pathlib import Path

from nidp.services.index_constituents.parser import parse_constituents

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def test_parse_constituents_canonical():
    body = (FIXTURES / "index_constituents_sample.csv").read_bytes()
    rows = parse_constituents(body)

    assert len(rows) == 4
    rel = next(r for r in rows if r["symbol"] == "RELIANCE")
    assert rel["isin"] == "INE002A01018"
    assert rel["company_name"] == "Reliance Industries Ltd"
    assert rel["industry"] == "Oil Gas & Consumable Fuels"
    assert rel["weight_pct"] is None  # not in standard CSV
