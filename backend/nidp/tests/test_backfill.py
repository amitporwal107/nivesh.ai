"""Unit tests for backfill orchestrator (no DB, no network).

We monkeypatch the trading_days() and already_succeeded() helpers
because they require Postgres. Per-service execution is mocked too —
the test verifies the orchestration logic itself, not the ingesters.
"""
from __future__ import annotations

import asyncio
from datetime import date

import pytest

from nidp import backfill as bf


@pytest.fixture
def fake_run(monkeypatch):
    """Replace each spec's importable run() with a recording stub.

    Returns the list of (service_name, target_date) tuples observed.
    """
    calls: list[tuple[str, date | None]] = []

    class FakeMod:
        def __init__(self, name):
            self.name = name
        async def run(self, td):
            calls.append((self.name, td))
            return None

    fake_mods = {s.module_path: FakeMod(s.name) for s in bf.SPECS}

    def fake_import(path):
        return fake_mods[path]

    monkeypatch.setattr(bf, "importlib", type("M", (), {"import_module": staticmethod(fake_import)}))

    async def no_skip(*_a, **_kw): return False
    monkeypatch.setattr(bf, "already_succeeded", no_skip)

    async def fake_days(start, end, segment="CM"):
        from datetime import timedelta
        cur = start
        out = []
        while cur <= end:
            if cur.weekday() < 5:
                out.append(cur)
            cur += timedelta(days=1)
        return out
    monkeypatch.setattr(bf, "trading_days", fake_days)

    # Disable the polite-gap sleeps for fast tests.
    async def no_sleep(_): return None
    monkeypatch.setattr(bf.asyncio, "sleep", no_sleep)

    return calls


def test_backfill_runs_rolling_then_daily(fake_run):
    report = asyncio.run(bf.run_backfill(
        start=date(2026, 5, 4), end=date(2026, 5, 6),
        skip_existing=False,
    ))
    assert report.runs_failed == 0

    rolling_names = {"nse_calendar", "index_constituents", "bulk_deals",
                     "block_deals", "corporate_actions", "rbi_yields"}
    daily_names = {"bhavcopy", "delivery", "index_close", "fii_dii"}

    rolling_calls = [c for c in fake_run if c[0] in rolling_names]
    daily_calls = [c for c in fake_run if c[0] in daily_names]

    # Rolling sources called exactly once (target_date is None)
    assert {c[0] for c in rolling_calls} == rolling_names
    assert all(c[1] is None for c in rolling_calls)

    # 4 daily services × 3 trading days (Mon-Wed) = 12 daily calls
    assert len(daily_calls) == 12
    assert {c[0] for c in daily_calls} == daily_names
    assert {c[1] for c in daily_calls} == {date(2026, 5, 4), date(2026, 5, 5), date(2026, 5, 6)}


def test_backfill_subset_of_services(fake_run):
    asyncio.run(bf.run_backfill(
        start=date(2026, 5, 4), end=date(2026, 5, 5),
        services=["bhavcopy", "nse_calendar"],
        skip_existing=False,
    ))
    services_seen = {c[0] for c in fake_run}
    assert services_seen == {"bhavcopy", "nse_calendar"}


def test_backfill_skips_weekends(fake_run):
    # 2026-05-02 = Saturday, 2026-05-03 = Sunday, 2026-05-04 = Monday
    asyncio.run(bf.run_backfill(
        start=date(2026, 5, 2), end=date(2026, 5, 4),
        services=["bhavcopy"],
        skip_existing=False,
    ))
    daily = [c for c in fake_run if c[0] == "bhavcopy"]
    # Only Monday should be a target_date for bhavcopy
    assert daily == [("bhavcopy", date(2026, 5, 4))]


def test_backfill_resume_skips_existing(monkeypatch, fake_run):
    # Mark bhavcopy 2026-05-04 as already-succeeded
    async def selective_skip(ingester, target_date):
        return ingester == "bhavcopy" and target_date == date(2026, 5, 4)
    monkeypatch.setattr(bf, "already_succeeded", selective_skip)

    report = asyncio.run(bf.run_backfill(
        start=date(2026, 5, 4), end=date(2026, 5, 5),
        services=["bhavcopy", "delivery"],
        skip_existing=True,
    ))
    daily = [c for c in fake_run if c[0] in {"bhavcopy", "delivery"}]
    # bhavcopy 5/4 is skipped; bhavcopy 5/5 + delivery 5/4, 5/5 still run
    assert ("bhavcopy", date(2026, 5, 4)) not in daily
    assert ("bhavcopy", date(2026, 5, 5)) in daily
    assert ("delivery", date(2026, 5, 4)) in daily
    assert ("delivery", date(2026, 5, 5)) in daily
    assert report.runs_skipped == 1


def test_backfill_failure_isolation(monkeypatch, fake_run):
    """One service failing on one date doesn't stop the rest."""
    real_calls = list(fake_run)

    async def flaky(td):
        if td == date(2026, 5, 4):
            raise RuntimeError("simulated NSE 503")

    # Make bhavcopy specifically flaky on 2026-05-04
    class FlakyMod:
        async def run(self, td): return await flaky(td)

    def fake_import(path):
        if path.endswith("bhavcopy.service"):
            return FlakyMod()
        # Reuse the recording stubs for everything else
        return type("M", (), {"run": staticmethod(lambda td: _record(path, td))})()

    async def _record(path, td):
        name = path.rsplit(".", 2)[-2]
        real_calls.append((name, td))

    monkeypatch.setattr(bf, "importlib", type("I", (), {"import_module": staticmethod(fake_import)}))

    report = asyncio.run(bf.run_backfill(
        start=date(2026, 5, 4), end=date(2026, 5, 5),
        services=["bhavcopy", "delivery"],
        skip_existing=False,
        rolling_first=False,
    ))
    assert report.runs_failed == 1
    assert any("simulated NSE 503" in msg for _, _, msg in report.failures)
    # Other dates / services still ran
    assert report.runs_ok >= 2


def test_invalid_date_range_returns_error(capsys):
    import argparse
    args = argparse.Namespace(
        start=date(2026, 5, 5), end=date(2026, 5, 4),
        services=None, skip_existing=True, rolling_first=True,
    )
    rc = asyncio.run(bf.cmd_backfill(args))
    assert rc == 2
    out = capsys.readouterr().out
    assert "from must be" in out
