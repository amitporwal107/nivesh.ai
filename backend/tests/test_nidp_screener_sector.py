"""NSE industry classification from Screener.in -> sector_master, in migration 080's labels."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from nidp.services.nse_financials.llm_extractor import parse_screener_classification  # noqa: E402
from nidp.services.nse_financials.screener_sector import (  # noqa: E402
    SECTOR_LABEL, nifty500_industry, sector_fields,
)

# Verbatim from https://www.screener.in/company/HDFCBANK/consolidated/ (2026-09-13)
HDFCBANK = '''<section id="peers" class="card card-large"><p>
<a href="/market/IN05/" target="_blank" title="Broad Sector">Financial Services</a>
<a href="/market/IN05/IN0501/" target="_blank" title="Sector">Financial Services</a>
<a href="/market/IN05/IN0501/IN050102/" target="_blank" title="Broad Industry">Banks</a>
<a href="/market/IN05/IN0501/IN050102/IN050102002/" target="_blank" title="Industry">Private Sector Bank</a>
</p></section>'''
RELIANCE_SECTOR = '<a href="/market/IN01/IN0101/" target="_blank" title="Sector">Oil, Gas &amp; Consumable Fuels</a>'


def test_parses_all_four_levels():
    assert parse_screener_classification("HDFCBANK", HDFCBANK) == {
        "broad_sector": "Financial Services", "sector": "Financial Services",
        "broad_industry": "Banks", "industry": "Private Sector Bank"}


def test_unescapes_and_maps_to_the_nifty500_spelling():
    cls = parse_screener_classification("RELIANCE", RELIANCE_SECTOR)
    assert cls["sector"] == "Oil, Gas & Consumable Fuels"
    assert sector_fields(cls) == ("Oil Gas", "Oil Gas & Consumable Fuels")


def test_every_mapped_label_matches_migration_080():
    assert sector_fields({"sector": "Financial Services"}) == ("Finance", "Financial Services")
    assert sector_fields({"sector": "Media, Entertainment & Publication"}) == ("Media", "Media Entertainment & Publication")
    assert len(SECTOR_LABEL) == 20


def test_unknown_labels_pass_through_like_080():
    assert sector_fields({"sector": "Forest Materials"}) == ("Forest Materials", "Forest Materials")


def test_no_sector_breadcrumb_is_none():
    assert parse_screener_classification("X", "<html><a href='/company/X/'>X</a></html>") is None
    assert parse_screener_classification("X", "") is None


def test_comma_normalisation_collapses_spaces():
    assert nifty500_industry("Oil,  Gas & Consumable Fuels ") == "Oil Gas & Consumable Fuels"
