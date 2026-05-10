"""Backend tests for NIDP iteration 58 — derived feeds 'never ran' fix.

Validates that the 8 derived feeds now write to nidp.job_log via the new
run_with_job_log() wrapper, so the /jobs endpoint surfaces real statuses
(OK/FAILED/PARTIAL/SKIPPED) instead of null/'never'.

Also re-runs all iter56 regression assertions inline (32 jobs, drift empty,
grafana proxy, archive listing/download, auth) so this file is a single
self-contained regression suite for the next iteration.
"""
import os
import datetime as dt
import pytest
import requests


def _load_base_url():
    url = os.environ.get('REACT_APP_BACKEND_URL')
    if url:
        return url.rstrip('/')
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

DERIVED_FEEDS = [
    "event_calendar",
    "event_day_poller",
    "d1_prep",
    "intelligence",
    "price_adjuster",
    "announcement_classifier",
    "document_parser",
    "quality_gate",
]

VALID_STATUSES = {"OK", "FAILED", "PARTIAL", "SKIPPED"}


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    s.cookies.update(COOKIES)
    return s


@pytest.fixture(scope="module")
def jobs_payload(client):
    r = client.get(f"{BASE_URL}/api/admin/nidp/jobs", timeout=30)
    assert r.status_code == 200, r.text[:500]
    return r.json()


# ---------- iter58: derived feed status fix ----------
class TestDerivedFeedsHaveRealStatus:
    """Core iter58 assertion: 8 derived feeds must no longer show 'never'."""

    @pytest.mark.parametrize("feed", DERIVED_FEEDS)
    def test_derived_feed_has_real_status(self, jobs_payload, feed):
        jobs = jobs_payload["jobs"]
        row = next((j for j in jobs if j.get("ingester") == feed), None)
        assert row is not None, f"derived feed {feed!r} not in /jobs response"
        status = row.get("last_run_status")
        assert status is not None, (
            f"{feed} still has last_run_status=None — the JobRun wrapper "
            f"isn't writing to nidp.job_log"
        )
        assert status in VALID_STATUSES, (
            f"{feed} last_run_status={status!r} not in {VALID_STATUSES}"
        )
        last_run_at = row.get("last_run_at")
        assert last_run_at, f"{feed} has no last_run_at timestamp"

    def test_intelligence_correctly_captures_failure(self, jobs_payload):
        """The intelligence feed has a known SQL bug ('column f.id does
        not exist'). Test asserts the wrapper correctly captures it as
        FAILED with a non-empty error message."""
        row = next(
            j for j in jobs_payload["jobs"] if j.get("ingester") == "intelligence"
        )
        assert row["last_run_status"] == "FAILED"
        assert row.get("consecutive_failures") and row["consecutive_failures"] >= 1
        err = (row.get("last_error_message") or "").lower()
        assert "f.id" in err or "undefinedcolumn" in err, (
            f"expected intelligence failure to mention SQL bug; got {err!r}"
        )


# ---------- iter58: per-feed runs/calendar endpoints ----------
class TestEventCalendarRuns:
    def test_event_calendar_runs_has_ok_entry(self, client):
        r = client.get(
            f"{BASE_URL}/api/admin/nidp/jobs/event_calendar/runs",
            params={"limit": 10},
            timeout=30,
        )
        assert r.status_code == 200, r.text[:500]
        body = r.json()
        runs = body.get("runs", [])
        assert isinstance(runs, list) and len(runs) >= 1, (
            f"expected runs[] non-empty for event_calendar, got {body}"
        )
        statuses = [run.get("status") for run in runs]
        assert "OK" in statuses, (
            f"expected at least one OK run for event_calendar, got {statuses}"
        )

    def test_event_calendar_calendar_7days(self, client):
        r = client.get(
            f"{BASE_URL}/api/admin/nidp/jobs/event_calendar/calendar",
            params={"days": 7},
            timeout=30,
        )
        assert r.status_code == 200, r.text[:500]
        body = r.json()
        cal = body.get("calendar", body if isinstance(body, list) else [])
        # Some endpoints return a flat list, others wrap it.
        if isinstance(body, dict) and isinstance(body.get("calendar"), list):
            cal = body["calendar"]
        elif isinstance(body, list):
            cal = body
        assert len(cal) == 7, f"expected 7 day cells, got {len(cal)}: {body}"


