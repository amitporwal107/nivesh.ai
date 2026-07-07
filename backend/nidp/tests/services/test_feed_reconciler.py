"""Unit tests for feed_reconciler (gap detection + idempotent heal).

No DB / network: JobRun, the backfill helpers, trading-day enumeration,
last_market_close_date, and notify are all monkeypatched. Verifies the
orchestration logic — detect gaps, heal via run_backfill, report result.
"""
from __future__ import annotations

import asyncio
from datetime import date, timedelta

import pytest

from nidp.services.feed_reconciler import service as s


@pytest.fixture
def patched(monkeypatch):
    state = {"succeeded": set(), "backfill_calls": [], "notify": [], "finalized": []}

    async def fake_last_close(market="NSE_EQ"):
        return date(2026, 7, 2)  # a Thursday
    monkeypatch.setattr(s, "last_market_close_date", fake_last_close)

    async def fake_trading_days(start, end, segment="CM"):
        out, cur = [], start
        while cur <= end:
            if cur.weekday() < 5:
                out.append(cur)
            cur += timedelta(days=1)
        return out
    monkeypatch.setattr(s.bf, "trading_days", fake_trading_days)

    async def fake_already(feed, d):
        return (feed, d) in state["succeeded"]
    monkeypatch.setattr(s.bf, "already_succeeded", fake_already)

    async def fake_backfill(*, start, end, services, skip_existing, rolling_first=False):
        state["backfill_calls"].append((start, end, tuple(services)))
        # Simulate healing: mark every (feed, trading-day) as succeeded.
        days = await fake_trading_days(start, end)
        for feed in services:
            for d in days:
                state["succeeded"].add((feed, d))
    monkeypatch.setattr(s.bf, "run_backfill", fake_backfill)

    def fake_notify(subject, body=None):
        state["notify"].append(subject)
        return True
    monkeypatch.setattr(s._notify, "notify", fake_notify)

    class FakeJobRun:
        def __init__(self, ingester, target_date=None, source_url=None):
            self.ingester = ingester
            self.metadata = {}
            self.rows_fetched = self.rows_inserted = self.rows_skipped = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def finalize(self, status, **kw):
            state["finalized"].append(status)
    monkeypatch.setattr(s._job_log, "JobRun", FakeJobRun)

    return state


def test_no_gaps_no_heal(patched, monkeypatch):
    """TC-1: no gaps → OK, run_backfill NOT called."""
    async def always(feed, d):
        return True
    monkeypatch.setattr(s.bf, "already_succeeded", always)

    rep = asyncio.run(s.reconcile(feeds=["bhavcopy"], lookback_days=7))
    assert rep["status"] == "OK"
    assert rep["gaps_before"] == []
    assert patched["backfill_calls"] == []
    assert patched["finalized"] == ["OK"]


def test_gaps_are_healed(patched):
    """TC-2: gaps present → detected, run_backfill called, all healed → OK."""
    rep = asyncio.run(s.reconcile(feeds=["bhavcopy"], lookback_days=3))
    assert len(rep["gaps_before"]) > 0
    assert rep["remaining"] == []
    assert len(rep["healed"]) == len(rep["gaps_before"])
    assert len(patched["backfill_calls"]) == 1
    assert patched["finalized"] == ["OK"]
    assert any("healed" in n for n in patched["notify"])


def test_unhealed_gap_is_actionable(patched, monkeypatch):
    """TC-3: gap remains after heal → FAILED + actionable alert."""
    async def noop_backfill(*, start, end, services, skip_existing, rolling_first=False):
        patched["backfill_calls"].append((start, end))
    monkeypatch.setattr(s.bf, "run_backfill", noop_backfill)

    rep = asyncio.run(s.reconcile(feeds=["bhavcopy"], lookback_days=3))
    assert len(rep["remaining"]) > 0
    assert rep["healed"] == []
    assert patched["finalized"] == ["FAILED"]
    assert any("could NOT be healed" in n for n in patched["notify"])


def test_weekend_excluded_from_gaps(patched, monkeypatch):
    """TC-4: trading_days excludes weekends → no weekend gaps flagged."""
    async def noop_backfill(*, start, end, services, skip_existing, rolling_first=False):
        pass
    monkeypatch.setattr(s.bf, "run_backfill", noop_backfill)

    rep = asyncio.run(s.reconcile(feeds=["bhavcopy"], lookback_days=7))
    assert rep["gaps_before"], "expected some weekday gaps in the window"
    for _feed, d in rep["gaps_before"]:
        assert d.weekday() < 5, f"{d} is a weekend and should not be a gap"


def test_unrunnable_feed_not_falsely_healed(patched, monkeypatch):
    """TC-4b: a feed not in the backfill registry is not claimed as healed."""
    async def noop_backfill(*, start, end, services, skip_existing, rolling_first=False):
        patched["backfill_calls"].append(services)
    monkeypatch.setattr(s.bf, "run_backfill", noop_backfill)

    rep = asyncio.run(s.reconcile(feeds=["not_a_real_feed"], lookback_days=3))
    # Not recoverable → no gaps claimed, no heal attempted.
    assert rep["gaps_before"] == []
    assert patched["backfill_calls"] == []
