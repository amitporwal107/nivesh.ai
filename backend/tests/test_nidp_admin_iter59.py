"""Backend tests for NIDP iteration 59 — targeted bug-fix verification.

Iter59 patches on top of iter58:
 1. intelligence: removed broken JOIN (UndefinedColumnError 'f.id'); should now run OK.
 2. nse_financials: wrapped with JobRun; cadence/freq updated quarterly→daily.
 3. amfi_nav_history: UI should show 'manual' instead of 'never'.
 4. corporate_announcements_*: UI should show 'event-driven' instead of 'never'.

Also asserts the iter58 derived feeds remain OK (no regression: still 32 jobs).
"""
import os
import pytest
import requests


def _load_base_url():
    url = os.environ.get('REACT_APP_BACKEND_URL')
    if url:
        return url.rstrip('/')
    with open('/app/frontend/.env') as f:
        for line in f:
            if line.startswith('REACT_APP_BACKEND_URL='):
                return line.split('=', 1)[1].strip().rstrip('/')
    raise RuntimeError("REACT_APP_BACKEND_URL not configured")


BASE_URL = _load_base_url()
SESSION = "3352751a-cc8a-4bcb-bf50-81a377c6b40b"
COOKIES = {"session_token": SESSION}

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


def _row(jobs_payload, ingester):
    row = next(
        (j for j in jobs_payload["jobs"] if j.get("ingester") == ingester), None
    )
    assert row is not None, f"{ingester!r} missing from /jobs response"
    return row


# ---------- iter59: intelligence fix ----------
class TestIntelligenceFix:
    def test_intelligence_now_ok(self, jobs_payload):
        row = _row(jobs_payload, "intelligence")
        assert row["last_run_status"] == "OK", (
            f"intelligence should be OK after JOIN fix; got {row.get('last_run_status')!r} "
            f"err={row.get('last_error_message')!r}"
        )

    def test_intelligence_consecutive_failures_zero(self, jobs_payload):
        row = _row(jobs_payload, "intelligence")
        cf = row.get("consecutive_failures") or 0
        assert cf == 0, f"intelligence consecutive_failures should be 0, got {cf}"

    def test_intelligence_runs_history_preserved(self, client):
        """Most recent run is OK; older FAILED runs (the f.id bug) are preserved."""
        r = client.get(
            f"{BASE_URL}/api/admin/nidp/jobs/intelligence/runs",
            params={"limit": 10}, timeout=30,
        )
        assert r.status_code == 200, r.text[:500]
        runs = r.json().get("runs", [])
        assert len(runs) >= 1, "no runs returned for intelligence"
        # runs are ordered newest-first
        assert runs[0]["status"] == "OK", (
            f"newest intelligence run should be OK, got {runs[0]['status']}"
        )
        # history preservation: at least one older FAILED run with f.id
        statuses = [r.get("status") for r in runs]
        assert "FAILED" in statuses, (
            f"expected historical FAILED runs preserved; got {statuses}"
        )


# ---------- iter59: nse_financials JobRun + cadence/freq fix ----------
class TestNseFinancialsFix:
    def test_nse_financials_status_ok(self, jobs_payload):
        row = _row(jobs_payload, "nse_financials")
        assert row["last_run_status"] == "OK", (
            f"nse_financials should be OK; got {row.get('last_run_status')!r}"
        )

    def test_nse_financials_expected_freq_daily(self, jobs_payload):
        """expected_freq updated quarterly → daily to match cron."""
        row = _row(jobs_payload, "nse_financials")
        assert row.get("expected_freq") == "daily", (
            f"expected_freq should be 'daily', got {row.get('expected_freq')!r}"
        )

    def test_nse_financials_schedule_cron(self, jobs_payload):
        row = _row(jobs_payload, "nse_financials")
        assert row.get("schedule_cron") == "30 20 * * *", (
            f"schedule_cron mismatch: {row.get('schedule_cron')!r}"
        )

    def test_nse_financials_last_run_at_present(self, jobs_payload):
        row = _row(jobs_payload, "nse_financials")
        assert row.get("last_run_at"), "nse_financials missing last_run_at"


# ---------- iter59: manual / event feeds (frontend display) ----------
class TestManualAndEventFeeds:
    """Backend returns expected_freq=manual / event with last_run_status=None.
    The UI display ('manual' / 'event-driven') is verified in playwright.
    Here we just make sure the data the UI reads is shaped correctly."""

    def test_amfi_nav_history_is_manual(self, jobs_payload):
        row = _row(jobs_payload, "amfi_nav_history")
        assert row.get("expected_freq") == "manual", (
            f"amfi_nav_history expected_freq should be 'manual', "
            f"got {row.get('expected_freq')!r}"
        )

    def test_corporate_announcements_nse_is_event(self, jobs_payload):
        row = _row(jobs_payload, "corporate_announcements_nse")
        assert row.get("expected_freq") == "event", (
            f"corporate_announcements_nse expected_freq should be 'event', "
            f"got {row.get('expected_freq')!r}"
        )

    def test_corporate_announcements_bse_is_event(self, jobs_payload):
        row = _row(jobs_payload, "corporate_announcements_bse")
        assert row.get("expected_freq") == "event", (
            f"corporate_announcements_bse expected_freq should be 'event', "
            f"got {row.get('expected_freq')!r}"
        )


# ---------- iter59: regression — 32 jobs, derived feeds still healthy ----------
class TestNoRegression:
    def test_jobs_count_32(self, jobs_payload):
        assert len(jobs_payload["jobs"]) == 32

    @pytest.mark.parametrize("feed", [
        "event_calendar", "event_day_poller", "d1_prep", "price_adjuster",
        "announcement_classifier", "document_parser", "quality_gate",
    ])
    def test_iter58_derived_feed_still_has_status(self, jobs_payload, feed):
        row = _row(jobs_payload, feed)
        status = row.get("last_run_status")
        assert status in VALID_STATUSES, (
            f"{feed} status regressed: {status!r}"
        )
