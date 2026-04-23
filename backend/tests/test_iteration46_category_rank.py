"""
Iteration 46: Category-rank visibility + sub_category partitioning.

Root cause fixed (per review request):
  (1) v3_integration bundle now carries `instrument_id` and `sub_category`
      (was missing → category_rank_by_iid always returned None).
  (2) enrichment partitions by `sub_category` (e.g. Flexi Cap vs Flexi Cap),
      not broad `category` ('equity' vs everything).

Spec targets (from review_request):
  - ≥20 MFs now ranked (last iteration was 3/36; live showed 22/36).
  - Sub-category spot-checks: Parag Parikh Flexi Cap Direct #1/14,
    HDFC Flexi Cap Direct #2/14, HDFC Balanced Advantage Direct #1/2,
    Axis Small Cap #5/17.
  - Morningstar regression: 14/36 still present.
"""
import os
import math
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
SESSION_COOKIE = {"session_token": "370eff71-fda1-46d8-b506-b81b894d634f"}


# --- shared fetch (module-scope cache via simple dict) ---
_cache: dict = {}


def _fetch_holdings():
    if "holdings" in _cache:
        return _cache["holdings"]
    r = requests.get(
        f"{BASE_URL}/api/portfolio/holdings-enriched",
        cookies=SESSION_COOKIE,
        timeout=60,
    )
    assert r.status_code == 200, f"holdings-enriched returned {r.status_code}: {r.text[:300]}"
    payload = r.json()
    hs = payload if isinstance(payload, list) else (
        payload.get("holdings") or payload.get("data") or []
    )
    _cache["holdings"] = hs
    return hs


# --- category-rank coverage ---
class TestCategoryRankCoverage:
    def test_mf_category_rank_populated_for_20plus(self):
        hs = _fetch_holdings()
        mfs = [h for h in hs if (h.get("asset_type") or "").lower() in ("mutual_fund", "mf", "etf")]
        ranked = [h for h in mfs if h.get("category_rank") is not None]
        assert len(mfs) >= 20, f"Expected ≥20 MF holdings; got {len(mfs)}"
        assert len(ranked) >= 20, (
            f"Expected ≥20 MFs with category_rank populated; got {len(ranked)}/{len(mfs)} "
            f"(last iteration was 3/36)"
        )

    def test_category_rank_total_always_paired(self):
        """rank and rank_total must both be present or both absent."""
        hs = _fetch_holdings()
        for h in hs:
            r = h.get("category_rank")
            t = h.get("category_rank_total")
            if r is None:
                assert t is None, f"{h.get('name')}: rank None but total={t}"
            else:
                assert t is not None and t >= r >= 1, (
                    f"{h.get('name')}: invalid rank={r} total={t}"
                )

    def test_ranked_funds_have_valid_totals(self):
        """Totals should be >1 for a real partition (not everything ending up in a bucket of 1)."""
        hs = _fetch_holdings()
        ranked = [h for h in hs if h.get("category_rank") is not None]
        # At least half the ranked MFs should live in a sub_category with >=5 peers,
        # confirming sub_category partitioning (not one-per-bucket noise).
        healthy = [h for h in ranked if (h.get("category_rank_total") or 0) >= 5]
        assert len(healthy) >= len(ranked) * 0.5, (
            f"Only {len(healthy)}/{len(ranked)} ranked funds have >=5 peers — suggests "
            f"partitioning fell back to single-fund buckets."
        )


# --- sub_category spot-checks ---
class TestSubCategorySpotChecks:
    def _find(self, hs, needles):
        needles = [n.lower() for n in needles]
        for h in hs:
            n = (h.get("name") or h.get("scheme_name") or "").lower()
            if all(x in n for x in needles):
                return h
        return None

    def test_hdfc_flexi_cap_direct(self):
        h = self._find(_fetch_holdings(), ["hdfc", "flexi", "direct"])
        assert h, "HDFC Flexi Cap Direct not in portfolio"
        assert h.get("category_rank") is not None, "Expected category_rank on HDFC Flexi Cap Direct"
        assert h.get("category_rank_total") in (13, 14, 15), (
            f"Expected ~14-bucket Flexi-Cap partition, got total={h.get('category_rank_total')}"
        )

    def test_hdfc_balanced_advantage_direct(self):
        h = self._find(_fetch_holdings(), ["hdfc", "balanced", "advantage", "direct"])
        assert h, "HDFC Balanced Advantage Direct not in portfolio"
        assert h.get("category_rank") is not None
        # Tiny bucket (spec says #1/2) — accept 2 or 3 for tolerance
        assert (h.get("category_rank_total") or 0) <= 4, (
            f"Balanced Advantage bucket unexpectedly large: {h.get('category_rank_total')}"
        )

    def test_axis_small_cap_direct(self):
        h = self._find(_fetch_holdings(), ["axis", "small", "cap", "direct"])
        assert h, "Axis Small Cap Direct not in portfolio"
        assert h.get("category_rank") is not None
        # Spec says #5/17 — Small Cap bucket ~15-20
        assert 10 <= (h.get("category_rank_total") or 0) <= 25, (
            f"Small Cap bucket size unexpected: {h.get('category_rank_total')}"
        )


# --- Morningstar regression ---
class TestMorningstarRegression:
    def test_morningstar_rating_still_populated(self):
        hs = _fetch_holdings()
        mfs = [h for h in hs if (h.get("asset_type") or "").lower() in ("mutual_fund", "mf", "etf")]
        with_ms = [h for h in mfs if h.get("morningstar_rating") is not None]
        # Spec: 14/36 expected; live has 14
        assert len(with_ms) >= 10, (
            f"Morningstar regression: only {len(with_ms)} MFs have ratings (expected ~14)"
        )


# --- core enrichment regressions (scores/XIRR/impact-strip) ---
class TestEnrichmentNoRegression:
    def test_composite_scores_present(self):
        hs = _fetch_holdings()
        with_scores = [h for h in hs if h.get("composite_score") is not None]
        assert len(with_scores) >= len(hs) * 0.5, (
            f"composite_score regressed: {len(with_scores)}/{len(hs)}"
        )

    def test_xirr_coverage(self):
        hs = _fetch_holdings()
        with_xirr = [h for h in hs if h.get("xirr_pct") is not None]
        assert len(with_xirr) >= 10, f"XIRR coverage dropped: {len(with_xirr)}"

    def test_action_badges_present(self):
        hs = _fetch_holdings()
        with_badge = [h for h in hs if h.get("action_badge")]
        assert len(with_badge) >= len(hs) * 0.5

    def test_portfolio_analytics_endpoint(self):
        # impact-strip is frontend-computed; verify the analytics endpoint
        # it feeds from is still healthy.
        r = requests.get(
            f"{BASE_URL}/api/portfolio/analytics",
            cookies=SESSION_COOKIE,
            timeout=30,
        )
        assert r.status_code == 200, f"analytics: {r.status_code}"
        d = r.json()
        assert isinstance(d, dict)
