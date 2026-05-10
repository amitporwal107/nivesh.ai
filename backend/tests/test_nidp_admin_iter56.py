"""Backend tests for NIDP Console iteration 56 fixes:
1. /jobs returns last_trading_day + grafana_embed_url, empty drift arrays, 32 jobs
2. /jobs/{ingester}/execute accepts target_date param
3. /grafana/* proxy works (mixed-content fix)
4. /archive/* listing & download endpoints
5. Auth + path traversal security
"""
import os
import pytest
import requests

def _load_base_url():
    url = os.environ.get('REACT_APP_BACKEND_URL')
    if url:
        return url.rstrip('/')
    # fall back to frontend/.env
    try:
        with open('/app/frontend/.env') as f:
            for line in f:
                if line.startswith('REACT_APP_BACKEND_URL='):
                    return line.split('=', 1)[1].strip().rstrip('/')
    except Exception:
        pass
    raise RuntimeError("REACT_APP_BACKEND_URL not configured")

BASE_URL = _load_base_url()
SESSION = "3352751a-cc8a-4bcb-bf50-81a377c6b40b"
COOKIES = {"session_token": SESSION}
TARGET_DATE = "2026-05-08"


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    s.cookies.update(COOKIES)
    return s


# ---------- /jobs ----------
class TestJobs:
    def test_jobs_returns_32_with_required_fields(self, client):
        r = client.get(f"{BASE_URL}/api/admin/nidp/jobs", timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        jobs = data.get("jobs", [])
        assert len(jobs) == 32, f"Expected 32 jobs, got {len(jobs)}"
        # last_trading_day at top level
        ltd = data.get("last_trading_day")
        assert isinstance(ltd, str) and len(ltd) == 10, f"bad last_trading_day {ltd!r}"
        import datetime as dt
        d = dt.date.fromisoformat(ltd)
        assert d.weekday() < 5, f"last_trading_day {ltd} is weekend"

    def test_jobs_grafana_embed_url(self, client):
        r = client.get(f"{BASE_URL}/api/admin/nidp/jobs", timeout=30)
        data = r.json()
        # check at top level or per-job
        gurl = data.get("grafana_embed_url")
        if gurl is None:
            # maybe per-job
            for j in data["jobs"]:
                if j.get("grafana_embed_url"):
                    gurl = j["grafana_embed_url"]
                    break
        assert gurl is not None, "no grafana_embed_url found in response"
        assert gurl.startswith("/api/admin/nidp/grafana/"), f"bad grafana url {gurl}"

    def test_jobs_drift_arrays_empty(self, client):
        r = client.get(f"{BASE_URL}/api/admin/nidp/jobs", timeout=30)
        data = r.json()
        drift = data.get("drift", {})
        assert drift.get("missing_from_db", []) == [], f"missing_from_db not empty: {drift.get('missing_from_db')}"
        assert drift.get("unregistered_in_canonical", []) == [], f"unregistered_in_canonical not empty: {drift.get('unregistered_in_canonical')}"


# ---------- execute with target_date ----------
class TestExecute:
    def test_execute_passes_target_date(self, client):
        r = client.post(
            f"{BASE_URL}/api/admin/nidp/jobs/bhavcopy/execute",
            params={"target_date": TARGET_DATE},
            timeout=60,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("target_date") == TARGET_DATE, f"target_date echo mismatch: {data}"
        assert data.get("via") == "vm", f"expected via=vm, got {data}"
        assert data.get("status") == "spawned", f"expected status=spawned, got {data}"


# ---------- Grafana proxy (CRITICAL mixed-content fix) ----------
class TestGrafanaProxy:
    def test_grafana_health(self, client):
        r = client.get(f"{BASE_URL}/api/admin/nidp/grafana/api/health", timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("database") == "ok", f"grafana health: {data}"
        assert "version" in data

    def test_grafana_dashboard(self, client):
        r = client.get(
            f"{BASE_URL}/api/admin/nidp/grafana/api/dashboards/uid/nidp-job-health",
            timeout=30,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert "dashboard" in data, f"no dashboard key: {list(data.keys())}"


# ---------- Archive listing ----------
class TestArchiveListing:
    def test_bhavcopy_listing(self, client):
        r = client.get(f"{BASE_URL}/api/admin/nidp/archive/bhavcopy", timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        dates = data.get("dates", [])
        target_entry = next((d for d in dates if d.get("target_date") == TARGET_DATE), None)
        assert target_entry is not None, f"no entry for {TARGET_DATE} in {dates}"
        files = target_entry.get("files", [])
        names = [f.get("filename") for f in files]
        assert "BhavCopy_NSE_CM_0_0_0_20260508_F_0000.csv.zip" in names, f"bhavcopy zip missing: {names}"

    def test_delivery_listing(self, client):
        r = client.get(f"{BASE_URL}/api/admin/nidp/archive/delivery", timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        dates = data.get("dates", [])
        target_entry = next((d for d in dates if d.get("target_date") == TARGET_DATE), None)
        assert target_entry is not None, f"no entry for {TARGET_DATE}: {dates}"
        names = [f.get("filename") for f in target_entry.get("files", [])]
        assert "sec_bhavdata_full_08052026.csv" in names, f"delivery csv missing: {names}"

    def test_amfi_nav_listing(self, client):
        r = client.get(f"{BASE_URL}/api/admin/nidp/archive/amfi_nav", timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        all_names = []
        for d in data.get("dates", []):
            for f in d.get("files", []):
                all_names.append(f.get("filename"))
        assert "NAVAll.txt" in all_names, f"NAVAll.txt missing: {all_names}"


# ---------- Archive download ----------
class TestArchiveDownload:
    def test_bhavcopy_download_real_zip(self, client):
        url = (
            f"{BASE_URL}/api/admin/nidp/archive/bhavcopy/{TARGET_DATE}/"
            "BhavCopy_NSE_CM_0_0_0_20260508_F_0000.csv.zip"
        )
        r = client.get(url, timeout=60)
        assert r.status_code == 200, r.text[:500]
        # ZIP magic bytes
        assert r.content[:2] == b"PK", f"not a zip, header={r.content[:8]!r}"
        size = len(r.content)
        assert 150_000 < size < 250_000, f"unexpected size {size}"

    def test_path_traversal_blocked(self, client):
        # Use URL-encoded traversal so client/proxy doesn't normalize it before
        # it reaches the route handler (raw "../.." gets collapsed by HTTP stacks).
        url = (
            f"{BASE_URL}/api/admin/nidp/archive/bhavcopy/{TARGET_DATE}/"
            "..%2F..%2Fetc%2Fpasswd"
        )
        r = client.get(url, timeout=30, allow_redirects=False)
        assert r.status_code == 400, f"expected 400 for traversal, got {r.status_code}: {r.text[:300]}"


# ---------- Auth ----------
class TestAuth:
    def test_jobs_unauth(self):
        r = requests.get(f"{BASE_URL}/api/admin/nidp/jobs", timeout=30)
        assert r.status_code == 401, f"got {r.status_code}"

    def test_grafana_unauth(self):
        r = requests.get(f"{BASE_URL}/api/admin/nidp/grafana/api/health", timeout=30)
        assert r.status_code == 401, f"got {r.status_code}"

    def test_archive_list_unauth(self):
        r = requests.get(f"{BASE_URL}/api/admin/nidp/archive/bhavcopy", timeout=30)
        assert r.status_code == 401, f"got {r.status_code}"

    def test_archive_download_unauth(self):
        r = requests.get(
            f"{BASE_URL}/api/admin/nidp/archive/bhavcopy/{TARGET_DATE}/"
            "BhavCopy_NSE_CM_0_0_0_20260508_F_0000.csv.zip",
            timeout=30,
        )
        assert r.status_code == 401, f"got {r.status_code}"
