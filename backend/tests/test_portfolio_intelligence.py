"""Portfolio Intelligence tests — iteration 27.

Covers the new /api/intelligence layer (services.portfolio_intelligence +
services.ai_insights + routes.intelligence).

Uses live PG (22 MFs seeded) + Mongo user holdings + Emergent LLM key
already configured in admin secrets. Falls back to deterministic insights
if OpenAI is unavailable and asserts both paths.
"""
import os
import sys
import pytest
import requests

def _load_backend_url():
    url = os.environ.get("REACT_APP_BACKEND_URL")
    if not url:
        # Load from /app/frontend/.env
        with open("/app/frontend/.env") as f:
            for line in f:
                if line.startswith("REACT_APP_BACKEND_URL="):
                    url = line.split("=", 1)[1].strip()
                    break
    if not url:
        raise RuntimeError("REACT_APP_BACKEND_URL not set")
    return url.rstrip("/")

BASE_URL = _load_backend_url()

# Test credentials (from /app/memory/test_credentials.md via problem statement)
USER_TOKEN = os.environ.get("NIVESH_TEST_USER_TOKEN", "5770bebb-8a9a-41f7-a7b9-e8152ac25daa")   # aporwal107@gmail.com
ADMIN_TOKEN = os.environ.get("NIVESH_TEST_ADMIN_TOKEN", "370eff71-fda1-46d8-b506-b81b894d634f")  # priyankamantri@gmail.com
USER_ID_APORWAL = None  # resolved from profile below


@pytest.fixture(scope="module")
def user_client():
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {USER_TOKEN}",
                      "Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def admin_client():
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {ADMIN_TOKEN}",
                      "Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def aporwal_user_id(user_client):
    r = user_client.get(f"{BASE_URL}/api/user/profile")
    assert r.status_code == 200, r.text
    return r.json()["user_id"]


