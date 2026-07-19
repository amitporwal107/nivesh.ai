"""End-to-end shape test for /pipeline/stages against a stubbed connection.

pipeline_stages() wraps its whole body in `except Exception` so the panel
degrades instead of 500ing. That is right for production and dangerous for
tests: a NameError in the ingest block would be swallowed into db_error and a
helper-level unit test would still pass. So every assertion here starts with
`db_error is None` — the stub exists to make that assertion meaningful.

Row data is the real staging state observed 2026-07-19 (Sunday), the moment the
panel showed 3 stale / 3 lagging / 0 healthy.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone

import pytest

from nidp.services.query_api.routers import pipeline as P

IST = P.IST
LAST_CLOSE = date(2026, 7, 17)          # Friday

# Anchored relative to now so the test does not rot: the shape that matters is
# "last write was Friday evening / Saturday", not the literal 2026 dates.
NOW = datetime.now(timezone.utc)


def _last_friday_2350() -> datetime:
    """Most recent Friday 23:50 IST at or before now."""
    now_ist = NOW.astimezone(IST)
    d = now_ist.date()
    while d.weekday() != 4:             # 4 = Friday
        d -= timedelta(days=1)
    ts = datetime.combine(d, datetime.min.time(), tzinfo=IST).replace(hour=23, minute=50)
    return ts if ts <= now_ist else ts - timedelta(days=7)


FRIDAY_LATE = _last_friday_2350()
SATURDAY_EARLY = FRIDAY_LATE + timedelta(hours=1)      # Sat 00:50 IST
SATURDAY_MORNING = FRIDAY_LATE + timedelta(hours=10)   # Sat 09:50 IST


class FakeConn:
    """Dispatches on SQL content; unknown queries fail loudly rather than
    returning an empty row that would silently read as 'never'."""

    async def fetchval(self, sql, *a):
        assert "compute_last_trading_day_ist" in sql, sql
        return _friday_before(FRIDAY_LATE)

    async def fetch(self, sql, *a):
        if "nse_holidays" in sql:
            return []
        if "GROUP BY source" in sql:
            return [
                {"source": "BSE_ANN", "total": 95998,
                 "latest_filed": FRIDAY_LATE, "latest_ingest": FRIDAY_LATE},
                {"source": "NSE_ANN", "total": 78298,
                 "latest_filed": FRIDAY_LATE, "latest_ingest": FRIDAY_LATE},
            ]
        raise AssertionError(f"unstubbed fetch: {sql[:80]}")

    async def fetchrow(self, sql, *a):
        if "event_category IS NOT NULL" in sql:
            return {"total": 174296, "classified": 9229,
                    "pending_reachable": 16389, "unreachable": 148678,
                    "latest": SATURDAY_EARLY}
        # Must precede the parse_status branch: the chunk-existence query also
        # filters on parse_status, so ordering by specificity is load-bearing.
        if "LATERAL" in sql:
            return {"chunked": 147018, "missing": 0}
        if "parse_status" in sql:
            return {"total": 172013, "pending": 18381, "parsed": 147018,
                    "failed": 2632, "skipped": 3109, "exhausted": 873,
                    "pending_in_window": 2228, "pending_out_of_scope": 16153,
                    "latest_discovered": SATURDAY_MORNING,
                    "latest_parsed": NOW - timedelta(hours=7.5)}
        if "count(embedding)" in sql:
            return {"chunks": 1734395, "embedded": 84250,
                    "unembedded": 1650145, "latest": NOW - timedelta(hours=7.5)}
        if "document_chunks" in sql:
            return {"chunks": 1734394, "latest": NOW - timedelta(hours=7.5)}
        raise AssertionError(f"unstubbed fetchrow: {sql[:80]}")


def _friday_before(ts: datetime) -> date:
    return ts.astimezone(IST).date()


class FakeAcquire:
    async def __aenter__(self): return FakeConn()
    async def __aexit__(self, *a): return False


class FakePool:
    def acquire(self): return FakeAcquire()


@pytest.fixture
def stages(monkeypatch):
    async def _get_pool(): return FakePool()
    monkeypatch.setattr(P, "get_pool", _get_pool)
    return asyncio.run(P.pipeline_stages())


def _by_id(result, sid):
    return next(s for s in result["stages"] if s["id"] == sid)


class TestEndpoint:
    def test_no_swallowed_exception(self, stages):
        # The assertion every other test here depends on.
        assert stages["db_error"] is None
        assert len(stages["stages"]) == 6

    def test_weekend_produces_no_stale_stage(self, stages):
        assert stages["summary"]["stale"] == 0
        assert [s["state"] for s in stages["stages"]].count("stale") == 0

    def test_ingest_is_healthy_and_reports_trading_days_behind(self, stages):
        ing = _by_id(stages, "ingest")
        assert ing["state"] == "healthy"
        assert ing["trading_days_behind"] == 0
        # Wall-clock age is still reported for display, and is still ~2 days.
        assert ing["age_hours"] > 24

    def test_ingest_state_is_not_driven_by_ingested_at(self, stages):
        # The false-green guard: age_hours (ingested_at) is >24h, which under
        # the old rule meant 'stale'. State now comes from filed_at.
        ing = _by_id(stages, "ingest")
        assert P._state(ing["age_hours"], has_backlog=False) == "stale"
        assert ing["state"] == "healthy"

    def test_classify_is_backlog_not_stale(self, stages):
        cls = _by_id(stages, "classify")
        assert cls["state"] == "backlog"
        assert cls["trading_age_hours"] == 0.0
        assert cls["pending"] == 16389

    def test_discover_is_healthy(self, stages):
        assert _by_id(stages, "discover")["state"] == "healthy"

    def test_parse_chunk_embed_keep_wall_clock_budgets(self, stages):
        # These grind 7 days a week; 7.5h idle is genuinely 'lagging'.
        for sid in ("parse", "embed"):
            assert _by_id(stages, sid)["state"] == "lagging"

    def test_per_source_states_are_reported(self, stages):
        ing = _by_id(stages, "ingest")
        assert {b["source"] for b in ing["breakdown"]} == {"BSE_ANN", "NSE_ANN"}
        assert all(b["trading_days_behind"] == 0 for b in ing["breakdown"])


class TestDegradation:
    def test_missing_holiday_table_does_not_blank_the_panel(self, monkeypatch):
        class NoCalendarConn(FakeConn):
            async def fetchval(self, sql, *a):
                raise RuntimeError("relation nidp.nse_holidays does not exist")

        class Acq:
            async def __aenter__(self): return NoCalendarConn()
            async def __aexit__(self, *a): return False

        class Pool:
            def acquire(self): return Acq()

        async def _get_pool(): return Pool()
        monkeypatch.setattr(P, "get_pool", _get_pool)
        out = asyncio.run(P.pipeline_stages())

        # Falls back to the weekday-only calendar: still no weekend false alarm.
        assert out["db_error"] is None
        assert len(out["stages"]) == 6
        assert out["summary"]["stale"] == 0