class TestIntelligenceRuns:
    def test_intelligence_runs_has_failed_entry(self, client):
        r = client.get(
            f"{BASE_URL}/api/admin/nidp/jobs/intelligence/runs",
            params={"limit": 10},
            timeout=30,
        )
        assert r.status_code == 200, r.text[:500]
        body = r.json()
        runs = body.get("runs", [])
        assert len(runs) >= 1, f"no runs returned: {body}"
        statuses = [run.get("status") for run in runs]
        assert "FAILED" in statuses, (
            f"expected FAILED run for intelligence (SQL bug), got {statuses}"
        )


# ---------- iter56 regression: /jobs schema ----------
class TestJobsSchemaRegression:
    def test_jobs_returns_32(self, jobs_payload):
        assert len(jobs_payload["jobs"]) == 32

    def test_last_trading_day_weekday(self, jobs_payload):
        ltd = jobs_payload.get("last_trading_day")
        assert isinstance(ltd, str) and len(ltd) == 10
        d = dt.date.fromisoformat(ltd)
        assert d.weekday() < 5

    def test_grafana_embed_url_present(self, jobs_payload):
        gurl = jobs_payload.get("grafana_embed_url")
        if not gurl:
            for j in jobs_payload["jobs"]:
                if j.get("grafana_embed_url"):
                    gurl = j["grafana_embed_url"]
                    break
        assert gurl, "grafana_embed_url missing"
        assert gurl.startswith("/api/admin/nidp/grafana/")

    def test_drift_empty(self, jobs_payload):
        drift = jobs_payload.get("drift", {})
        assert drift.get("missing_from_db", []) == []
        assert drift.get("unregistered_in_canonical", []) == []


# ---------- iter56 regression: execute / grafana / archive / auth ----------
class TestRegressionExecute:
    def test_execute_target_date(self, client):
        r = client.post(
            f"{BASE_URL}/api/admin/nidp/jobs/bhavcopy/execute",
            params={"target_date": TARGET_DATE},
            timeout=60,
        )
        assert r.status_code == 200
        data = r.json()
        assert data.get("target_date") == TARGET_DATE
        assert data.get("via") == "vm"
        assert data.get("status") == "spawned"


class TestRegressionGrafana:
    def test_grafana_health(self, client):
        r = client.get(
            f"{BASE_URL}/api/admin/nidp/grafana/api/health", timeout=30
        )
        assert r.status_code == 200
        data = r.json()
        assert data.get("database") == "ok"

    def test_grafana_dashboard(self, client):
        r = client.get(
            f"{BASE_URL}/api/admin/nidp/grafana/api/dashboards/uid/nidp-job-health",
            timeout=30,
        )
        assert r.status_code == 200
        assert "dashboard" in r.json()


class TestRegressionArchive:
    def test_bhavcopy_listing(self, client):
        r = client.get(
            f"{BASE_URL}/api/admin/nidp/archive/bhavcopy", timeout=30
        )
        assert r.status_code == 200
        dates = r.json().get("dates", [])
        entry = next(
            (d for d in dates if d.get("target_date") == TARGET_DATE), None
        )
        assert entry is not None
        names = [f.get("filename") for f in entry.get("files", [])]
        assert "BhavCopy_NSE_CM_0_0_0_20260508_F_0000.csv.zip" in names

    def test_bhavcopy_download(self, client):
        url = (
            f"{BASE_URL}/api/admin/nidp/archive/bhavcopy/{TARGET_DATE}/"
            "BhavCopy_NSE_CM_0_0_0_20260508_F_0000.csv.zip"
        )
        r = client.get(url, timeout=60)
        assert r.status_code == 200
        assert r.content[:2] == b"PK"
        assert 150_000 < len(r.content) < 250_000

    def test_path_traversal_blocked(self, client):
        url = (
            f"{BASE_URL}/api/admin/nidp/archive/bhavcopy/{TARGET_DATE}/"
            "..%2F..%2Fetc%2Fpasswd"
        )
        r = client.get(url, timeout=30, allow_redirects=False)
        assert r.status_code == 400


class TestRegressionAuth:
    def test_jobs_unauth(self):
        assert (
            requests.get(f"{BASE_URL}/api/admin/nidp/jobs", timeout=30).status_code
            == 401
        )

    def test_grafana_unauth(self):
        assert (
            requests.get(
                f"{BASE_URL}/api/admin/nidp/grafana/api/health", timeout=30
            ).status_code
            == 401
        )
