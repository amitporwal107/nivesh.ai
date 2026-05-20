"""Unit tests for services.mf_category_enricher.

The fix this module enables (2026-05-20): a Large Cap fund and a Nifty 50
Index fund should NOT be paired as duplicates just because both hold
large-cap stocks. The enricher tags each MF with its real SEBI category;
the downstream clusterer only pairs within the same category.
"""
from __future__ import annotations

from services.mf_category_enricher import (
    enrich_mf_with_sebi_category,
    normalise_scheme_category,
    parse_sebi_from_name,
)


# ── Name-parser tests ────────────────────────────────────────────────
def test_large_cap_name_parses_correctly():
    cat, sub = parse_sebi_from_name("Mirae Asset Large Cap Fund Growth")
    assert cat == "Large Cap"
    assert sub is None


def test_nifty_50_index_fund_parses_correctly():
    """The bug: this fund was getting clustered with Large Cap funds.
    Must parse to Index Fund with Nifty 50 sub-category."""
    cat, sub = parse_sebi_from_name("UTI Nifty 50 Index Fund Plan Growth")
    assert cat == "Index Fund"
    assert sub == "Nifty 50"


def test_nifty_index_without_explicit_50_falls_back_to_nifty_50():
    """2026-05-20 fix: AMFI/KFinTech sometimes store names that elide
    the '50' — 'UTI Nifty Index Fund' / 'SBI Nifty Index Fund' both
    track Nifty 50 in practice. Without this fallback they'd parse to
    ('Index Fund', None) and get dropped from duplicate-cluster
    detection — making the user's Index funds appear to 'disappear'
    from the rec center."""
    for name in (
        "UTI Nifty Index Fund Growth",
        "SBI Nifty Index Fund",
        "Tata Nifty Index Fund Direct Growth",
    ):
        cat, sub = parse_sebi_from_name(name)
        assert cat == "Index Fund", f"failed cat for {name!r}: {cat}"
        assert sub == "Nifty 50", (
            f"failed sub-cat for {name!r}: {sub} — expected 'Nifty 50' fallback"
        )


def test_sensex_index_without_number_falls_back():
    """A 'Sensex' fund parses to Index Fund / Sensex even if BSE 500
    et al don't match."""
    cat, sub = parse_sebi_from_name("HDFC Sensex Index Fund")
    assert cat == "Index Fund"
    assert sub == "Sensex"


def test_equal_weight_index_distinguished_from_plain_nifty_50():
    cat, sub = parse_sebi_from_name("HDFC NIFTY50 Equal Weight Index Fund Direct Growth")
    assert cat == "Index Fund"
    assert sub == "Nifty 50 Equal Weight"


def test_index_fund_beats_large_cap_keyword():
    """Multiple keywords present — Index detection must win because the
    Nifty 50 universe IS large-cap, but the fund's SEBI category is
    Index Fund, not Large Cap."""
    cat, sub = parse_sebi_from_name("ICICI Prudential Nifty 50 Index Fund Direct Plan")
    assert cat == "Index Fund"
    assert sub == "Nifty 50"


def test_unrecognised_name_returns_none():
    cat, sub = parse_sebi_from_name("Random Mystery Fund XYZ")
    assert cat is None
    assert sub is None


def test_empty_name_returns_none():
    cat, sub = parse_sebi_from_name("")
    assert cat is None
    assert sub is None


def test_aggressive_hybrid_parses_correctly():
    """The HDFC Hybrid Equity pair from the user's screenshot (overlap 87%)
    — both Regular and Direct variants must land on the same SEBI category
    so the clusterer can group them. SEBI classifies 'Hybrid Equity' as
    Aggressive Hybrid in practice."""
    cat, sub = parse_sebi_from_name("HDFC Hybrid Equity Fund Growth")
    assert cat == "Aggressive Hybrid"
    assert sub is None


def test_balanced_advantage_parses_correctly():
    cat, sub = parse_sebi_from_name("ICICI Prudential Balanced Advantage Fund")
    assert cat == "Balanced Advantage"


def test_elss_parses_correctly():
    cat, _ = parse_sebi_from_name("Axis Long Term Equity Fund - ELSS")
    assert cat == "ELSS"


def test_liquid_fund_parses_as_debt():
    cat, _ = parse_sebi_from_name("HDFC Liquid Fund Growth")
    assert cat == "Liquid"


def test_gold_etf_parses_correctly():
    cat, _ = parse_sebi_from_name("Nippon India Gold ETF")
    assert cat == "Gold ETF"


def test_international_fund_parses_correctly():
    cat, _ = parse_sebi_from_name("Motilal Oswal Nasdaq 100 Fund of Fund Growth")
    assert cat == "International Fund"


# ── NIDP scheme_category normalisation ───────────────────────────────
def test_normalise_handles_sebi_prefix():
    cat, _ = normalise_scheme_category("Equity Scheme - Large Cap Fund")
    assert cat == "Large Cap"


def test_normalise_index_fund_extracts_sub_from_name():
    cat, sub = normalise_scheme_category(
        "Open Ended - Index Funds/ETFs",
        fund_name="UTI Nifty 50 Index Fund",
    )
    assert cat == "Index Fund"
    assert sub == "Nifty 50"


def test_normalise_empty_returns_none():
    cat, sub = normalise_scheme_category(None)
    assert cat is None
    assert sub is None


# ── End-to-end enrichment ────────────────────────────────────────────
def test_enrich_mf_skips_non_mf_holdings():
    holdings = [
        {"name": "Reliance Industries", "asset_type": "stock"},
        {"name": "HDFC Large Cap Fund", "asset_type": "mutual_fund"},
    ]
    enrich_mf_with_sebi_category(holdings)
    assert "sebi_category" not in holdings[0]
    assert holdings[1].get("sebi_category") == "Large Cap"


def test_enrich_prefers_scheme_category_over_name_parse():
    """If NIDP says it's a Flexi Cap, name-based 'Large Cap' must not
    override that."""
    holdings = [{
        "name": "Some Fund containing Large Cap in the name",
        "asset_type": "mutual_fund",
        "scheme_category": "Equity Scheme - Flexi Cap Fund",
    }]
    enrich_mf_with_sebi_category(holdings)
    assert holdings[0]["sebi_category"] == "Flexi Cap"


def test_enrich_is_idempotent():
    holdings = [{
        "name": "UTI Nifty 50 Index Fund",
        "asset_type": "mutual_fund",
    }]
    enrich_mf_with_sebi_category(holdings)
    first_cat = holdings[0]["sebi_category"]
    first_sub = holdings[0]["sebi_subcategory"]
    enrich_mf_with_sebi_category(holdings)
    assert holdings[0]["sebi_category"] == first_cat
    assert holdings[0]["sebi_subcategory"] == first_sub
