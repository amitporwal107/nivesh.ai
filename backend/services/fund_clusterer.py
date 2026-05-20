"""Fund Clusterer — N-way grouping of similar MF holdings.

Replaces the per-pair `overlap_matrix` (analytics.py:638-650) so that:

  1. Funds are paired ONLY within the same SEBI primary category
     (Large Cap with Large Cap; Index Fund with Index Fund tracking
     the same index; etc.).
  2. Three Nifty 50 funds become ONE cluster of size 3, not three
     pairs of size 2.
  3. The Recommendations Centre gets one insight per cluster ("keep
     the best-scoring, exit the rest") instead of N×(N-1)/2 pair
     insights.

Why this fix is needed: per the 2026-05-20 user report, the current
pair iteration paired Large Cap funds with Index funds (because both
have `sector = "Large Cap"`) and produced 60-69% "overlap" — wrong
on two axes. The category filter here defuses the cross-category
false positive; the N-way clustering defuses the pair-explosion.

Inputs are holding dicts. Caller (analytics route) must run
`services.mf_category_enricher.enrich_mf_with_sebi_category()` first
to populate `sebi_category` / `sebi_subcategory`.

Pure module — no DB / network. Easy to unit-test.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from helpers.portfolio_utils import compute_fund_overlap


# Default threshold for declaring two funds "duplicates" within a
# category. 40% mirrors the threshold used by other parts of the
# codebase (services/copilot_tools/portfolio.py overlap detector).
DEFAULT_OVERLAP_THRESHOLD = 40.0


# ── Union-Find (for N-way clustering) ────────────────────────────────
class _UnionFind:
    """Path-compressed disjoint-set forest. Used to group funds where
    each pairwise overlap edge implies transitive consolidation."""
    def __init__(self, n: int) -> None:
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


# ── Grouping helper ──────────────────────────────────────────────────
def _group_by_category(
    holdings: List[Dict[str, Any]],
) -> Dict[Tuple[Optional[str], Optional[str]], List[Dict[str, Any]]]:
    """Bucket holdings by (sebi_category, sebi_subcategory).

    Holdings without a category are dropped — we can't safely cluster
    them (would risk re-introducing cross-category pairs).

    Special rule for Index Funds: REQUIRE a sub-category. A Nifty 50
    fund and a Nifty Next 50 fund are both "Index Fund" but distinct
    exposures — must NOT be clustered together. If sub is None on
    an Index Fund, leave it un-clustered."""
    groups: Dict[Tuple[Optional[str], Optional[str]], List[Dict[str, Any]]] = {}
    for h in holdings:
        cat = h.get("sebi_category")
        if not cat:
            continue
        sub = h.get("sebi_subcategory")
        if cat == "Index Fund" and not sub:
            continue
        groups.setdefault((cat, sub), []).append(h)
    return groups


# ── Cluster builder ──────────────────────────────────────────────────
def _cluster_within_group(
    members: List[Dict[str, Any]],
    threshold: float,
) -> List[List[int]]:
    """For one (category, subcategory) bucket of N≥2 funds, return the
    list of connected components (each = list of indices into members)
    where at least one pairwise overlap is >= threshold.

    Singletons are dropped — no recommendation if a fund is alone."""
    n = len(members)
    if n < 2:
        return []

    uf = _UnionFind(n)
    edge_weights: Dict[Tuple[int, int], float] = {}

    for i in range(n):
        for j in range(i + 1, n):
            ov = compute_fund_overlap(members[i], members[j])
            pct = float(ov.get("overlap_pct") or 0)
            if pct >= threshold:
                uf.union(i, j)
                edge_weights[(i, j)] = pct

    by_root: Dict[int, List[int]] = {}
    for i in range(n):
        by_root.setdefault(uf.find(i), []).append(i)

    clusters: List[List[int]] = [idxs for idxs in by_root.values() if len(idxs) >= 2]

    def _sort_key(idxs: List[int]) -> tuple:
        idx_set = set(idxs)
        weights = [w for (a, b), w in edge_weights.items() if a in idx_set and b in idx_set]
        return (-len(idxs), -sum(weights))

    clusters.sort(key=_sort_key)
    return clusters


def _summarise_cluster(
    members: List[Dict[str, Any]],
    indices: List[int],
    sebi_category: Optional[str],
    sebi_subcategory: Optional[str],
    threshold: float,
) -> Dict[str, Any]:
    """Build the response payload for one cluster."""
    cluster_members = [members[i] for i in indices]

    pcts: List[float] = []
    for a in range(len(cluster_members)):
        for b in range(a + 1, len(cluster_members)):
            ov = compute_fund_overlap(cluster_members[a], cluster_members[b])
            pct = float(ov.get("overlap_pct") or 0)
            if pct >= threshold:
                pcts.append(pct)
    avg_overlap = round(sum(pcts) / len(pcts), 1) if pcts else 0.0

    total_value = round(sum(
        (float(m.get("quantity") or 0) * float(m.get("current_price") or 0))
        for m in cluster_members
    ), 2)

    return {
        "sebi_category":    sebi_category,
        "sebi_subcategory": sebi_subcategory,
        "members": [
            {
                "name":             m.get("name", ""),
                "scheme_code":      m.get("scheme_code"),
                "current_value_rs": round(
                    float(m.get("quantity") or 0) * float(m.get("current_price") or 0), 2,
                ),
                "ticker":           m.get("ticker"),
            }
            for m in cluster_members
        ],
        "avg_overlap_pct":  avg_overlap,
        "total_value_rs":   total_value,
        "size":             len(cluster_members),
    }


# ── Public API ───────────────────────────────────────────────────────
def cluster_overlapping_funds(
    holdings: List[Dict[str, Any]],
    *,
    threshold: float = DEFAULT_OVERLAP_THRESHOLD,
) -> List[Dict[str, Any]]:
    """Top-level entry. Returns a list of cluster payloads.

    Each cluster has size ≥ 2 and contains only same-category funds
    where at least one pairwise overlap exceeds `threshold`.

    Sorted: largest cluster first; ties broken by total ₹ value."""
    groups = _group_by_category(holdings)
    out: List[Dict[str, Any]] = []
    for (cat, sub), members in groups.items():
        for cluster_indices in _cluster_within_group(members, threshold):
            out.append(_summarise_cluster(members, cluster_indices, cat, sub, threshold))

    out.sort(key=lambda c: (-c["size"], -c["total_value_rs"]))
    return out
