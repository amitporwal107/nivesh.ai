"""Unit tests for services.fund_clusterer.cluster_overlapping_funds.

Validates the 2026-05-20 fix: duplicate-fund detection must (1) only
pair within SEBI primary category, (2) cluster N-way instead of N×(N-1)/2
pairs, and (3) keep Index sub-categories distinct (Nifty 50 vs Nifty Next
50 must not cluster).
"""
from __future__ import annotations

from services.fund_clusterer import cluster_overlapping_funds


def _mf(name: str, sebi_category: str, sebi_subcategory: str | None = None,
        sector: str | None = None, qty: float = 1.0, price: float = 100.0):
    """Build a holding dict that satisfies BOTH the enricher's outputs
    AND `compute_fund_overlap`'s input expectations."""
    return {
        "name": name,
        "asset_type": "mutual_fund",
        "sebi_category": sebi_category,
        "sebi_subcategory": sebi_subcategory,
        "sector": sector or sebi_category,
        "quantity": qty,
        "current_price": price,
    }


def test_three_nifty_50_funds_cluster_into_one():
    holdings = [
        _mf("UTI Nifty 50 Index Fund Plan",   "Index Fund", "Nifty 50"),
        _mf("HDFC Nifty 50 Index Fund",        "Index Fund", "Nifty 50"),
        _mf("ICICI Prudential Nifty 50 Fund",  "Index Fund", "Nifty 50"),
    ]
    clusters = cluster_overlapping_funds(holdings)
    assert len(clusters) == 1, f"expected 1 cluster, got {len(clusters)}"
    assert clusters[0]["size"] == 3


def test_large_cap_vs_index_fund_does_not_cluster():
    """The user-reported bug: Mirae Large Cap + UTI Nifty 50 Index
    were being paired as duplicates. Different SEBI categories =>
    must be in distinct buckets and never appear in the same cluster.
    """
    holdings = [
        _mf("Mirae Asset Large Cap Fund",  "Large Cap"),
        _mf("UTI Nifty 50 Index Fund",      "Index Fund", "Nifty 50"),
    ]
    clusters = cluster_overlapping_funds(holdings)
    assert clusters == []


def test_different_index_subcategories_kept_separate():
    """Both are 'Index Fund' but tracking different indices — must NOT
    cluster together."""
    holdings = [
        _mf("UTI Nifty 50 Index Fund",          "Index Fund", "Nifty 50"),
        _mf("UTI Nifty Next 50 Index Fund",      "Index Fund", "Nifty Next 50"),
    ]
    clusters = cluster_overlapping_funds(holdings)
    assert clusters == []


def test_two_large_cap_funds_cluster():
    holdings = [
        _mf("HDFC Large Cap Fund",  "Large Cap"),
        _mf("Axis Bluechip Fund",   "Large Cap"),
    ]
    clusters = cluster_overlapping_funds(holdings)
    assert len(clusters) == 1
    assert clusters[0]["size"] == 2


def test_holdings_without_category_are_skipped():
    """Can't safely cluster uncategorised holdings — would risk
    re-introducing cross-category pairs."""
    holdings = [
        _mf("Categorised Fund A",          "Large Cap"),
        {"name": "Uncategorised Fund X",   "asset_type": "mutual_fund",
         "sector": "Large Cap", "quantity": 1, "current_price": 100},
        {"name": "Uncategorised Fund Y",   "asset_type": "mutual_fund",
         "sector": "Large Cap", "quantity": 1, "current_price": 100},
    ]
    clusters = cluster_overlapping_funds(holdings)
    assert clusters == []


def test_two_buckets_produce_two_clusters():
    holdings = [
        _mf("Nifty 50 A", "Index Fund", "Nifty 50"),
        _mf("Nifty 50 B", "Index Fund", "Nifty 50"),
        _mf("Nifty 50 C", "Index Fund", "Nifty 50"),
        _mf("Large Cap X", "Large Cap"),
        _mf("Large Cap Y", "Large Cap"),
    ]
    clusters = cluster_overlapping_funds(holdings)
    assert len(clusters) == 2
    sizes = sorted(c["size"] for c in clusters)
    assert sizes == [2, 3]


def test_index_fund_without_subcategory_is_dropped():
    """An 'Index Fund' without a known sub-category can't be safely
    clustered — we don't know what it tracks."""
    holdings = [
        {"name": "Generic Index Fund A", "asset_type": "mutual_fund",
         "sebi_category": "Index Fund", "sebi_subcategory": None,
         "sector": "Large Cap", "quantity": 1, "current_price": 100},
        {"name": "Generic Index Fund B", "asset_type": "mutual_fund",
         "sebi_category": "Index Fund", "sebi_subcategory": None,
         "sector": "Large Cap", "quantity": 1, "current_price": 100},
    ]
    clusters = cluster_overlapping_funds(holdings)
    assert clusters == []


def test_cluster_payload_has_required_keys():
    holdings = [
        _mf("Nifty 50 A", "Index Fund", "Nifty 50", qty=10, price=200),
        _mf("Nifty 50 B", "Index Fund", "Nifty 50", qty=5, price=400),
    ]
    clusters = cluster_overlapping_funds(holdings)
    assert len(clusters) == 1
    c = clusters[0]
    for key in (
        "sebi_category", "sebi_subcategory", "members",
        "avg_overlap_pct", "total_value_rs", "size",
    ):
        assert key in c, f"missing {key}"

    assert c["sebi_category"] == "Index Fund"
    assert c["sebi_subcategory"] == "Nifty 50"
    assert c["size"] == 2
    # 10×200 + 5×400 = 4000
    assert c["total_value_rs"] == 4000.0
    for m in c["members"]:
        assert {"name", "scheme_code", "current_value_rs", "ticker"} <= m.keys()


def test_clusters_sorted_largest_first():
    holdings = [
        _mf("Large Cap 1", "Large Cap"),
        _mf("Large Cap 2", "Large Cap"),
        _mf("Nifty A", "Index Fund", "Nifty 50"),
        _mf("Nifty B", "Index Fund", "Nifty 50"),
        _mf("Nifty C", "Index Fund", "Nifty 50"),
    ]
    clusters = cluster_overlapping_funds(holdings)
    assert len(clusters) == 2
    assert clusters[0]["size"] == 3
    assert clusters[1]["size"] == 2
