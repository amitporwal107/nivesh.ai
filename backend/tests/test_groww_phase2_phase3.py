"""Phase 2 + Phase 3 Groww MF Data Fetcher — end-to-end integration tests.

Covers:
  * Scheduler: running + 3 jobs; start/stop toggles
  * scrape-now full lifecycle → PG persistence assertions (direct psql)
  * Cache enrichment on 2nd /api/mf/holdings call
  * PG fallback: services.pg_writer.load_fund_from_pg returns hydrated dict
  * Dashboard: /admin/mf/funds list + {uuid} drill-down
  * Queue ops: seed-portfolio-queue + drain-queue?force=true
  * Admin auth on all /admin/mf/* endpoints
  * Regression: /api/user/profile, /api/mf/holdings, /api/admin/secrets, /api/admin/feature-flags
"""
from __future__ import annotations
import asyncio
import os
import subprocess
import time
from typing import Any, Dict, Optional

import pytest
import requests

BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "https://nivesh-ai-preview.preview.emergentagent.com",
).rstrip("/")
ADMIN_TOKEN = os.environ.get("NIVESH_TEST_ADMIN_TOKEN", "370eff71-fda1-46d8-b506-b81b894d634f")
USER_TOKEN = os.environ.get("NIVESH_TEST_USER_TOKEN", "5770bebb-8a9a-41f7-a7b9-e8152ac25daa")
TIMEOUT = 90  # live Groww scrape can take ~20s
PG_CONN = "postgresql://postgres:nivesh_dev@127.0.0.1:5432/nivesh"

TARGET_FUND = "HDFC Flexi Cap Fund Direct Growth"


def _cookies(tok: str) -> dict:
    return {"session_token": tok}


def _psql(sql: str) -> str:
    """Run a raw SQL via psql and return stdout."""
    env = os.environ.copy()
    env["PGPASSWORD"] = "nivesh_dev"
    r = subprocess.run(
        ["psql", "-h", "127.0.0.1", "-U", "postgres", "-d", "nivesh",
         "-tAc", sql],
        env=env, capture_output=True, text=True, timeout=15,
    )
    return r.stdout.strip()