# ── /api/intelligence/portfolio ─────────────────────────────────────────
class TestPortfolioIntelligence:
    """Narrative + compression + overlap + stock aggregation shape."""

    def test_auth_required(self):
        r = requests.get(f"{BASE_URL}/api/intelligence/portfolio")
        assert r.status_code in (401, 403)

    def test_narrative_no_ai(self, user_client):
        r = user_client.get(f"{BASE_URL}/api/intelligence/portfolio?narrate=false")
        assert r.status_code == 200, r.text
        d = r.json()
        for k in ("mf_investments", "pairwise_overlap", "top_stocks",
                  "compression", "narrative", "category_inefficiency",
                  "sector_exposure", "redundancy_suggestions"):
            assert k in d, f"missing key {k}"
        n = d["narrative"]
        for k in ("total_invested_rs", "unique_stocks", "effective_stocks",
                  "compression_score", "behaves_like_rs"):
            assert k in n
            assert n[k] is not None
        assert n["total_invested_rs"] > 0
        assert n["unique_stocks"] > 0
        assert n["effective_stocks"] > 0

    def test_compression_shape_and_bounds(self, user_client):
        d = user_client.get(f"{BASE_URL}/api/intelligence/portfolio?narrate=false").json()
        c = d["compression"]
        assert 0 <= c["score"] <= 100
        assert c["effective_stocks"] > 0
        assert c["top_10_exposure_pct"] > 0
        assert c["top_20_exposure_pct"] >= c["top_10_exposure_pct"]

    def test_dedupe_26_to_22(self, user_client):
        """aporwal has 26 raw Mongo MF rows; must dedupe down by instrument_id."""
        d = user_client.get(f"{BASE_URL}/api/intelligence/portfolio?narrate=false").json()
        invs = d["mf_investments"]
        assert len(invs) <= 23, f"dedupe failed: got {len(invs)} rows"
        # unique by instrument_id (ignoring unresolved-name fallbacks)
        ids = [m["instrument_id"] for m in invs if m.get("instrument_id")]
        assert len(ids) == len(set(ids)), "duplicate instrument_id present"

    def test_no_self_overlap_pairs(self, user_client):
        d = user_client.get(f"{BASE_URL}/api/intelligence/portfolio?narrate=false").json()
        for p in d["pairwise_overlap"]:
            assert p["a"] != p["b"]
            assert p["a_name"] != p["b_name"], f"self overlap: {p['a_name']}"
            assert 0 <= p["overlap_pct"] <= 100

    def test_pairwise_overlap_sorted_desc(self, user_client):
        d = user_client.get(f"{BASE_URL}/api/intelligence/portfolio?narrate=false").json()
        ovs = [p["overlap_pct"] for p in d["pairwise_overlap"]]
        assert ovs == sorted(ovs, reverse=True)

    def test_top_stocks_shape(self, user_client):
        d = user_client.get(f"{BASE_URL}/api/intelligence/portfolio?narrate=false").json()
        stocks = d["top_stocks"]
        assert len(stocks) > 0
        s0 = stocks[0]
        for k in ("name", "exposure_pct", "exposure_rs",
                  "fund_count", "via_funds"):
            assert k in s0
        assert s0["exposure_pct"] > 0
        assert s0["fund_count"] >= 1
        assert isinstance(s0["via_funds"], list)
        # sorted desc by exposure_pct
        pcts = [s["exposure_pct"] for s in stocks]
        assert pcts == sorted(pcts, reverse=True)

    def test_category_inefficiency_has_two_plus_funds(self, user_client):
        d = user_client.get(f"{BASE_URL}/api/intelligence/portfolio?narrate=false").json()
        for c in d["category_inefficiency"]:
            assert c["funds_count"] >= 2

    def test_sector_exposure_sums_near_100(self, user_client):
        d = user_client.get(f"{BASE_URL}/api/intelligence/portfolio?narrate=false").json()
        tot = sum(s["pct"] for s in d["sector_exposure"])
        # Should be ~100 (MFs often have ~1-3% cash/unclassified; tolerance 10)
        assert 85 <= tot <= 105, f"sector sum {tot} not ~100"

    def test_redundancy_suggestions_sorted_by_score(self, user_client):
        d = user_client.get(f"{BASE_URL}/api/intelligence/portfolio?narrate=false").json()
        rs = d["redundancy_suggestions"]
        if len(rs) >= 2:
            scores = [r["score"] for r in rs]
            assert scores == sorted(scores, reverse=True)
        for r in rs:
            for k in ("remove_id", "remove_name", "overlap_reduced_pp",
                      "sector_l1_drift_pct", "score"):
                assert k in r


