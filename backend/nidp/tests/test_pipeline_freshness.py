"""Trading-time freshness for the announcement -> RAG pipeline panel.

Two bugs are pinned here, and they pull in opposite directions — which is the
whole point. A fix for either one alone is easy and wrong:

  FALSE RED  — the ingesters run `*/10 9-23 * * 1-5`. Measured on a wall clock,
               Friday 23:50 -> Sunday 17:51 is 41.9h, so a 24h budget painted
               Ingest/Classify/Discover 'stale' every weekend. Observed on
               staging 2026-07-19 (Sunday): 3 stale, 3 lagging, 0 healthy.

  FALSE GREEN— corporate_announcements/writer.py does `ON CONFLICT ... DO UPDATE
               SET ingested_at = NOW()`, so max(ingested_at) advances on every
               re-seen row. A feed weeks behind on filings read 'healthy'.

Raising the threshold to 72h would clear the weekend red and make the false
green permanent. So the tests below assert BOTH: quiet on a closed market, loud
on a feed that has actually stopped.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from nidp.services.query_api.routers.pipeline import (
    IST,
    _filed_state,
    _state,
    _trading_days_behind,
    _trading_hours_between,
)

NO_HOLIDAYS = frozenset()


def ist(y, m, d, hh=0, mm=0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=IST)


# The exact moment the panel was screenshotted, and the timestamps behind it.
SUNDAY_NOW = ist(2026, 7, 19, 17, 51)
LAST_INGEST = ist(2026, 7, 17, 23, 50)   # Friday's final */10 slot
LAST_CLASSIFY = ist(2026, 7, 18, 0, 51)  # Saturday, drained Friday's queue
LAST_DISCOVER = ist(2026, 7, 18, 9, 51)  # Saturday, then starved
FRIDAY_CLOSE = date(2026, 7, 17)


# ── the weekend false alarm ──────────────────────────────────────────────

class TestWeekendIsQuiet:
    """The reported bug: a closed market must not read as a dead pipeline."""

    def test_ingest_current_through_friday_is_healthy_on_sunday(self):
        behind = _trading_days_behind(LAST_INGEST, FRIDAY_CLOSE, NO_HOLIDAYS)
        assert behind == 0
        assert _filed_state(behind) == "healthy"

    def test_classify_idle_all_weekend_is_not_stale(self):
        # 41.2h wall-clock -> 'stale' under the old rule.
        wall = (SUNDAY_NOW - LAST_CLASSIFY).total_seconds() / 3600
        assert wall > 24 and _state(wall, has_backlog=True) == "stale"
        # Zero trading hours have elapsed: Saturday 00:51 onward is all weekend.
        trading = _trading_hours_between(LAST_CLASSIFY, SUNDAY_NOW, NO_HOLIDAYS)
        assert trading == 0.0
        # backlog (blue, 16,389 pending) — a queue, not an outage.
        assert _state(trading, has_backlog=True) == "backlog"

    def test_discover_idle_all_weekend_is_healthy(self):
        trading = _trading_hours_between(LAST_DISCOVER, SUNDAY_NOW, NO_HOLIDAYS)
        assert trading == 0.0
        assert _state(trading, has_backlog=False) == "healthy"

    def test_friday_evening_tail_counts_but_stays_under_budget(self):
        # 23:50 -> midnight is real trading time and is counted; it is simply
        # nowhere near the 6h warn budget.
        trading = _trading_hours_between(LAST_INGEST, SUNDAY_NOW, NO_HOLIDAYS)
        assert 0.0 < trading < 0.5
        assert _state(trading, has_backlog=False) == "healthy"

    def test_no_stage_is_stale_at_the_screenshotted_moment(self):
        states = [
            _filed_state(_trading_days_behind(LAST_INGEST, FRIDAY_CLOSE, NO_HOLIDAYS)),
            _state(_trading_hours_between(LAST_CLASSIFY, SUNDAY_NOW, NO_HOLIDAYS),
                   has_backlog=True),
            _state(_trading_hours_between(LAST_DISCOVER, SUNDAY_NOW, NO_HOLIDAYS),
                   has_backlog=False),
        ]
        assert "stale" not in states
        assert states == ["healthy", "backlog", "healthy"]


# ── detection must survive the fix ───────────────────────────────────────

class TestWeekdayDeathStillDetected:
    """Raising the threshold would have passed the tests above and broken these."""

    def test_feed_dead_since_monday_is_stale_by_wednesday(self):
        trading = _trading_hours_between(
            ist(2026, 7, 20, 9, 0), ist(2026, 7, 22, 17, 0), NO_HOLIDAYS)
        assert trading > 24
        assert _state(trading, has_backlog=False) == "stale"

    def test_a_72h_threshold_would_have_missed_it(self):
        # Pins why the cheap fix was rejected: Mon 09:00 -> Wed 17:00 is 56h
        # wall-clock, so a 72h budget reads a two-day outage as fine.
        wall = (ist(2026, 7, 22, 17, 0) - ist(2026, 7, 20, 9, 0)).total_seconds() / 3600
        assert wall < 72

    def test_one_missed_trading_session_warns(self):
        # Tuesday close reached with nothing filed since Monday.
        behind = _trading_days_behind(
            ist(2026, 7, 20, 15, 0), date(2026, 7, 21), NO_HOLIDAYS)
        assert behind == 1
        assert _filed_state(behind) == "lagging"

    def test_two_missed_trading_sessions_is_stale(self):
        behind = _trading_days_behind(
            ist(2026, 7, 20, 15, 0), date(2026, 7, 22), NO_HOLIDAYS)
        assert behind == 2
        assert _filed_state(behind) == "stale"

    def test_a_long_dead_feed_is_stale_not_healthy(self):
        # The false-green case: ingested_at is fresh (cron re-sees rows) but
        # filed_at has not moved in ~51 days. Must not read healthy.
        behind = _trading_days_behind(
            ist(2026, 5, 26, 12, 0), date(2026, 7, 17), NO_HOLIDAYS)
        assert behind > 30
        assert _filed_state(behind) == "stale"


# ── calendar correctness ─────────────────────────────────────────────────

class TestCalendar:
    def test_holiday_hours_are_not_counted(self):
        holiday = date(2026, 7, 21)  # a Tuesday, declared a holiday
        span = (ist(2026, 7, 20, 12, 0), ist(2026, 7, 22, 12, 0))
        assert _trading_hours_between(*span, NO_HOLIDAYS) == 48.0
        assert _trading_hours_between(*span, frozenset({holiday})) == 24.0

    def test_holiday_is_skipped_when_counting_days_behind(self):
        holiday = date(2026, 7, 21)
        args = (ist(2026, 7, 20, 15, 0), date(2026, 7, 22))
        assert _trading_days_behind(*args, NO_HOLIDAYS) == 2
        assert _trading_days_behind(*args, frozenset({holiday})) == 1

    def test_monday_morning_before_first_filing_is_healthy(self):
        # 09:05 Monday: last close is still Friday (18:30 cutoff), and Friday's
        # filings are in. Nothing is wrong, so nothing should be amber.
        behind = _trading_days_behind(LAST_INGEST, FRIDAY_CLOSE, NO_HOLIDAYS)
        assert _filed_state(behind) == "healthy"

    def test_filed_ahead_of_last_close_clamps_to_zero(self):
        # Intraday: today's filings exist but today has not closed yet.
        behind = _trading_days_behind(
            ist(2026, 7, 20, 14, 0), date(2026, 7, 17), NO_HOLIDAYS)
        assert behind == 0

    def test_naive_timestamps_are_treated_as_utc(self):
        naive = datetime(2026, 7, 17, 18, 20)  # == 23:50 IST
        assert _trading_days_behind(naive, FRIDAY_CLOSE, NO_HOLIDAYS) == 0

    def test_absent_timestamp_is_never_not_stale(self):
        assert _trading_days_behind(None, FRIDAY_CLOSE, NO_HOLIDAYS) is None
        assert _trading_hours_between(None, SUNDAY_NOW, NO_HOLIDAYS) is None
        assert _filed_state(None) == "never"
        assert _state(None, has_backlog=False) == "never"

    def test_absurd_timestamp_terminates(self):
        # A garbage/epoch timestamp must not walk the calendar forever.
        assert _trading_days_behind(
            ist(1970, 1, 1), FRIDAY_CLOSE, NO_HOLIDAYS) == 400
        assert _trading_hours_between(
            ist(1970, 1, 1), SUNDAY_NOW, NO_HOLIDAYS) > 24

    def test_clock_skew_does_not_go_negative(self):
        future = SUNDAY_NOW + timedelta(hours=2)
        assert _trading_hours_between(future, SUNDAY_NOW, NO_HOLIDAYS) == 0.0

    def test_utc_timestamps_bucket_into_the_right_ist_day(self):
        # 19:00 UTC Friday is 00:30 IST Saturday — a weekend hour that must not
        # be counted. Off-by-one here would resurrect the false alarm.
        assert _trading_hours_between(
            datetime(2026, 7, 17, 19, 0, tzinfo=timezone.utc),
            datetime(2026, 7, 17, 20, 0, tzinfo=timezone.utc),
            NO_HOLIDAYS) == 0.0
