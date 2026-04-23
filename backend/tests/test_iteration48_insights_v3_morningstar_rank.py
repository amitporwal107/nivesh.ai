"""Iteration 48: Morningstar + Category Rank surfaced in /api/insights/v3-portfolio.

Targets (from review_request for priyanka):
 - portfolio.n_morningstar_rated       ≈ 14
 - portfolio.avg_morningstar_rating    ≈ 4.64
 - portfolio.n_morningstar_4plus       ≈ 13
 - portfolio.n_category_ranked         ≈ 21
 - portfolio.n_top_quartile            ≈ 8
 - funds[] rows carry morningstar_rating / category_rank / _total / _sub
 - Spot-check: Aditya Birla Sun Life Large Cap  ms=4, 7/20 in Large Cap
               ICICI Prudential Value           ms=5, 2/5 in Value Oriented
               HDFC Small Cap                   ms=4, 7/17 in Small Cap
"""
import os
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
COOKIES = {"session_token": "370eff71-fda1-46d8-b506-b81b894d634f"}

_cache = {}


def _fetch():
    if "d" in _cache:
        return _cache["d"]
    r = requests.get(
        f"{BASE_URL}/api/insights/v3-portfolio",
        cookies=COOKIES, timeout=90,
    )
    assert r.status_code == 200, f"status={r.status_code} body={r.text[:300]}"
    _cache["d"] = r.json()
    return _cache["d"]


class TestPortfolioAggregate:
    def test_aggregate_keys_present(self):
        p = _fetch()["portfolio"]
        for k in ("n_morningstar_rated", "avg_morningstar_rating",
                  "n_morningstar_4plus", "n_category_ranked", "n_top_quartile"):
            assert k in p, f"portfolio missing {k}"

    def test_morningstar_rated_count(self):
        p = _fetch()["portfolio"]
        # spec: 14 → allow 10-20 band
        assert 10 <= p["n_morningstar_rated"] <= 20, p["n_morningstar_rated"]

    def test_avg_morningstar(self):
        p = _fetch()["portfolio"]
        assert p["avg_morningstar_rating"] is not None
        assert 4.0 <= p["avg_morningstar_rating"] <= 5.0

    def test_ms_4plus(self):
        p = _fetch()["portfolio"]
        assert p["n_morningstar_4plus"] >= 10

    def test_category_ranked_count(self):
        p = _fetch()["portfolio"]
        # spec: 21 → allow 15-30
        assert 15 <= p["n_category_ranked"] <= 30

    def test_top_quartile_count(self):
        p = _fetch()["portfolio"]
        # spec: 8 → allow 4-15
        assert 4 <= p["n_top_quartile"] <= 15


class TestFundRows:
    def test_funds_carry_new_keys(self):
        funds = _fetch()["funds"]
        assert funds
        for f in funds:
            # every fund must have the keys even if null
            assert "morningstar_rating" in f
            assert "category_rank" in f
            assert "category_rank_total" in f
            assert "category_rank_sub" in f

    def test_rank_invariants(self):
        for f in _fetch()["funds"]:
            r, t = f.get("category_rank"), f.get("category_rank_total")
            if r is None:
                assert t is None
            else:
                assert t and t >= r >= 1

    def test_morningstar_in_range(self):
        for f in _fetch()["funds"]:
            ms = f.get("morningstar_rating")
            if ms is not None:
                assert 1 <= ms <= 5

    def _find(self, needles):
        needles = [n.lower() for n in needles]
        for f in _fetch()["funds"]:
            nm = (f.get("scheme_name") or "").lower()
            if all(n in nm for n in needles):
                return f
        return None

    def test_spot_aditya_birla_large_cap(self):
        f = self._find(["aditya", "birla", "large"])
        assert f, "Aditya Birla Sun Life Large Cap not found"
        assert f.get("morningstar_rating") == 4, f.get("morningstar_rating")
        assert f.get("category_rank_total") in (18, 19, 20, 21)
        sub = (f.get("category_rank_sub") or "").lower()
        assert "large" in sub, sub

    def test_spot_icici_value(self):
        f = self._find(["icici", "value"])
        assert f, "ICICI Prudential Value not found"
        assert f.get("morningstar_rating") == 5
        assert f.get("category_rank_total") in (4, 5, 6)
        sub = (f.get("category_rank_sub") or "").lower()
        assert "value" in sub, sub

    def test_spot_hdfc_small_cap(self):
        f = self._find(["hdfc", "small"])
        assert f, "HDFC Small Cap not found"
        assert f.get("morningstar_rating") == 4
        assert f.get("category_rank_total") in (15, 16, 17, 18, 19)
        sub = (f.get("category_rank_sub") or "").lower()
        assert "small" in sub, sub
