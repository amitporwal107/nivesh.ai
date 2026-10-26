"""scripts/run_positional_engine.py — the scheduled run's two guards.

--require-bars stops before the scans and the scoring when the day's bars are not in stock_ohlcv (otherwise the
Chartink hits make a universe and the scorer dates the previous session's bars as today's); --skip-if-done makes a
retry do nothing after a run that already scored the day. Without the flags the runner behaves as before.

Every outside call is stubbed: no database, no NSE, no Chartink.
"""
from __future__ import annotations

import asyncio
from datetime import date

import pytest

from scripts import run_positional_engine as runner
from services.positional_engine import bhavcopy_ingester, pipeline, scan_config, session_calendar

DAY = date(2026, 10, 26)


@pytest.fixture
def calls(monkeypatch):
    seen: dict = {"ingest": 0, "pipeline": 0, "scans": 0}

    async def ingest(d):
        seen["ingest"] += 1
        return {"date": d.isoformat(), "status": "written", "rows_written": 2925}

    async def a_session(d):
        return True, "weekday, not an NSE CM holiday"

    async def run_for_date(d):
        seen["pipeline"] += 1
        return {"ok": True, "scored": 10, "actionable": 2}

    async def load(db):
        seen["scans"] += 1
        return []                       # no scans configured: the Chartink step never reaches the network

    monkeypatch.setattr(bhavcopy_ingester, "ingest", ingest)
    monkeypatch.setattr(session_calendar, "check_session", a_session)   # the calendar guard: tests/test_scanner_bar_integrity.py
    monkeypatch.setattr(pipeline, "run_for_date", run_for_date)
    monkeypatch.setattr(scan_config, "load", load)
    return seen


def counts(monkeypatch, bars, signals):
    async def bars_on(d):
        return bars

    async def signals_on(d):
        return signals

    monkeypatch.setattr(runner, "bars_on", bars_on)
    monkeypatch.setattr(runner, "signals_on", signals_on)


def test_require_bars_stops_before_scans_and_scoring_when_the_day_has_no_bars(monkeypatch, calls):
    counts(monkeypatch, bars=0, signals=0)
    out = asyncio.run(runner.run(DAY, fetch_bhavcopy=True, fetch_scans=True, require_bars=True))
    assert out["skipped"] == "no_bars" and out["ok"] is False
    assert calls["ingest"] == 1 and calls["scans"] == 0 and calls["pipeline"] == 0


def test_require_bars_treats_an_unreachable_database_as_no_bars(monkeypatch, calls):
    counts(monkeypatch, bars=None, signals=None)
    out = asyncio.run(runner.run(DAY, fetch_bhavcopy=False, fetch_scans=True, require_bars=True))
    assert out["skipped"] == "no_bars" and calls["pipeline"] == 0


def test_require_bars_scores_when_the_bars_are_in(monkeypatch, calls):
    counts(monkeypatch, bars=2925, signals=0)
    out = asyncio.run(runner.run(DAY, fetch_bhavcopy=True, fetch_scans=True, require_bars=True))
    assert "skipped" not in out and out["ok"] is True
    assert calls["scans"] == 1 and calls["pipeline"] == 1


def test_skip_if_done_does_nothing_after_a_run_that_scored_the_day(monkeypatch, calls):
    counts(monkeypatch, bars=2925, signals=636)
    out = asyncio.run(runner.run(DAY, fetch_bhavcopy=True, fetch_scans=True, require_bars=True, skip_if_done=True))
    assert out == {"date": "2026-10-26", "steps": {}, "ok": True, "skipped": "already_scored"}
    assert calls == {"ingest": 0, "pipeline": 0, "scans": 0}


def test_skip_if_done_runs_when_the_day_is_not_scored(monkeypatch, calls):
    counts(monkeypatch, bars=2925, signals=0)
    out = asyncio.run(runner.run(DAY, fetch_bhavcopy=True, fetch_scans=True, require_bars=True, skip_if_done=True))
    assert out["ok"] is True and calls["pipeline"] == 1


def test_without_the_flags_the_runner_scores_as_before(monkeypatch, calls):
    counts(monkeypatch, bars=0, signals=636)
    out = asyncio.run(runner.run(DAY, fetch_bhavcopy=True, fetch_scans=True))
    assert "skipped" not in out and calls["pipeline"] == 1


@pytest.mark.parametrize("skipped, code", [("no_bars", 2), ("already_scored", 0), (None, 0)])
def test_exit_code(monkeypatch, skipped, code):
    async def fake_run(d, **kw):
        return {"date": str(d), "steps": {}, "ok": skipped != "no_bars", **({"skipped": skipped} if skipped else {})}

    monkeypatch.setattr(runner, "run", fake_run)
    monkeypatch.setattr("sys.argv", ["run_positional_engine", "--date", "2026-10-26", "--require-bars", "--skip-if-done"])
    assert runner.main() == code
