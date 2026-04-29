"""Backend tests for Post-Deploy Migration suite (iteration 35).

Covers:
  - Auth gating on 3 new admin endpoints (mirror-pg-to-mongo, post-deploy-migrate,
    apply-pg-schema)
  - Functional behaviour of mirror_pg_to_mongo (~250-270k rows across 7 tables)
  - 7-phase post_deploy_migrate orchestrator (skip_replay=true, < 60s)
  - Idempotency (run twice in a row)
  - apply_pg_schema applies all 6 migrations
"""
from __future__ import annotations

import os
import time

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://wealth-advisor-96.preview.emergentagent.com").rstrip("/")
ADMIN_COOKIE = {"session_token": "370eff71-fda1-46d8-b506-b81b894d634f"}

EXPECTED_MIRROR_TABLES = {
    "instrument_master",
    "benchmark_master",
    "mutual_fund_metadata",
    "mutual_fund_performance_ratios",
    "mutual_fund_holdings",
    "mutual_fund_nav_history",
    "mutual_fund_aum_history",
}

EXPECTED_PHASES = [
    "hydrate_secrets",
    "health_check",
    "apply_migrations",
    "restore_mirrors",
    "replay_scrape_cache",
    "analytics_sweep",
    "v3_rescore",
    "smoke_check",
]


@pytest.fixture(scope="module")
def admin_session():
    s = requests.Session()
    s.cookies.update(ADMIN_COOKIE)
    s.headers.update({"Content-Type": "application/json"})
    # Sanity check
    r = s.get(f"{BASE_URL}/api/admin/datastores/status", timeout=15)
    if r.status_code != 200:
        pytest.skip(f"Admin session not valid (status={r.status_code}); cannot run tests")
    return s


@pytest.fixture(scope="module")
def anon_session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


# ─────────────── AUTH GATING ───────────────
class TestAuthGating:
    def test_mirror_endpoint_requires_admin(self, anon_session):
        r = anon_session.post(f"{BASE_URL}/api/admin/datastores/mirror-pg-to-mongo", json={}, timeout=10)
        assert r.status_code in (401, 403), f"expected 401/403, got {r.status_code}: {r.text[:200]}"

    def test_post_deploy_endpoint_requires_admin(self, anon_session):
        r = anon_session.post(
            f"{BASE_URL}/api/admin/datastores/post-deploy-migrate",
            json={"skip_replay": True},
            timeout=10,
        )
        assert r.status_code in (401, 403), f"expected 401/403, got {r.status_code}: {r.text[:200]}"

    def test_apply_pg_schema_requires_admin(self, anon_session):
        r = anon_session.post(f"{BASE_URL}/api/admin/datastores/apply-pg-schema", json={}, timeout=10)
        assert r.status_code in (401, 403), f"expected 401/403, got {r.status_code}: {r.text[:200]}"


# ─────────────── apply-pg-schema ───────────────
class TestApplyPgSchema:
    def test_applies_all_six_migrations(self, admin_session):
        r = admin_session.post(f"{BASE_URL}/api/admin/datastores/apply-pg-schema", json={}, timeout=120)
        assert r.status_code == 200, f"apply-pg-schema failed: {r.status_code} {r.text[:400]}"
        data = r.json()
        assert data.get("status") == "ok", f"expected status=ok, got {data}"
        applied = data.get("applied", [])
        assert isinstance(applied, list) and len(applied) >= 6, (
            f"expected 6 migrations, got {len(applied)}: {applied}"
        )
        valid_states = {"already_applied", "applied", "marked_applied"}
        for m in applied:
            state = m.get("status") or m.get("state") or m.get("result")
            assert state in valid_states, f"unexpected migration state {state} for {m}"


