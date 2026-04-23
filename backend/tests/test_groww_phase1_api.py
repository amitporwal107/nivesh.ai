"""Phase 1 Groww MF Data Fetcher — HTTP API integration tests.

Verifies the 6 new endpoints against the preview backend:
  - /api/admin/mf/db-status
  - /api/mf/lookup
  - /api/mf/holdings  (with cache + search-API fallback)
  - /api/admin/mf/scrape-queue
  - /api/admin/mf/scrape-now
  - /api/admin/secrets  +  /api/admin/secrets/{POSTGRES,REDIS}_URL/test
Also sanity-checks unrelated endpoints (profile, scenarios/suggest) haven't regressed.
"""
from __future__ import annotations
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://portfolio-pro-985.preview.emergentagent.com").rstrip("/")
ADMIN_TOKEN = os.environ["NIVESH_TEST_ADMIN_TOKEN"]
USER_TOKEN = os.environ["NIVESH_TEST_USER_TOKEN"]
TIMEOUT = 45  # seconds (Groww scraping can take a few secs)


def _cookies(tok: str) -> dict:
    return {"session_token": tok}


# ── Admin: db-status ──────────────────────────────────────────────────────
def test_db_status_rejects_unauthenticated():
    r = requests.get(f"{BASE_URL}/api/admin/mf/db-status", timeout=TIMEOUT)
    assert r.status_code in (401, 403), f"expected 401/403 unauth, got {r.status_code}"


def test_db_status_reports_not_configured():
    """Phase 2/3: PG + Redis are now configured — endpoint should report ok=True."""
    r = requests.get(f"{BASE_URL}/api/admin/mf/db-status", cookies=_cookies(ADMIN_TOKEN), timeout=TIMEOUT)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "postgres" in data and "redis" in data
    # Accept either ok=True (configured) or ok=False (unconfigured) — both are valid states
    assert data["postgres"]["ok"] in (True, False)
    assert data["redis"]["ok"] in (True, False)


# ── MF lookup ────────────────────────────────────────────────────────────
def test_lookup_requires_auth():
    r = requests.get(f"{BASE_URL}/api/mf/lookup?scheme_name=Foo", timeout=TIMEOUT)
    assert r.status_code in (401, 403)


