"""Unit tests for dlq_redrive.redrive_one — the status-transition logic.

No DB / network: the re-run, the success check, and feed-runnability are
monkeypatched; a FakeConn records the UPDATE that would be issued.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from nidp.services.dlq_redrive import service as s


class FakeConn:
    def __init__(self):
        self.execs: list[tuple] = []

    async def execute(self, sql, *args):
        self.execs.append((sql, args))

    async def fetchval(self, *a, **k):  # not used (we patch _succeeded_since)
        return None

    @property
    def last_status(self):
        # args = (dlq_id, status, notes)
        return self.execs[-1][1][1] if self.execs else None


NOW = datetime(2026, 7, 3, tzinfo=timezone.utc)


def _row(notes=None, created_at=None, feed="bhavcopy", td="2026-07-01"):
    return {
        "id": uuid.uuid4(),
        "feed": feed,
        "target_date": td,
        "severity": "P0",
        "notes": notes,
        "created_at": created_at or NOW,
    }


@pytest.fixture(autouse=True)
def base_patch(monkeypatch):
    monkeypatch.setattr(s, "_feed_runnable", lambda feed: True)

    async def rerun_ok(feed, td):
        return None
    monkeypatch.setattr(s, "_rerun_feed", rerun_ok)


def test_replayed_on_success(monkeypatch):
    """TC-5: re-run now succeeds → REPLAYED with replayed_at."""
    async def ok(conn, feed, td, since):
        return True
    monkeypatch.setattr(s, "_succeeded_since", ok)

    conn = FakeConn()
    out = asyncio.run(s.redrive_one(conn, _row(), max_attempts=3, drop_age_days=30, now=NOW))
    assert out == "REPLAYED"
    assert conn.last_status == "REPLAYED"
    assert "replayed_at=NOW()" in conn.execs[-1][0]


def test_stays_pending_under_budget(monkeypatch):
    """TC-6: still failing, attempts < MAX → PENDING, attempt recorded."""
    async def fail(conn, feed, td, since):
        return False
    monkeypatch.setattr(s, "_succeeded_since", fail)

    conn = FakeConn()
    out = asyncio.run(s.redrive_one(conn, _row(notes=None), max_attempts=3, drop_age_days=30, now=NOW))
    assert out == "PENDING"
    assert conn.last_status == "PENDING"
    assert "attempts=1" in conn.execs[-1][1][2]  # notes


def test_investigating_at_max_attempts(monkeypatch):
    """TC-7a: attempts reach MAX → INVESTIGATING."""
    async def fail(conn, feed, td, since):
        return False
    monkeypatch.setattr(s, "_succeeded_since", fail)

    conn = FakeConn()
    # notes already record 2 attempts; this is attempt 3 == max
    out = asyncio.run(s.redrive_one(conn, _row(notes="redrive: attempts=2; ..."),
                                    max_attempts=3, drop_age_days=30, now=NOW))
    assert out == "INVESTIGATING"
    assert "attempts=3" in conn.execs[-1][1][2]


def test_dropped_when_aged_out(monkeypatch):
    """TC-7b: still failing AND older than drop-age → DROPPED."""
    async def fail(conn, feed, td, since):
        return False
    monkeypatch.setattr(s, "_succeeded_since", fail)

    conn = FakeConn()
    old = NOW - timedelta(days=40)
    out = asyncio.run(s.redrive_one(conn, _row(created_at=old),
                                    max_attempts=3, drop_age_days=30, now=NOW))
    assert out == "DROPPED"
    assert conn.last_status == "DROPPED"


def test_unrunnable_feed_goes_investigating(monkeypatch):
    """TC-8: feed has no runnable service → INVESTIGATING immediately, no crash."""
    monkeypatch.setattr(s, "_feed_runnable", lambda feed: False)

    called = {"rerun": False}

    async def rerun_should_not_run(feed, td):
        called["rerun"] = True
    monkeypatch.setattr(s, "_rerun_feed", rerun_should_not_run)

    conn = FakeConn()
    out = asyncio.run(s.redrive_one(conn, _row(feed="not_a_feed"),
                                    max_attempts=3, drop_age_days=30, now=NOW))
    assert out == "INVESTIGATING"
    assert called["rerun"] is False
    assert "no runnable service" in conn.execs[-1][1][2]