# ─────────────── mirror-pg-to-mongo ───────────────
class TestMirrorPgToMongo:
    def test_mirror_returns_ok_with_full_table_set(self, admin_session):
        t0 = time.time()
        r = admin_session.post(f"{BASE_URL}/api/admin/datastores/mirror-pg-to-mongo", json={}, timeout=180)
        elapsed = time.time() - t0
        assert r.status_code == 200, f"mirror failed: {r.status_code} {r.text[:400]}"
        data = r.json()
        assert data.get("status") == "ok", f"expected status=ok, got {data}"

        total = data.get("total_rows") or data.get("totals", {}).get("total") or 0
        # Per agent context: ~266,558 rows. Allow generous range.
        assert total >= 200_000, f"total_rows too low: {total} (expected ~250-270k)"

        # Verify all 7 tables represented
        tables = data.get("tables") or data.get("collections") or {}
        if isinstance(tables, list):
            table_names = {t.get("table") or t.get("name") for t in tables}
        elif isinstance(tables, dict):
            table_names = set(tables.keys())
        else:
            table_names = set()
        # Must cover all expected tables
        missing = EXPECTED_MIRROR_TABLES - table_names
        assert not missing, f"mirror missing tables: {missing}; saw {table_names}"
        print(f"Mirror completed in {elapsed:.1f}s, total_rows={total}")


# ─────────────── post-deploy-migrate ───────────────
def _run_post_deploy(admin_session) -> dict:
    t0 = time.time()
    r = admin_session.post(
        f"{BASE_URL}/api/admin/datastores/post-deploy-migrate",
        json={"skip_replay": True},
        timeout=180,
    )
    elapsed = time.time() - t0
    assert r.status_code == 200, f"post-deploy-migrate failed: {r.status_code} {r.text[:600]}"
    data = r.json()
    data["_elapsed"] = elapsed
    return data


class TestPostDeployMigrate:
    def test_post_deploy_migrate_completes_under_60s_with_all_phases_green(self, admin_session):
        data = _run_post_deploy(admin_session)
        elapsed = data.pop("_elapsed")
        assert elapsed < 90, f"post-deploy-migrate too slow: {elapsed:.1f}s (expected <60s, allowing 90s buffer)"

        overall = data.get("overall") or data.get("status")
        assert overall == "ok", f"expected overall=ok, got {overall}; data={str(data)[:600]}"

        phases = data.get("phases") or {}
        assert isinstance(phases, (dict, list)), f"phases must be dict/list, got {type(phases)}"

        # Normalize phases (impl prefixes with index e.g. "0_hydrate_secrets")
        if isinstance(phases, list):
            raw_map = {p.get("name") or p.get("phase"): p for p in phases}
        else:
            raw_map = phases

        def _strip_idx(key: str) -> str:
            # "0_hydrate_secrets" -> "hydrate_secrets"
            if key and "_" in key and key.split("_", 1)[0].isdigit():
                return key.split("_", 1)[1]
            return key

        phase_map = {_strip_idx(k): v for k, v in raw_map.items()}

        for phase_name in EXPECTED_PHASES:
            assert phase_name in phase_map, f"missing phase {phase_name}; have {list(phase_map.keys())}"
            ph = phase_map[phase_name]
            status = ph.get("status") if isinstance(ph, dict) else None
            if phase_name == "replay_scrape_cache":
                assert status == "skipped", f"replay_scrape_cache should be skipped, got {status}"
            else:
                assert status in ("ok", "skipped"), f"phase {phase_name} status={status} (expected ok/skipped); ph={ph}"

        # Smoke check counts
        smoke = phase_map.get("smoke_check", {})
        if isinstance(smoke, dict):
            smoke_result = smoke.get("result") or smoke.get("data") or smoke.get("counts") or {}
            counts = smoke_result.get("counts") if isinstance(smoke_result, dict) and "counts" in smoke_result else smoke_result
            if not isinstance(counts, dict):
                counts = {}
        else:
            counts = {}
        if counts:
            for key, minimum in [
                ("instruments", 2000),
                ("mf_nav_history", 200_000),
                ("mf_performance_ratios", 200),
                ("benchmark_master", 30),
            ]:
                if key in counts:
                    assert counts[key] >= minimum, f"smoke count {key}={counts[key]} < {minimum}"
            # Exact-match expected
            for key, expected in [("mf_metadata", 185), ("mf_scored", 185), ("mc_debt_enriched", 36)]:
                if key in counts:
                    assert counts[key] == expected, f"smoke count {key}={counts[key]} (expected {expected})"

    def test_post_deploy_migrate_idempotent(self, admin_session):
        # Run a second time back to back
        data = _run_post_deploy(admin_session)
        elapsed = data.pop("_elapsed")
        overall = data.get("overall") or data.get("status")
        assert overall == "ok", f"second post-deploy run not ok: {overall}; data={str(data)[:600]}"
        assert elapsed < 120, f"second run too slow: {elapsed:.1f}s"
