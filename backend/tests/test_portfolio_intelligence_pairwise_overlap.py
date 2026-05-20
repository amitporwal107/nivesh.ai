"""Regression tests for services.portfolio_intelligence._pairwise_overlap.

This is the REAL source of the cross-category pair bug the user reported
2026-05-20 — not routes/insights.py. The fix adds a SEBI-category gate
so Large Cap funds and Nifty 50 Index funds (which share large-cap stocks
but are different SEBI primary categories) never pair as duplicates.
"""
from __future__ import annotations

# The module imports deps.db and services.pg_client transitively. Stub
# them so the unit test stays in-process.
import sys
import types

if "deps" not in sys.modules:
    deps_stub = types.ModuleType("deps")
    deps_stub.db = None
    sys.modules["deps"] = deps_stub

if "services.pg_client" not in sys.modules:
    pg_stub = types.ModuleType("services.pg_client")
    sys.modules["services.pg_client"] = pg_stub

from services.portfolio_intelligence import (  # noqa: E402
    _pairwise_overlap,
    _sebi_buckets_match,
)


def _catalog_entry(scheme_name: str, category: str | None = None):
    """Minimal catalog entry shape."""
    return {"scheme_name": scheme_name, "category": category, "holdings": []}


def _weights(*top_stocks):
    """`{stock_slug: weight_pct}` map. Use the same slugs across funds
    to drive shared-stock overlap higher."""
    return {s: 5.0 for s in top_stocks}


# ── 1. SEBI category gate ─────────────────────────────────────────────
def test_large_cap_and_nifty_index_fund_do_not_pair():
    """The exact bug from the screenshots: Mirae Large Cap + UTI Nifty 50."""
    ids = ["mirae", "uti_nifty"]
    catalog = {
        "mirae":     _catalog_entry("Mirae Asset Large Cap Fund Growth"),
        "uti_nifty": _catalog_entry("UTI Nifty 50 Index Fund Plan Growth"),
    }
    # Both hold the same top stocks (high stock overlap), but they
    # are different SEBI categories — must not pair.
    weights = {
        "mirae":     _weights("reliance", "tcs", "hdfc-bank", "infosys"),
        "uti_nifty": _weights("reliance", "tcs", "hdfc-bank", "infosys"),
    }
    pairs = _pairwise_overlap(ids, weights, catalog)
    assert pairs == [], (
        f"cross-category pair leaked through SEBI filter: {pairs}"
    )


def test_two_large_cap_funds_do_pair():
    ids = ["mirae", "axis"]
    catalog = {
        "mirae": _catalog_entry("Mirae Asset Large Cap Fund Growth"),
        "axis":  _catalog_entry("Axis Bluechip Fund Growth"),  # Large Cap
    }
    # NOTE: "Axis Bluechip Fund" — without "Large Cap" in the name —
    # falls through to None in the parser. So in real life the system
    # would skip this pair. For the test, mark catalog category explicitly.
    catalog["axis"] = _catalog_entry("Axis Bluechip Large Cap Fund Growth")
    weights = {
        "mirae": _weights("reliance", "tcs", "hdfc-bank"),
        "axis":  _weights("reliance", "tcs", "hdfc-bank"),
    }
    pairs = _pairwise_overlap(ids, weights, catalog)
    assert len(pairs) == 1
    p = pairs[0]
    assert {p["a"], p["b"]} == {"mirae", "axis"}
    assert p["sebi_category"] == "Large Cap"
    assert any("Same SEBI category: Large Cap" in r for r in p["reasons"])


def test_three_nifty_50_funds_produce_three_pairs():
    """All same SEBI bucket → all three pairs (UF clustering happens
    downstream in dashboard_recommendations, not here)."""
    ids = ["uti", "hdfc", "icici"]
    catalog = {
        "uti":   _catalog_entry("UTI Nifty 50 Index Fund Plan Growth"),
        "hdfc":  _catalog_entry("HDFC Nifty 50 Index Fund Direct Growth"),
        "icici": _catalog_entry("ICICI Prudential Nifty 50 Index Fund Direct Plan"),
    }
    same_weights = _weights("reliance", "tcs", "hdfc-bank", "infosys")
    weights = {"uti": same_weights, "hdfc": same_weights, "icici": same_weights}
    pairs = _pairwise_overlap(ids, weights, catalog)
    assert len(pairs) == 3, f"expected 3 same-bucket pairs, got {len(pairs)}"
    for p in pairs:
        assert p["sebi_category"] == "Index Fund"
        assert p["sebi_subcategory"] == "Nifty 50"


def test_nifty_50_vs_nifty_next_50_do_not_pair():
    """Both are Index Funds but track different indices — must not pair."""
    ids = ["uti_50", "uti_next50"]
    catalog = {
        "uti_50":     _catalog_entry("UTI Nifty 50 Index Fund"),
        "uti_next50": _catalog_entry("UTI Nifty Next 50 Index Fund"),
    }
    weights = {
        "uti_50":     _weights("reliance", "tcs", "hdfc-bank"),
        "uti_next50": _weights("reliance", "tcs", "hdfc-bank"),
    }
    pairs = _pairwise_overlap(ids, weights, catalog)
    assert pairs == [], (
        f"Index sub-categories should be distinct: {pairs}"
    )


def test_index_fund_without_subcategory_skipped():
    """Generic 'Index Fund' name with no tracked-index keyword — can't
    safely cluster (could be tracking any index). Must skip."""
    ids = ["a", "b"]
    catalog = {
        "a": _catalog_entry("Generic Index Fund A"),
        "b": _catalog_entry("Generic Index Fund B"),
    }
    weights = {
        "a": _weights("reliance", "tcs"),
        "b": _weights("reliance", "tcs"),
    }
    pairs = _pairwise_overlap(ids, weights, catalog)
    assert pairs == []


def test_funds_without_category_skipped():
    ids = ["a", "b"]
    catalog = {
        "a": _catalog_entry("Some Mystery Fund X"),
        "b": _catalog_entry("Another Random Fund Y"),
    }
    weights = {
        "a": _weights("reliance"),
        "b": _weights("reliance"),
    }
    pairs = _pairwise_overlap(ids, weights, catalog)
    assert pairs == []  # can't safely match without a category


# ── 2. _sebi_buckets_match — unit logic ──────────────────────────────
def test_sebi_buckets_match_same_large_cap():
    assert _sebi_buckets_match("Large Cap", None, "Large Cap", None) is True


def test_sebi_buckets_match_different_categories():
    assert _sebi_buckets_match("Large Cap", None, "Index Fund", "Nifty 50") is False


def test_sebi_buckets_match_index_requires_same_sub():
    assert _sebi_buckets_match("Index Fund", "Nifty 50", "Index Fund", "Nifty 50") is True
    assert _sebi_buckets_match("Index Fund", "Nifty 50", "Index Fund", "Nifty Next 50") is False


def test_sebi_buckets_match_index_without_sub_is_false():
    assert _sebi_buckets_match("Index Fund", None, "Index Fund", "Nifty 50") is False
    assert _sebi_buckets_match("Index Fund", None, "Index Fund", None) is False


def test_sebi_buckets_match_unknown_categories_false():
    assert _sebi_buckets_match(None, None, None, None) is False
    assert _sebi_buckets_match("Large Cap", None, None, None) is False
