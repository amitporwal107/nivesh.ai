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


# Fixture: real NSE Nifty PSU Bank list (nsearchives ind_niftypsubanklist.csv, fetched 2026-10-19), unedited.
def test_parse_psu_bank_real_list():
    rows = parse_constituents((FIXTURES / "index_constituents_psubank_sample.csv").read_bytes())
    assert len(rows) == 12
    sbin = next(r for r in rows if r["symbol"] == "SBIN")
    assert sbin["isin"] == "INE062A01020"
    assert sbin["company_name"] == "State Bank of India"
    assert next(r for r in rows if r["symbol"] == "PSB")["company_name"] == "Punjab & Sind Bank"


# Fixture: the first 400 bytes of what niftyindices.com returns (status 200) for a wrong filename.
def test_html_soft_404_is_rejected_not_parsed_as_empty():
    import pytest
    with pytest.raises(ValueError):
        parse_constituents((FIXTURES / "index_constituents_html_soft404.html").read_bytes())


def test_every_desk_sector_index_has_a_list_url():
    from nidp.services.daas_api.routers.desk_market import SECTOR_INDICES
    from nidp.shared.config import INDEX_CONSTITUENT_URLS
    missing = [n for n, _ in SECTOR_INDICES if n not in INDEX_CONSTITUENT_URLS]
    assert missing == []
    assert "Nifty Midcap 150" in INDEX_CONSTITUENT_URLS and "Nifty Smallcap 250" in INDEX_CONSTITUENT_URLS
