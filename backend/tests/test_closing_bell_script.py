"""scripts/closing_bell.py — the readiness rule the nightly Closing Bell job waits on (TC-1, TC-9 in
test_reports/closing_bell_daily_20261028.md). Ready = the NIDP EOD snapshot for the date carries that date's
prices and index closes AND that date's Top 10 list is stored. Holidays and weekends are flagged so the job
records "no session" instead of alerting."""
from __future__ import annotations

import asyncio
import sys
import types

from scripts import closing_bell as cb


def _patch(monkeypatch, snapshot, holidays=(), ideas=True):
    async def fake_daas(path, params=None):
        if path == "/snapshots/market":
            return {"data": snapshot} if snapshot else {"_http": 404}
        if path == "/desk/macro-calendar":
            return {"holidays": [{"date": h} for h in holidays], "events": []}
        raise AssertionError(path)

    async def has_day(d):
        return ideas

    monkeypatch.setattr(cb, "daas", fake_daas)
    store = types.ModuleType("services.ai_watchlist_store")
    store.has_day = has_day
    monkeypatch.setitem(sys.modules, "services.ai_watchlist_store", store)
    import services
    monkeypatch.setattr(services, "ai_watchlist_store", store, raising=False)


def test_ready_when_snapshot_and_list_exist(monkeypatch):
    _patch(monkeypatch, {"prices_as_of": "2026-10-27", "index_as_of": "2026-10-27", "built_at": "2026-10-27T16:30:02+00:00"})
    r = asyncio.run(cb.readiness("2026-10-27"))
    assert r["ready"] is True and r["snapshot_ready"] is True and r["no_session"] is False


def test_not_ready_without_top10_list(monkeypatch):
    _patch(monkeypatch, {"prices_as_of": "2026-10-27", "index_as_of": "2026-10-27"}, ideas=False)
    r = asyncio.run(cb.readiness("2026-10-27"))
    assert r["ready"] is False and r["snapshot_ready"] is True and r["ideas_list"] is False


def test_stale_snapshot_is_not_ready(monkeypatch):
    # the builder carried yesterday's prices forward: not this date's snapshot
    _patch(monkeypatch, {"prices_as_of": "2026-10-26", "index_as_of": "2026-10-27"})
    assert asyncio.run(cb.readiness("2026-10-27"))["ready"] is False


def test_missing_snapshot_on_a_holiday_is_no_session(monkeypatch):
    _patch(monkeypatch, None, holidays=("2026-11-10",))
    r = asyncio.run(cb.readiness("2026-11-10"))
    assert r["ready"] is False and r["no_session"] is True


def test_weekend_is_no_session(monkeypatch):
    _patch(monkeypatch, None)
    assert asyncio.run(cb.readiness("2026-10-31"))["no_session"] is True   # a Saturday


def test_month_name_param_for_sensibull():
    from datetime import date
    assert cb.month_name(date(2026, 10, 27)) == "2026-October"
