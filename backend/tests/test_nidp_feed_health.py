"""Unit tests for the pure NIDP feed-health classifier that backs the
Console "Feeds Live" tab (helpers/nidp_feed_health.py).

Framework-free — imports the helper directly (no fastapi needed), so it
runs locally as well as in CI. Covers TC-3 / TC-4 of
test_reports/nidp_feeds_live_tracker.md.
"""
from datetime import date, datetime, timezone

from helpers.nidp_feed_health import classify_feed, feed_dt, DAILY_CADENCES

LTD = date(2026, 7, 14)  # a Tuesday — "last trading day" under test


def _feed(**over):
    base = {
        "ingester": "bhavcopy",
        "expected_freq": "daily",
        "last_run_at": "2026-07-14T13:00:00+00:00",
        "last_success_at": "2026-07-14T13:00:00+00:00",
        "last_run_status": "OK",
        "consecutive_failures": 0,
    }
    base.update(over)
    return base


# ── classify_feed ────────────────────────────────────────────────────

def test_healthy_daily_success_on_last_trading_day():
    assert classify_feed(_feed(), LTD) == "healthy"


def test_stale_daily_missed_last_trading_day():
    # last success was the previous day → hasn't succeeded on 2026-07-14
    f = _feed(last_success_at="2026-07-11T13:00:00+00:00")
    assert classify_feed(f, LTD) == "stale"


def test_stale_daily_never_succeeded():
    f = _feed(last_success_at=None, last_run_status="SKIPPED")
    assert classify_feed(f, LTD) == "stale"


def test_failing_on_consecutive_failures():
    f = _feed(consecutive_failures=3, last_run_status="OK")
    assert classify_feed(f, LTD) == "failing"


def test_failing_on_failed_status():
    f = _feed(consecutive_failures=0, last_run_status="FAILED")
    assert classify_feed(f, LTD) == "failing"


def test_never_run_when_no_last_run_at():
    f = _feed(last_run_at=None, last_success_at=None, last_run_status=None)
    assert classify_feed(f, LTD) == "never_run"


def test_running_takes_precedence():
    # Even a feed with consecutive failures shows RUNNING if a run is live.
    f = _feed(last_run_status="RUNNING", consecutive_failures=5)
    assert classify_feed(f, LTD) == "running"


def test_event_feed_never_stale():
    # An event/monthly feed with a very old success is NOT flagged stale.
    f = _feed(expected_freq="event", last_success_at="2026-01-01T00:00:00+00:00")
    assert classify_feed(f, LTD) == "healthy"


def test_monthly_feed_never_stale():
    f = _feed(expected_freq="monthly", last_success_at="2026-05-01T00:00:00+00:00")
    assert classify_feed(f, LTD) == "healthy"


def test_high_freq_treated_as_daily_for_staleness():
    assert "high-freq" in DAILY_CADENCES
    f = _feed(expected_freq="high-freq", last_success_at="2026-07-10T00:00:00+00:00")
    assert classify_feed(f, LTD) == "stale"


# ── feed_dt ──────────────────────────────────────────────────────────

def test_feed_dt_none_safe():
    assert feed_dt(None) is None
    assert feed_dt("") is None
    assert feed_dt("not-a-date") is None


def test_feed_dt_parses_tz_aware():
    dt = feed_dt("2026-07-14T13:00:00+00:00")
    assert dt == datetime(2026, 7, 14, 13, 0, tzinfo=timezone.utc)


def test_feed_dt_z_suffix_and_naive_assumed_utc():
    assert feed_dt("2026-07-14T13:00:00Z") == datetime(2026, 7, 14, 13, 0, tzinfo=timezone.utc)
    # Naive input is coerced to UTC so downstream subtraction never raises.
    assert feed_dt("2026-07-14T13:00:00").tzinfo == timezone.utc
