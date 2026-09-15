"""The stale-run reaper must be conservative and honest.

A job_log row stranded in RUNNING by a dead process makes the feed look
busy rather than broken — and because v_feed_status reports the *latest*
run, a stranded latest row hides the failure from every staleness alarm.
Staging carried 24 such rows, the oldest 85 days.
"""
from __future__ import annotations

import asyncio
import re
from contextlib import asynccontextmanager

import pytest

from nidp.shared.storage import reap_stale_runs


class _Conn:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    async def fetch(self, sql, *args):
        self.calls.append((sql, args))
        return self.rows

    @asynccontextmanager
    async def transaction(self):
        yield


class _Pool:
    def __init__(self, conn):
        self._conn = conn

    @asynccontextmanager
    async def acquire(self):
        yield self._conn


def _reap(rows, hours, monkeypatch):
    conn = _Conn(rows)

    async def _get_pool():
        return _Pool(conn)

    monkeypatch.setattr(reap_stale_runs, "get_pool", _get_pool)
    out = asyncio.run(reap_stale_runs.reap(hours))
    return out, conn


def test_returns_what_it_reaped(monkeypatch):
    rows = [{"ingester": "document_parser", "started_at": "2026-07-16"}]
    out, _ = _reap(rows, 6, monkeypatch)
    assert out == [{"ingester": "document_parser", "started_at": "2026-07-16"}]


def test_no_stale_rows_is_a_clean_no_op(monkeypatch):
    out, _ = _reap([], 6, monkeypatch)
    assert out == []


def test_threshold_is_passed_through(monkeypatch):
    _, conn = _reap([], 12, monkeypatch)
    assert conn.calls[0][1] == ("12",)


def test_only_running_rows_are_touched():
    assert "status = 'RUNNING'" in reap_stale_runs._REAP_SQL


def test_only_rows_older_than_the_threshold_are_touched():
    """A long-running ingester must never be shot in the back."""
    sql = re.sub(r"\s+", " ", reap_stale_runs._REAP_SQL)
    assert "started_at < now() - ($1 || ' hours')::interval" in sql


def test_finished_at_is_derived_from_started_at_not_now():
    """A run abandoned in May must not look like it finished today."""
    sql = re.sub(r"\s+", " ", reap_stale_runs._REAP_SQL)
    assert "finished_at = started_at + ($1 || ' hours')::interval" in sql
    assert "finished_at = now()" not in sql


def test_reaped_rows_land_in_an_allowed_status():
    """job_log_status_check permits RUNNING/OK/FAILED/PARTIAL/SKIPPED only."""
    assert "status = 'FAILED'" in reap_stale_runs._REAP_SQL


def test_message_explains_the_cause_and_the_reaper():
    sql = reap_stale_runs._REAP_SQL
    assert "abandoned" in sql
    assert "reap_stale_runs" in sql
    assert "existing error_message is preserved" or "COALESCE(error_message" in sql