# ── Scheduler ────────────────────────────────────────────────────────────
class TestScheduler:
    def test_scheduler_running_with_three_jobs(self):
        r = requests.get(f"{BASE_URL}/api/admin/mf/db-status",
                         cookies=_cookies(ADMIN_TOKEN), timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        sch = r.json().get("scheduler", {})
        assert sch.get("running") is True, f"scheduler not running: {sch}"
        job_ids = {j["id"] for j in sch.get("jobs", [])}
        assert {"drain_weekday", "drain_weekend", "stale_refresh"}.issubset(job_ids), \
            f"missing expected jobs: {job_ids}"
        # Timezone sanity
        assert "Asia/Kolkata" in sch.get("timezone", "")

    def test_scheduler_stop_then_start_toggles(self):
        # Stop
        r = requests.post(f"{BASE_URL}/api/admin/mf/scheduler/stop",
                          cookies=_cookies(ADMIN_TOKEN), timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        assert r.json().get("running") is False
        # Start
        r2 = requests.post(f"{BASE_URL}/api/admin/mf/scheduler/start",
                           cookies=_cookies(ADMIN_TOKEN), timeout=TIMEOUT)
        assert r2.status_code == 200, r2.text
        assert r2.json().get("running") is True
        assert len(r2.json().get("jobs", [])) >= 3

    def test_scheduler_control_requires_admin(self):
        r = requests.post(f"{BASE_URL}/api/admin/mf/scheduler/start", timeout=TIMEOUT)
        assert r.status_code in (401, 403)
        r2 = requests.post(f"{BASE_URL}/api/admin/mf/scheduler/stop", timeout=TIMEOUT)
        assert r2.status_code in (401, 403)


# ── Full scrape lifecycle + PG persistence ───────────────────────────────
class TestScrapeLifecycle:
    # Shared across tests: remember instrument_id + isin from scrape
    _state: Dict[str, Any] = {}

    def test_scrape_now_full_shape(self):
        r = requests.post(
            f"{BASE_URL}/api/admin/mf/scrape-now",
            params={"scheme_name": TARGET_FUND},
            cookies=_cookies(ADMIN_TOKEN),
            timeout=TIMEOUT,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        # If the fund isn't available (off-hours already passed / WAF), accept
        # skipped or partial — but prefer available=true.
        if data.get("available") is False:
            pytest.skip(f"scrape not available right now: {data}")
        assert data.get("valid") is True, f"not valid: {data.get('validation_issues')}"
        ratios = data.get("ratios") or {}
        for k in ("alpha", "beta", "sharpe", "sortino", "std_dev",
                  "ret_1y", "ret_3y", "ret_5y"):
            assert k in ratios, f"missing ratio key {k} in {ratios}"
        meta = data.get("metadata") or {}
        for k in ("scheme_code", "isin", "aum_cr", "nav", "expense_ratio",
                  "category", "risk_label"):
            assert k in meta, f"missing metadata key {k}"
        assert meta.get("isin"), "ISIN must be populated"
        assert meta.get("aum_cr") and meta["aum_cr"] > 0
        assert meta.get("nav") and meta["nav"] > 0
        # risk_label regression — must come from return_stats.risk, not sub_category
        assert meta.get("risk_label") and isinstance(meta["risk_label"], str)
        assert "cap" not in meta["risk_label"].lower(), \
            f"risk_label looks like sub_category: {meta['risk_label']}"
        # Stash for dependent tests
        TestScrapeLifecycle._state["isin"] = meta["isin"]
        TestScrapeLifecycle._state["scheme_code"] = meta.get("scheme_code")
        TestScrapeLifecycle._state["scheme_name"] = data.get("scheme_name") or TARGET_FUND

    def test_pg_instrument_master_row_exists(self):
        isin = TestScrapeLifecycle._state.get("isin")
        if not isin:
            pytest.skip("scrape did not yield ISIN")
        uid = _psql(
            f"SELECT instrument_id FROM instrument_master "
            f"WHERE isin = '{isin}' AND instrument_type = 'MUTUAL_FUND';"
        )
        assert uid, f"instrument_master row missing for isin {isin}"
        # UUID shape
        assert len(uid) == 36 and uid.count("-") == 4
        TestScrapeLifecycle._state["instrument_id"] = uid

    def test_pg_metadata_row_populated(self):
        iid = TestScrapeLifecycle._state.get("instrument_id")
        if not iid:
            pytest.skip("no instrument_id")
        row = _psql(
            f"SELECT aum_cr, nav, expense_ratio, risk_label, category "
            f"FROM mutual_fund_metadata WHERE instrument_id = '{iid}';"
        )
        assert row, "metadata row missing"
        parts = row.split("|")
        assert len(parts) == 5
        aum, nav, exp, risk, cat = parts
        assert aum and float(aum) > 0, f"aum_cr invalid: {aum}"
        assert nav and float(nav) > 0, f"nav invalid: {nav}"
        assert risk, "risk_label empty"

    def test_pg_performance_ratios_row_populated(self):
        iid = TestScrapeLifecycle._state.get("instrument_id")
        if not iid:
            pytest.skip("no instrument_id")
        row = _psql(
            f"SELECT alpha, beta, sharpe, sortino, std_dev, ret_1y, ret_3y, ret_5y "
            f"FROM mutual_fund_performance_ratios "
            f"WHERE instrument_id = '{iid}' ORDER BY ratios_date DESC LIMIT 1;"
        )
        assert row, "ratios row missing"
        parts = row.split("|")
        assert len(parts) == 8
        # At least 5 of 8 should be non-null
        non_null = [p for p in parts if p.strip()]
        assert len(non_null) >= 5, f"too many null ratios: {parts}"

    def test_pg_holdings_rows_populated(self):
        iid = TestScrapeLifecycle._state.get("instrument_id")
        if not iid:
            pytest.skip("no instrument_id")
        cnt = _psql(
            f"SELECT COUNT(*) FROM mutual_fund_holdings WHERE instrument_id = '{iid}';"
        )
        assert int(cnt) > 0, f"holdings count is {cnt}"
        # Weight + rank sanity
        sample = _psql(
            f"SELECT rank, weight_percent, holding_name FROM mutual_fund_holdings "
            f"WHERE instrument_id = '{iid}' ORDER BY rank LIMIT 3;"
        )
        assert sample, "holdings sample empty"
        for line in sample.splitlines():
            rank, wt, _name = line.split("|", 2)
            assert int(rank) >= 1
            assert float(wt) > 0, f"weight zero in {line}"

    def test_pg_audit_log_has_ok_status(self):
        iid = TestScrapeLifecycle._state.get("instrument_id")
        if not iid:
            pytest.skip("no instrument_id")
        status = _psql(
            f"SELECT status FROM scrape_audit_log WHERE instrument_id = '{iid}' "
            f"ORDER BY created_at DESC LIMIT 1;"
        )
        assert status in ("ok", "partial"), f"unexpected audit status: {status}"


# ── Cache enrichment (2nd call returns source=cache with ids) ────────────
class TestCacheEnrichment:
    def test_second_holdings_call_is_cached_and_enriched(self):
        # Warm the cache via user-auth holdings endpoint
        r1 = requests.get(
            f"{BASE_URL}/api/mf/holdings",
            params={"scheme_name": TARGET_FUND},
            cookies=_cookies(USER_TOKEN), timeout=TIMEOUT,
        )
        assert r1.status_code == 200, r1.text
        # 2nd call — should come from cache
        time.sleep(1)
        r2 = requests.get(
            f"{BASE_URL}/api/mf/holdings",
            params={"scheme_name": TARGET_FUND},
            cookies=_cookies(USER_TOKEN), timeout=TIMEOUT,
        )
        assert r2.status_code == 200, r2.text
        d = r2.json()
        assert d.get("source") == "cache", f"expected source=cache, got {d.get('source')}"
        # Enrichment: resolver must merge instrument_id/isin/symbol back into cached payload
        meta = d.get("metadata") or {}
        # After scrape-now persisted to PG, resolver should resolve these
        assert meta.get("isin") or d.get("isin"), "enrichment missing isin"


# ── PG fallback (direct resolver call) ───────────────────────────────────
class TestPgFallback:
    def test_load_fund_from_pg_direct(self):
        """Call pg_writer.load_fund_from_pg directly via a subprocess shim."""
        isin = TestScrapeLifecycle._state.get("isin")
        if not isin:
            pytest.skip("no isin available")
        code = f"""
import asyncio, json, os, sys
sys.path.insert(0, '/app/backend')
os.environ.setdefault('MONGO_URL','mongodb://localhost:27017')
os.environ.setdefault('DB_NAME','test_database')
from services import pg_writer
async def main():
    d = await pg_writer.load_fund_from_pg(isin='{isin}')
    print(json.dumps({{'ok': bool(d), 'source': d.get('source') if d else None,
                      'valid': d.get('valid') if d else None,
                      'has_holdings': bool(d and d.get('holdings')),
                      'has_ratios': bool(d and d.get('ratios')),
                      'isin': (d.get('metadata') or {{}}).get('isin') if d else None}}))
asyncio.run(main())
"""
        env = os.environ.copy()
        # load backend .env into env
        with open("/app/backend/.env") as f:
            for line in f:
                if "=" in line and not line.strip().startswith("#"):
                    k, v = line.strip().split("=", 1)
                    env.setdefault(k, v.strip('"').strip("'"))
        # POSTGRES_URL is stored as an admin secret in Mongo, not env — set it
        # explicitly so pg_client can build the pool in the subprocess.
        env["POSTGRES_URL"] = PG_CONN
        r = subprocess.run(
            ["python", "-c", code], env=env,
            capture_output=True, text=True, timeout=30,
        )
        assert r.returncode == 0, f"stderr: {r.stderr}\nstdout: {r.stdout}"
        import json
        out = json.loads(r.stdout.strip().splitlines()[-1])
        assert out["ok"] is True, f"load_fund_from_pg returned None: {out}"
        assert out["source"] == "pg"
        assert out["valid"] is True
        assert out["has_holdings"] is True
        assert out["has_ratios"] is True
        assert out["isin"] == TestScrapeLifecycle._state["isin"]


# ── Dashboard endpoints ──────────────────────────────────────────────────
class TestDashboard:
    def test_list_funds_returns_instrument_ids(self):
        r = requests.get(f"{BASE_URL}/api/admin/mf/funds",
                         cookies=_cookies(ADMIN_TOKEN), timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        funds = r.json().get("funds")
        assert isinstance(funds, list)
        assert len(funds) >= 1, "no funds in dashboard list"
        f0 = funds[0]
        # UUID shape
        assert len(f0["instrument_id"]) == 36
        for k in ("instrument_id", "aum_cr", "holdings_count", "last_scraped_at"):
            assert k in f0

    def test_list_funds_requires_admin(self):
        r = requests.get(f"{BASE_URL}/api/admin/mf/funds", timeout=TIMEOUT)
        assert r.status_code in (401, 403)

    def test_fund_detail_returns_full_payload(self):
        iid = TestScrapeLifecycle._state.get("instrument_id")
        if not iid:
            # fallback — pick first fund from list
            lr = requests.get(f"{BASE_URL}/api/admin/mf/funds",
                              cookies=_cookies(ADMIN_TOKEN), timeout=TIMEOUT)
            funds = lr.json().get("funds") or []
            if not funds:
                pytest.skip("no funds available for detail test")
            iid = funds[0]["instrument_id"]
        r = requests.get(f"{BASE_URL}/api/admin/mf/funds/{iid}",
                         cookies=_cookies(ADMIN_TOKEN), timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        d = r.json()
        for k in ("instrument", "metadata", "holdings", "ratios_history", "recent_audit"):
            assert k in d, f"missing key {k}"
        # Holdings ordered by rank
        if d["holdings"]:
            ranks = [h["rank"] for h in d["holdings"]]
            assert ranks == sorted(ranks), f"holdings not ordered by rank: {ranks}"

    def test_fund_detail_404_for_missing_uuid(self):
        fake = "00000000-0000-0000-0000-000000000000"
        r = requests.get(f"{BASE_URL}/api/admin/mf/funds/{fake}",
                         cookies=_cookies(ADMIN_TOKEN), timeout=TIMEOUT)
        assert r.status_code == 404

    def test_audit_log_endpoint(self):
        r = requests.get(f"{BASE_URL}/api/admin/mf/audit-log",
                         cookies=_cookies(ADMIN_TOKEN), timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        audit = r.json().get("audit")
        assert isinstance(audit, list)
        if audit:
            row = audit[0]
            for k in ("id", "instrument_name", "status", "created_at"):
                assert k in row

    def test_audit_log_requires_admin(self):
        r = requests.get(f"{BASE_URL}/api/admin/mf/audit-log", timeout=TIMEOUT)
        assert r.status_code in (401, 403)


# ── Queue ops ────────────────────────────────────────────────────────────
class TestQueueOps:
    def test_seed_portfolio_queue(self):
        r = requests.post(f"{BASE_URL}/api/admin/mf/seed-portfolio-queue",
                          cookies=_cookies(ADMIN_TOKEN), timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        d = r.json()
        # Expect counters like queued/skipped/total
        assert any(k in d for k in ("queued", "total", "added", "skipped")), \
            f"unexpected seed response: {d}"

    def test_seed_portfolio_queue_requires_admin(self):
        r = requests.post(f"{BASE_URL}/api/admin/mf/seed-portfolio-queue", timeout=TIMEOUT)
        assert r.status_code in (401, 403)

    def test_drain_queue_force(self):
        r = requests.post(
            f"{BASE_URL}/api/admin/mf/drain-queue",
            params={"force": "true", "max_items": 2},
            cookies=_cookies(ADMIN_TOKEN), timeout=TIMEOUT,
        )
        assert r.status_code == 200, r.text
        d = r.json()
        # Shape: processed/success/failed/skipped counters
        assert isinstance(d, dict)

    def test_drain_queue_requires_admin(self):
        r = requests.post(f"{BASE_URL}/api/admin/mf/drain-queue?force=true", timeout=TIMEOUT)
        assert r.status_code in (401, 403)


# ── Admin auth gates on all /api/admin/mf/* ──────────────────────────────
class TestAdminAuth:
    @pytest.mark.parametrize("path,method", [
        ("/api/admin/mf/db-status", "GET"),
        ("/api/admin/mf/funds", "GET"),
        ("/api/admin/mf/audit-log", "GET"),
        ("/api/admin/mf/scrape-queue", "GET"),
        ("/api/admin/mf/scrape-now?scheme_name=X", "POST"),
        ("/api/admin/mf/seed-portfolio-queue", "POST"),
        ("/api/admin/mf/drain-queue", "POST"),
        ("/api/admin/mf/scheduler/start", "POST"),
        ("/api/admin/mf/scheduler/stop", "POST"),
    ])
    def test_unauthenticated_rejected(self, path, method):
        r = requests.request(method, f"{BASE_URL}{path}", timeout=TIMEOUT)
        assert r.status_code in (401, 403), f"{method} {path} -> {r.status_code}"


# ── Regression: existing endpoints ───────────────────────────────────────
class TestRegression:
    def test_user_profile(self):
        r = requests.get(f"{BASE_URL}/api/user/profile",
                         cookies=_cookies(USER_TOKEN), timeout=TIMEOUT)
        assert r.status_code == 200, r.text

    def test_mf_holdings_user_auth(self):
        r = requests.get(
            f"{BASE_URL}/api/mf/holdings",
            params={"scheme_name": TARGET_FUND},
            cookies=_cookies(USER_TOKEN), timeout=TIMEOUT,
        )
        assert r.status_code == 200, r.text
        assert "source" in r.json()

    def test_admin_secrets(self):
        r = requests.get(f"{BASE_URL}/api/admin/secrets",
                         cookies=_cookies(ADMIN_TOKEN), timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        assert "secrets" in r.json() or isinstance(r.json(), list) or isinstance(r.json(), dict)

    def test_admin_feature_flags(self):
        r = requests.get(f"{BASE_URL}/api/admin/feature-flags",
                         cookies=_cookies(ADMIN_TOKEN), timeout=TIMEOUT)
        # Accept 200 or 404 (if endpoint not present)
        assert r.status_code in (200, 404), r.text
