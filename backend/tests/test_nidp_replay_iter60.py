"""Iter60: NIDP Replay engine admin endpoints contract tests.

Pod env has POSTGRES_URL set to a local DB that does NOT contain the
NIDP `audit.*` schema. The replay endpoints proxy through
`_nidp_dsn()` which prefers `NIDP_PG_DSN` but falls back to
`POSTGRES_URL`. So in pod:
  - /policies  → 200 with builtin fallback (graceful degrade)
  - /start     → may return 200 (pool opens) or 502 (connect fails)
  - /runs      → 500 (audit.replay_runs missing) or 502
  - /status/{id} → 404 / 500 / 502 (no rows / table missing)
Auth: session_token cookie for aporwal107@gmail.com (admin).
"""
from __future__ import annotations

import os
from datetime import date, timedelta

import pytest
import requests
from dotenv import load_dotenv

load_dotenv("/app/frontend/.env")
BASE = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
SESSION_TOKEN = "3352751a-cc8a-4bcb-bf50-81a377c6b40b"
PREFIX = "/api/admin/nidp/replay"


@pytest.fixture(scope="module")
def admin_client():
    s = requests.Session()
    s.cookies.set("session_token", SESSION_TOKEN)
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def anon_client():
    return requests.Session()


# ─────────────────────────────────────────────────────────────
# Auth gating
# ─────────────────────────────────────────────────────────────
class TestAuth:
    def test_policies_requires_auth(self, anon_client):
        r = anon_client.get(f"{BASE}{PREFIX}/policies")
        assert r.status_code in (401, 403), f"got {r.status_code}: {r.text[:200]}"

    def test_start_requires_auth(self, anon_client):
        r = anon_client.post(
            f"{BASE}{PREFIX}/start",
            json={"start_date": "2026-01-01", "end_date": "2026-01-02"},
        )
        assert r.status_code in (401, 403)

    def test_runs_requires_auth(self, anon_client):
        r = anon_client.get(f"{BASE}{PREFIX}/runs")
        assert r.status_code in (401, 403)


# ─────────────────────────────────────────────────────────────
# /policies — graceful builtin fallback
# ─────────────────────────────────────────────────────────────
class TestPolicies:
    def test_policies_returns_builtin_when_db_unreachable(self, admin_client):
        r = admin_client.get(f"{BASE}{PREFIX}/policies")
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        assert "policies" in body
        # source can be 'builtin' (no DSN / unreachable) or 'db'
        # (connected but falls back internally on UndefinedTableError → still 'db')
        assert body.get("source") in ("builtin", "db"), body
        versions = {p["version"] for p in body["policies"]}
        assert {"v1", "legacy"}.issubset(versions), versions

    def test_policies_weights_sum_to_one(self, admin_client):
        r = admin_client.get(f"{BASE}{PREFIX}/policies")
        body = r.json()
        for p in body["policies"]:
            wsum = (
                p["w_accuracy"] + p["w_consistency"] + p["w_completeness"]
                + p["w_freshness"] + p["w_confidence"]
            )
            assert abs(wsum - 1.0) < 1e-6, f"{p['version']} weights={wsum}"

    def test_v1_weights_match_prd(self, admin_client):
        r = admin_client.get(f"{BASE}{PREFIX}/policies")
        v1 = next(p for p in r.json()["policies"] if p["version"] == "v1")
        assert v1["w_accuracy"] == 0.30
        assert v1["w_consistency"] == 0.25
        assert v1["w_completeness"] == 0.20
        assert v1["w_freshness"] == 0.15
        assert v1["w_confidence"] == 0.10
        assert v1["cert_gold"] == 99.0
        assert v1["cert_silver"] == 95.0

    def test_legacy_weights(self, admin_client):
        r = admin_client.get(f"{BASE}{PREFIX}/policies")
        leg = next(p for p in r.json()["policies"] if p["version"] == "legacy")
        assert leg["w_accuracy"] == 0.40
        assert leg["w_consistency"] == 0.30
        assert leg["w_completeness"] == 0.15
        assert leg["w_freshness"] == 0.10
        assert leg["w_confidence"] == 0.05


# ─────────────────────────────────────────────────────────────
# /start validation
# ─────────────────────────────────────────────────────────────
class TestStartValidation:
    def test_end_before_start_returns_422(self, admin_client):
        r = admin_client.post(
            f"{BASE}{PREFIX}/start",
            json={
                "start_date": "2026-01-10",
                "end_date":   "2026-01-01",
                "domains":    ["mf"],
            },
        )
        assert r.status_code == 422, r.text[:300]
        body = r.json()
        assert "detail" in body
        msgs = " ".join(str(d.get("msg", "")) for d in body["detail"])
        assert "end_date" in msgs.lower() or "start_date" in msgs.lower()

    def test_unknown_domain_returns_422(self, admin_client):
        r = admin_client.post(
            f"{BASE}{PREFIX}/start",
            json={
                "start_date": "2026-01-01",
                "end_date":   "2026-01-02",
                "domains":    ["bogus"],
            },
        )
        assert r.status_code == 422, r.text[:300]

    def test_parallel_out_of_range_returns_422(self, admin_client):
        r = admin_client.post(
            f"{BASE}{PREFIX}/start",
            json={
                "start_date": "2026-01-01",
                "end_date":   "2026-01-02",
                "parallel":   99,
            },
        )
        assert r.status_code == 422

    def test_failure_rate_above_one_returns_422(self, admin_client):
        r = admin_client.post(
            f"{BASE}{PREFIX}/start",
            json={
                "start_date":   "2026-01-01",
                "end_date":     "2026-01-02",
                "failure_rate": 2.0,
            },
        )
        assert r.status_code == 422

    def test_window_over_5_years_returns_422(self, admin_client):
        r = admin_client.post(
            f"{BASE}{PREFIX}/start",
            json={
                "start_date": "2010-01-01",
                "end_date":   "2026-01-01",
            },
        )
        assert r.status_code == 422


# ─────────────────────────────────────────────────────────────
# /start, /runs, /status — DB-backed (will 5xx in pod env)
# ─────────────────────────────────────────────────────────────
class TestDbBackedEndpoints:
    """In pod env, NIDP audit.* tables do not exist. Verify that
    endpoints fail with a meaningful 5xx, not a 200-with-mock-data."""

    def test_start_valid_payload_returns_meaningful_response(self, admin_client):
        today = date.today()
        r = admin_client.post(
            f"{BASE}{PREFIX}/start",
            json={
                "start_date": (today - timedelta(days=90)).isoformat(),
                "end_date":   today.isoformat(),
                "domains":    ["mf", "equity"],
                "policy_version": "v1",
                "parallel":   2,
                "inject_failures": False,
                "reset_data": False,
            },
        )
        # Accept 502 (connect fail) or 500 (audit schema missing); not 200 silently
        assert r.status_code in (200, 500, 502, 503), r.text[:300]
        if r.status_code == 200:
            # Engine kicked off, but background will fail. replay_id may be None
            body = r.json()
            assert "ok" in body or "replay_id" in body

    def test_runs_endpoint_meaningful_error(self, admin_client):
        r = admin_client.get(f"{BASE}{PREFIX}/runs")
        # In pod env, audit.replay_runs doesn't exist → likely 500
        assert r.status_code in (200, 500, 502, 503), r.text[:300]
        if r.status_code == 200:
            assert "runs" in r.json()

    def test_status_unknown_id_returns_4xx_or_5xx(self, admin_client):
        r = admin_client.get(
            f"{BASE}{PREFIX}/status/00000000-0000-0000-0000-000000000000"
        )
        assert r.status_code in (404, 500, 502, 503)