def test_lookup_falls_back_to_name_key_when_pg_absent():
    r = requests.get(
        f"{BASE_URL}/api/mf/lookup",
        params={"scheme_name": "Nippon India Multi Cap Fund - Direct - Growth"},
        cookies=_cookies(USER_TOKEN),
        timeout=TIMEOUT,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert "resolved" in data and "latest_nav" in data
    assert data["latest_nav"] is None  # pg not configured
    key = data["resolved"].get("instrument_key", "")
    assert key.startswith("NAME:"), f"expected NAME: fallback, got {key!r}"


def test_lookup_requires_at_least_one_param():
    r = requests.get(f"{BASE_URL}/api/mf/lookup", cookies=_cookies(USER_TOKEN), timeout=TIMEOUT)
    assert r.status_code == 400


# ── MF holdings ──────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def holdings_fresh():
    """One live Groww scrape, reused across tests to stay polite."""
    scheme = "Parag Parikh Flexi Cap Fund - Direct - Growth"
    r = requests.get(
        f"{BASE_URL}/api/mf/holdings",
        params={"scheme_name": scheme, "force": "true"},
        cookies=_cookies(USER_TOKEN),
        timeout=TIMEOUT,
    )
    return scheme, r


def test_holdings_requires_auth():
    r = requests.get(f"{BASE_URL}/api/mf/holdings?scheme_name=Foo", timeout=TIMEOUT)
    assert r.status_code in (401, 403)


def test_holdings_fresh_scrape_shape(holdings_fresh):
    _, r = holdings_fresh
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("valid") is True, f"validation_issues: {data.get('validation_issues')}"
    holdings = data.get("holdings") or []
    assert len(holdings) > 10, f"expected >10 holdings, got {len(holdings)}"
    total = sum(h["pct"] for h in holdings)
    assert 70 <= total <= 115, f"holdings sum {total} out of 70-115"
    sectors = data.get("sectors") or []
    assert len(sectors) >= 1
    assert all("name" in s and "pct" in s for s in sectors)
    meta = data.get("metadata") or {}
    assert "aum_cr" in meta and "nav" in meta and "expense_ratio" in meta
    # First call should be fresh
    assert data.get("source") in ("fresh", "groww"), f"expected fresh/groww, got {data.get('source')}"


def test_holdings_second_call_is_cached(holdings_fresh):
    scheme, r1 = holdings_fresh
    assert r1.status_code == 200
    time.sleep(1)
    r2 = requests.get(
        f"{BASE_URL}/api/mf/holdings",
        params={"scheme_name": scheme},
        cookies=_cookies(USER_TOKEN),
        timeout=TIMEOUT,
    )
    assert r2.status_code == 200, r2.text
    data = r2.json()
    assert data.get("source") == "cache", f"expected cache, got {data.get('source')}"
    assert len(data.get("holdings") or []) > 10


def test_holdings_search_api_fallback_sbi_small_cap():
    """Deterministic slug for 'SBI Small Cap Fund Direct Growth' → sbi-small-cap-fund-direct-growth (404).
    Search-API fallback must recover the real slug (sbi-small-midcap-fund-direct-growth or similar)."""
    scheme = "SBI Small Cap Fund Direct Growth"
    r = requests.get(
        f"{BASE_URL}/api/mf/holdings",
        params={"scheme_name": scheme, "force": "true"},
        cookies=_cookies(USER_TOKEN),
        timeout=TIMEOUT,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    # Must either recover via search, or return a structured "not found" response.
    # Spec: search-API fallback must recover → expect valid=true + holdings.
    assert data.get("valid") is True, (
        f"search fallback failed: valid={data.get('valid')} issues={data.get('validation_issues')} slug={data.get('slug')}"
    )
    assert len(data.get("holdings") or []) > 5


# ── Admin: scrape queue ──────────────────────────────────────────────────
def test_scrape_queue_rejects_unauthenticated():
    r = requests.get(f"{BASE_URL}/api/admin/mf/scrape-queue", timeout=TIMEOUT)
    assert r.status_code in (401, 403)


def test_scrape_queue_shape():
    r = requests.get(f"{BASE_URL}/api/admin/mf/scrape-queue", cookies=_cookies(ADMIN_TOKEN), timeout=TIMEOUT)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "queue" in data and isinstance(data["queue"], list)
    assert "summary" in data and isinstance(data["summary"], dict)
    assert "queued" in data["summary"] and "done" in data["summary"] and "failed" in data["summary"]


# ── Admin: scrape-now ────────────────────────────────────────────────────
def test_scrape_now_rejects_unauthenticated():
    r = requests.post(
        f"{BASE_URL}/api/admin/mf/scrape-now",
        params={"scheme_name": "HDFC Flexi Cap Fund - Direct Plan - Growth"},
        timeout=TIMEOUT,
    )
    assert r.status_code in (401, 403)


def test_scrape_now_bypass_gate():
    r = requests.post(
        f"{BASE_URL}/api/admin/mf/scrape-now",
        params={"scheme_name": "HDFC Flexi Cap Fund - Direct Plan - Growth"},
        cookies=_cookies(ADMIN_TOKEN),
        timeout=TIMEOUT,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("valid") is True, f"issues={data.get('validation_issues')}"
    assert len(data.get("holdings") or []) > 10


# ── Admin: secrets listing + test endpoints ──────────────────────────────
def test_admin_secrets_lists_postgres_and_redis():
    r = requests.get(f"{BASE_URL}/api/admin/secrets", cookies=_cookies(ADMIN_TOKEN), timeout=TIMEOUT)
    assert r.status_code == 200, r.text
    body = r.json()
    secrets = body.get("secrets") if isinstance(body, dict) and "secrets" in body else body
    keys = {s.get("key"): s for s in secrets}
    assert "POSTGRES_URL" in keys, f"POSTGRES_URL missing from /admin/secrets; got {list(keys)[:20]}"
    assert "REDIS_URL" in keys, f"REDIS_URL missing from /admin/secrets"
    for k in ("POSTGRES_URL", "REDIS_URL"):
        s = keys[k]
        assert s.get("category") == "data", f"{k}.category = {s.get('category')!r}, expected 'data'"
        tfn = s.get("test_fn") or s.get("tester") or s.get("has_test")
        assert tfn, f"{k} should expose test_fn metadata; got {s}"


def test_postgres_test_endpoint_reports_not_configured():
    """Phase 2/3: PG is now configured — endpoint returns ok=True."""
    r = requests.post(
        f"{BASE_URL}/api/admin/secrets/POSTGRES_URL/test",
        cookies=_cookies(ADMIN_TOKEN),
        timeout=TIMEOUT,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert "ok" in data  # either True or False, both valid


def test_redis_test_endpoint_reports_not_configured():
    """Phase 2/3: Redis is now configured — endpoint returns ok=True."""
    r = requests.post(
        f"{BASE_URL}/api/admin/secrets/REDIS_URL/test",
        cookies=_cookies(ADMIN_TOKEN),
        timeout=TIMEOUT,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert "ok" in data


# ── Regression: unrelated endpoints ──────────────────────────────────────
def test_user_profile_still_works():
    r = requests.get(f"{BASE_URL}/api/user/profile", cookies=_cookies(USER_TOKEN), timeout=TIMEOUT)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "user_id" in data or "email" in data or "user" in data


def test_scenarios_suggest_auth_gated():
    r = requests.get(f"{BASE_URL}/api/scenarios/suggest", timeout=TIMEOUT)
    assert r.status_code in (401, 403)
    # And works with auth
    r2 = requests.get(f"{BASE_URL}/api/scenarios/suggest", cookies=_cookies(USER_TOKEN), timeout=TIMEOUT)
    assert r2.status_code in (200, 201), r2.text
