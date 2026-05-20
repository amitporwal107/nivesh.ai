"""Tests for the cluster collapse in dashboard_recommendations._project_overlap.

User directive 2026-05-20: three Nifty 50 funds should produce ONE
"Consolidate 3 funds in your Nifty 50 category" insight, NOT three
separate "Fund A and Fund B overlap N%" pair-insights.
"""
from __future__ import annotations

import sys
import types

# Stub the deps chain
if "deps" not in sys.modules:
    deps_stub = types.ModuleType("deps")
    deps_stub.db = None
    sys.modules["deps"] = deps_stub
if "services.pg_client" not in sys.modules:
    sys.modules["services.pg_client"] = types.ModuleType("services.pg_client")

from services.dashboard_recommendations import _project_overlap  # noqa: E402


def _pair(a_id, b_id, pct, *, sebi_category=None, sebi_subcategory=None,
          a_name=None, b_name=None):
    return {
        "a": a_id, "b": b_id,
        "a_name": a_name or f"Fund {a_id}",
        "b_name": b_name or f"Fund {b_id}",
        "overlap_pct": pct,
        "shared_count": 30,
        "reasons": [],
        "sebi_category":    sebi_category,
        "sebi_subcategory": sebi_subcategory,
    }


# ── Cluster collapse ────────────────────────────────────────────────
def test_three_nifty_50_funds_collapse_to_one_cluster():
    """The exact user-visible win: 3 pairs in same SEBI bucket → 1 insight."""
    intelligence = {
        "pairwise_overlap": [
            _pair("uti",   "hdfc",  72, sebi_category="Index Fund", sebi_subcategory="Nifty 50"),
            _pair("uti",   "icici", 65, sebi_category="Index Fund", sebi_subcategory="Nifty 50"),
            _pair("hdfc",  "icici", 68, sebi_category="Index Fund", sebi_subcategory="Nifty 50"),
        ],
    }
    out = _project_overlap(intelligence)
    overlap_rows = [r for r in out if r["kind"] == "OVERLAP"]
    assert len(overlap_rows) == 1, f"expected 1 cluster row, got {len(overlap_rows)}: {[r['title'] for r in overlap_rows]}"
    row = overlap_rows[0]
    assert "Consolidate 3 funds" in row["title"]
    assert "Nifty 50" in row["title"]
    assert sorted(row["metadata"]["fund_ids"]) == ["hdfc", "icici", "uti"]


def test_two_separate_buckets_produce_two_clusters():
    """3 Nifty 50 funds + 2 Large Cap funds → 2 cluster insights."""
    intelligence = {
        "pairwise_overlap": [
            # Nifty 50 cluster
            _pair("n1", "n2", 70, sebi_category="Index Fund", sebi_subcategory="Nifty 50"),
            _pair("n1", "n3", 68, sebi_category="Index Fund", sebi_subcategory="Nifty 50"),
            _pair("n2", "n3", 72, sebi_category="Index Fund", sebi_subcategory="Nifty 50"),
            # Large Cap cluster
            _pair("l1", "l2", 55, sebi_category="Large Cap"),
        ],
    }
    out = _project_overlap(intelligence)
    overlap_rows = [r for r in out if r["kind"] == "OVERLAP"]
    assert len(overlap_rows) == 2, [r["title"] for r in overlap_rows]
    # The larger cluster (size 3, higher max overlap) should be first
    assert "Consolidate 3" in overlap_rows[0]["title"]
    assert "Consolidate 2" in overlap_rows[1]["title"]


def test_pair_below_threshold_dropped():
    intelligence = {
        "pairwise_overlap": [
            _pair("a", "b", 20, sebi_category="Large Cap"),  # below 40 threshold
        ],
    }
    out = _project_overlap(intelligence)
    assert out == []


def test_unbucketed_pair_falls_back_to_pair_shape():
    """If sebi_category is missing (older data), we still emit something
    rather than dropping the signal entirely. Falls back to pair-style row."""
    intelligence = {
        "pairwise_overlap": [
            _pair("a", "b", 65, sebi_category=None, sebi_subcategory=None),
        ],
    }
    out = _project_overlap(intelligence)
    assert len(out) == 1
    # Old pair-shape title
    assert "overlap 65%" in out[0]["title"]
    assert "and" in out[0]["title"]


def test_cluster_impact_set_by_max_overlap():
    """High impact when any edge in the cluster is >= 70."""
    intelligence = {
        "pairwise_overlap": [
            _pair("a", "b", 75, sebi_category="Large Cap"),
            _pair("a", "c", 50, sebi_category="Large Cap"),
        ],
    }
    out = _project_overlap(intelligence)
    cluster = [r for r in out if r["kind"] == "OVERLAP"][0]
    assert cluster["impact"] == "high"


def test_transitive_overlap_collapses_into_one_cluster():
    """A↔B and B↔C edges → cluster {A,B,C}, even without an A↔C edge."""
    intelligence = {
        "pairwise_overlap": [
            _pair("a", "b", 60, sebi_category="Flexi Cap"),
            _pair("b", "c", 55, sebi_category="Flexi Cap"),
            # no A↔C edge — union-find should still merge all three
        ],
    }
    out = _project_overlap(intelligence)
    clusters = [r for r in out if r["kind"] == "OVERLAP"]
    assert len(clusters) == 1
    assert sorted(clusters[0]["metadata"]["fund_ids"]) == ["a", "b", "c"]


def test_cluster_metadata_includes_fund_names():
    intelligence = {
        "pairwise_overlap": [
            _pair("uti", "hdfc", 70, sebi_category="Index Fund", sebi_subcategory="Nifty 50",
                  a_name="UTI Nifty 50", b_name="HDFC Nifty 50"),
        ],
    }
    out = _project_overlap(intelligence)
    md = out[0]["metadata"]
    assert set(md["fund_names"]) == {"UTI Nifty 50", "HDFC Nifty 50"}
    assert md["sebi_category"] == "Index Fund"
    assert md["sebi_subcategory"] == "Nifty 50"