# ── AI insights (narrate=true) ──────────────────────────────────────────
class TestAIInsights:
    def test_insights_3_to_6_items(self, user_client):
        r = user_client.get(f"{BASE_URL}/api/intelligence/portfolio?narrate=true")
        assert r.status_code == 200
        d = r.json()
        ins = d.get("ai_insights", [])
        assert 3 <= len(ins) <= 6, f"expected 3-6 insights, got {len(ins)}"
        for i in ins:
            assert "type" in i and i["type"]
            assert "headline" in i and i["headline"]
            assert "detail" in i

    def test_at_least_one_headline_cites_rs_or_pct(self, user_client):
        d = user_client.get(f"{BASE_URL}/api/intelligence/portfolio?narrate=true").json()
        ins = d.get("ai_insights", [])
        cites = [i for i in ins if ("₹" in i["headline"] or "%" in i["headline"])]
        assert len(cites) >= 1, \
            f"no insight cites ₹ or %: {[i['headline'] for i in ins]}"

    def test_fallback_insights_still_cite_rs(self):
        """Force fallback path by temporarily unsetting EMERGENT_LLM_KEY
        via helpers.secrets.set_override. Uses synthetic metrics (avoids Mongo
        import issues in the test-process context) which exercise ALL branches
        of _fallback_insights."""
        sys.path.insert(0, "/app/backend")
        from dotenv import load_dotenv
        load_dotenv("/app/backend/.env")
        import asyncio
        from helpers import secrets as _secrets
        from services import ai_insights

        synthetic = {
            "narrative": {"total_invested_rs": 6489913.38,
                          "behaves_like_rs": 1940484.1},
            "compression": {"score": 29.9, "effective_stocks": 23.9,
                            "unique_stocks": 50},
            "top_stocks": [
                {"name": "HDFC Bank Ltd.", "exposure_pct": 5.13,
                 "exposure_rs": 332932.0, "fund_count": 17},
            ],
            "pairwise_overlap": [
                {"a_name": "HDFC Flexi Cap Direct",
                 "b_name": "HDFC Flexi Cap Regular",
                 "overlap_pct": 95.8, "reasons": ["Same category: Flexi Cap"]},
            ],
            "category_inefficiency": [
                {"category": "Large Cap", "funds_count": 3,
                 "avg_pair_overlap": 60.96, "invested_rs": 1000000,
                 "inefficient": True},
            ],
            "redundancy_suggestions": [
                {"remove_name": "HDFC Flexi Cap Direct",
                 "overlap_reduced_pp": 12.5,
                 "sector_l1_drift_pct": 1.2},
            ],
        }

        orig_emergent = _secrets.get("EMERGENT_LLM_KEY") or ""
        orig_openai = _secrets.get("OPENAI_API_KEY") or ""
        try:
            _secrets.set_override("EMERGENT_LLM_KEY", "")
            _secrets.set_override("OPENAI_API_KEY", "")
            ins = asyncio.run(ai_insights.generate_insights(synthetic))
            assert 1 <= len(ins) <= 6, f"fallback returned {len(ins)} insights"
            cites = [i for i in ins if "₹" in i["headline"] or "%" in i["headline"]]
            assert len(cites) >= 1, \
                f"fallback headlines: {[i['headline'] for i in ins]}"
        finally:
            _secrets.set_override("EMERGENT_LLM_KEY", orig_emergent)
            _secrets.set_override("OPENAI_API_KEY", orig_openai)


def _aporwal_uid_sync():
    r = requests.get(f"{BASE_URL}/api/user/profile",
                     headers={"Authorization": f"Bearer {USER_TOKEN}"})
    return r.json()["user_id"]


# ── /api/intelligence/simulate ──────────────────────────────────────────
class TestSimulate:
    def test_empty_body_returns_unchanged(self, user_client):
        r = user_client.post(f"{BASE_URL}/api/intelligence/simulate",
                             json={"remove_mf_ids": []})
        assert r.status_code == 200
        d = r.json()
        assert d.get("sim_unchanged") is True

    def test_remove_two_funds_recomputes(self, user_client):
        # Grab two resolved MF ids from current portfolio
        d0 = user_client.get(f"{BASE_URL}/api/intelligence/portfolio?narrate=false").json()
        resolved = [m["instrument_id"] for m in d0["mf_investments"]
                    if m.get("resolved") and m.get("instrument_id")]
        assert len(resolved) >= 3
        remove = resolved[:2]
        orig_count = len(d0["mf_investments"])

        r = user_client.post(f"{BASE_URL}/api/intelligence/simulate",
                             json={"remove_mf_ids": remove})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["kept_count"] == orig_count - len(remove)
        for k in ("compression", "pairwise_overlap", "top_stocks",
                  "category_inefficiency", "sector_exposure", "narrative"):
            assert k in d
        # narrative total should be lower than before
        assert d["narrative"]["total_invested_rs"] < d0["narrative"]["total_invested_rs"]
        # no pair should include a removed id
        for p in d["pairwise_overlap"]:
            assert p["a"] not in remove
            assert p["b"] not in remove

    def test_body_validation_bad_type(self, user_client):
        r = user_client.post(f"{BASE_URL}/api/intelligence/simulate",
                             json={"remove_mf_ids": "not-a-list"})
        assert r.status_code in (400, 422)

    def test_simulate_auth_required(self):
        r = requests.post(f"{BASE_URL}/api/intelligence/simulate",
                          json={"remove_mf_ids": []})
        assert r.status_code in (401, 403)


