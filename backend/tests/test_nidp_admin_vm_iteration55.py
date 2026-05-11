"""
Backend regression tests for /api/admin/nidp/* endpoints (iteration 55).
Verifies wiring to VM-based NIDP query_api at 34.47.191.39:8090.
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://nidp-backfill-ui.preview.emergentagent.com").rstrip("/")
ADMIN_SESSION = "3352751a-cc8a-4bcb-bf50-81a377c6b40b"  # aporwal107@gmail.com
EXPECTED_VM_URL = "http://34.47.191.39:8090"


@pytest.fixture(scope="module")
def admin_client():
    s = requests.Session()
    s.cookies.set("session_token", ADMIN_SESSION)
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def anon_client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


# ---------- Auth ----------
class TestAuth:
    @pytest.mark.parametrize("path", [
        "/api/admin/nidp/diag",
        "/api/admin/nidp/jobs",
        "/api/admin/nidp/catalog",
        "/api/admin/nidp/quality/summary",
    ])
    def test_requires_session(self, anon_client, path):
        r = anon_client.get(f"{BASE_URL}{path}", timeout=30)
        assert r.status_code == 401, f"{path} expected 401, got {r.status_code}"


# ---------- Diagnostics ----------
class TestDiag:
    def test_diag(self, admin_client):
        r = admin_client.get(f"{BASE_URL}/api/admin/nidp/diag", timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        nq = data.get("nidp_query_api") or {}
        env = data.get("env") or {}
        assert nq.get("reachable") is True, f"reachable not true: {nq}"
        assert nq.get("auth_ok") is True, f"auth_ok not true: {nq}"
        assert env.get("NIDP_QUERY_API_URL") == EXPECTED_VM_URL, f"unexpected URL: {env.get('NIDP_QUERY_API_URL')}"
        lat = (nq.get("health") or {}).get("db_latency_ms")
        assert isinstance(lat, (int, float)), f"db_latency_ms should be number: {lat}"
        assert 0 <= lat < 5000, f"db_latency_ms unreasonable: {lat}"


# ---------- Jobs ----------
class TestJobs:
    def test_jobs_list(self, admin_client):
        r = admin_client.get(f"{BASE_URL}/api/admin/nidp/jobs", timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        jobs = data.get("jobs", [])
        assert len(jobs) >= 30, f"expected >=30 jobs, got {len(jobs)}"
        names = {j.get("name") or j.get("ingester") or j.get("id") for j in jobs}
        for required in ["amfi_nav", "amfi_circulars", "mf_holdings", "event_calendar"]:
            assert required in names, f"missing required job '{required}' in {sorted(names)[:40]}"
        assert data.get("grafana_url"), f"grafana_url missing: keys={list(data.keys())}"
        # Real status — at least one OK or some FAILED variety
        statuses = {(j.get("status") or "").upper() for j in jobs}
        assert statuses, "no statuses present"

    def test_amfi_nav_runs(self, admin_client):
        r = admin_client.get(f"{BASE_URL}/api/admin/nidp/jobs/amfi_nav/runs?limit=5", timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        runs = data.get("runs", [])
        assert len(runs) > 0, "no runs returned for amfi_nav"
        assert any((r.get("status") or "").upper() == "OK" for r in runs), f"no OK runs: {runs}"
        assert any((r.get("rows_inserted") or 0) > 0 for r in runs), f"no rows_inserted >0: {runs}"

    def test_amfi_nav_logs(self, admin_client):
        r = admin_client.get(f"{BASE_URL}/api/admin/nidp/jobs/amfi_nav/logs?limit=10", timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("via") == "vm", f"expected via=vm, got {data.get('via')}"
        assert "/opt/nidp/logs/amfi_nav" in (data.get("log_path") or ""), f"unexpected log_path: {data.get('log_path')}"
        lines = data.get("lines") or []
        assert len(lines) > 0, "log lines empty"

    def test_amfi_nav_calendar(self, admin_client):
        r = admin_client.get(f"{BASE_URL}/api/admin/nidp/jobs/amfi_nav/calendar?days=7", timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        cal = data.get("calendar", [])
        assert len(cal) == 7, f"expected 7 calendar entries, got {len(cal)}"

    def test_execute_amfi_circulars(self, admin_client):
        r = admin_client.post(f"{BASE_URL}/api/admin/nidp/jobs/amfi_circulars/execute", timeout=30)
        assert r.status_code in (200, 202), r.text
        data = r.json()
        assert data.get("ok") is True, f"ok not true: {data}"
        assert data.get("via") == "vm", f"via not vm: {data}"
        assert data.get("status") == "spawned", f"status not spawned: {data}"


# ---------- Catalog ----------
class TestCatalog:
    def test_catalog(self, admin_client):
        r = admin_client.get(f"{BASE_URL}/api/admin/nidp/catalog", timeout=45)
        assert r.status_code == 200, r.text
        data = r.json()
        assert isinstance(data.get("tables"), list), f"tables missing: {list(data.keys())}"
        by_domain = data.get("by_domain") or {}
        assert len(by_domain) >= 8, f"expected >=8 domains, got {len(by_domain)}"
        assert isinstance(data.get("feeds"), list), "feeds missing"
        assert "validation" in data, "validation missing"


# ---------- Quality ----------
class TestQuality:
    def test_quality_summary(self, admin_client):
        r = admin_client.get(f"{BASE_URL}/api/admin/nidp/quality/summary", timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        for k in ("quality", "certified", "gate", "exceptions"):
            assert k in data, f"key {k} missing in summary"
            assert isinstance(data[k], list), f"{k} not list"
        assert all(v in (None, [], {}, "") for v in (data.get("errors") or {}).values()), f"errors should be falsy: {data.get('errors')}"

    def test_quality_consistency(self, admin_client):
        r = admin_client.get(f"{BASE_URL}/api/admin/nidp/quality/consistency", timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert isinstance(data.get("runs"), list), "runs missing"
        assert isinstance(data.get("findings"), list), "findings missing"
        assert all(v in (None, [], {}, "") for v in (data.get("errors") or {}).values()), f"errors should be falsy: {data.get('errors')}"

    def test_quality_exceptions(self, admin_client):
        r = admin_client.get(f"{BASE_URL}/api/admin/nidp/quality/exceptions", timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert isinstance(data.get("exceptions"), list), "exceptions missing"

    def test_quality_quarantine(self, admin_client):
        r = admin_client.get(f"{BASE_URL}/api/admin/nidp/quality/quarantine", timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert isinstance(data.get("quarantine"), list), "quarantine missing"
