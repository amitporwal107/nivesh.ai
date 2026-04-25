"""Unit tests for /api/data-health/summary classification logic."""
from datetime import datetime, timedelta, timezone

from routes.data_health import (
    _classify_job,
    _hours_since,
)


def _iso(hrs_ago):
    return (datetime.now(timezone.utc) - timedelta(hours=hrs_ago)).isoformat()


def test_hours_since_handles_iso_string():
    h = _hours_since(_iso(5))
    assert h is not None and 4.9 < h < 5.1


def test_hours_since_handles_none():
    assert _hours_since(None) is None


def test_classify_no_history_emits_warn():
    issues = _classify_job("nav_cron", None)
    assert len(issues) == 1
    assert issues[0]["severity"] == "warn"
    assert "no run history" in issues[0]["message"].lower()


def test_classify_failed_status_emits_error():
    issues = _classify_job("nav_cron", {
        "status": "failed", "started_at": _iso(2), "error_msg": "timeout",
    })
    assert issues[0]["severity"] == "error"
    assert "timeout" in issues[0]["message"]


def test_classify_stale_critical_job_emits_error():
    issues = _classify_job("analytics_sweep", {
        "status": "ok", "started_at": _iso(45),  # > 36h threshold
    })
    assert issues[0]["severity"] == "error"
    assert "45h" in issues[0]["message"]


def test_classify_stale_non_critical_job_emits_warn():
    """nifty100_refresh stale → only warn, not error."""
    issues = _classify_job("nifty100_refresh", {
        "status": "ok", "started_at": _iso(48),
    })
    assert issues[0]["severity"] == "warn"


def test_classify_fresh_run_emits_no_issue():
    issues = _classify_job("nav_cron", {
        "status": "ok", "started_at": _iso(2),
    })
    assert issues == []