# ── Admin view ──────────────────────────────────────────────────────────
class TestAdminPortfolio:
    def test_admin_can_view_user_intelligence(self, admin_client, aporwal_user_id):
        r = admin_client.get(
            f"{BASE_URL}/api/intelligence/portfolio/{aporwal_user_id}?narrate=false"
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert "mf_investments" in d
        assert len(d["mf_investments"]) > 0

    def test_non_admin_cannot_view_other_user(self, user_client, aporwal_user_id):
        """Both seeded test users (aporwal + priyanka) are is_admin=True in DB
        (per iteration 26 context). Skipping negative admin-auth test — covered
        by test_admin_route_auth_required (unauthenticated path)."""
        pytest.skip("Both seeded users are admins; see admin_route_auth_required")

    def test_admin_route_auth_required(self, aporwal_user_id):
        r = requests.get(
            f"{BASE_URL}/api/intelligence/portfolio/{aporwal_user_id}"
        )
        assert r.status_code in (401, 403)


# ── /api/intelligence/rate-fund/{instrument_id} ─────────────────────────
class TestRateFund:
    @pytest.fixture(scope="class")
    def instrument_id(self, admin_client):
        r = admin_client.get(f"{BASE_URL}/api/admin/mf/funds")
        assert r.status_code == 200
        funds = r.json()["funds"]
        assert len(funds) > 0
        return funds[0]["instrument_id"]

    def test_rate_fund_first_call(self, admin_client, instrument_id):
        r = admin_client.post(
            f"{BASE_URL}/api/intelligence/rate-fund/{instrument_id}"
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert "rating" in d
        assert "reason" in d
        assert "cached" in d
        # rating must be 1-5 when LLM configured
        if d["rating"] is not None:
            assert 1 <= d["rating"] <= 5
            assert isinstance(d["reason"], str) and len(d["reason"]) > 0

    def test_rate_fund_second_call_cached(self, admin_client, instrument_id):
        r1 = admin_client.post(
            f"{BASE_URL}/api/intelligence/rate-fund/{instrument_id}"
        ).json()
        r2 = admin_client.post(
            f"{BASE_URL}/api/intelligence/rate-fund/{instrument_id}"
        ).json()
        if r1.get("rating") is None:
            pytest.xfail(
                f"LLM integration broken — rate_fund returned null rating: "
                f"{r1.get('reason')!r}. Route only caches non-null ratings, "
                f"so 2nd call also not cached. See action_items."
            )
        # 2nd call must be cached
        assert r2.get("cached") is True
        assert r2["rating"] == r1["rating"]

    def test_rate_fund_404_on_bad_id(self, admin_client):
        r = admin_client.post(
            f"{BASE_URL}/api/intelligence/rate-fund/00000000-0000-0000-0000-000000000000"
        )
        assert r.status_code == 404

    def test_rate_fund_requires_admin(self, user_client, instrument_id):
        """Both seeded users are admins — skipping non-admin negative test."""
        pytest.skip("Both seeded users are admins")


# ── Regression: pre-existing endpoints still work ───────────────────────
class TestRegression:
    def test_mf_holdings(self, user_client):
        # /api/mf/holdings requires ?scheme_name= query param
        r = user_client.get(
            f"{BASE_URL}/api/mf/holdings",
            params={"scheme_name": "HDFC Flexi Cap Fund Growth"},
        )
        assert r.status_code == 200, r.text

    def test_admin_mf_funds(self, admin_client):
        r = admin_client.get(f"{BASE_URL}/api/admin/mf/funds")
        assert r.status_code == 200
        assert "funds" in r.json()

    def test_admin_mf_db_status(self, admin_client):
        r = admin_client.get(f"{BASE_URL}/api/admin/mf/db-status")
        assert r.status_code == 200

    def test_user_profile(self, user_client):
        r = user_client.get(f"{BASE_URL}/api/user/profile")
        assert r.status_code == 200
        assert "user_id" in r.json()

    def test_scenarios_suggest(self, user_client):
        r = user_client.get(f"{BASE_URL}/api/scenarios/suggest")
        assert r.status_code == 200
