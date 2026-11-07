"""analytics_refresh refreshes the latest session that has prices, and fails loudly when it writes nothing.

The nightly cron runs at 00:10 IST. With the old default (date.today()) every run from 13 Oct 2026 targeted a day with
no prices, wrote 0 rows and still logged OK, so the analytics layer (top movers, sector heatmap, delivery surge, stock
cards) stayed on 12 Oct.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import date

import pytest

from nidp.services.analytics_refresh import service


class _Conn:
    def __init__(self, latest, summary):
        self.latest = latest
        self.summary = summary
        self.calls = []

    async def fetchval(self, sql, *args):
        self.calls.append(("fetchval", sql, args))
        return self.latest

    async def fetchrow(self, sql, *args):
        self.calls.append(("fetchrow", sql, args))
        return {"summary": self.summary}


class _Pool:
    def __init__(self, conn):
        self._conn = conn

    @asynccontextmanager
    async def acquire(self):
        yield self._conn


def _run(monkeypatch, latest, summary, target=None):
    conn = _Conn(latest, summary)

    async def _get_pool():
        return _Pool(conn)

    monkeypatch.setattr(service, "get_pool", _get_pool)
    return asyncio.run(service.run(target)), conn


def test_default_is_the_latest_session_with_a_stock_snapshot(monkeypatch):
    out, conn = _run(monkeypatch, date(2026, 10, 29), {"stock_cards": 2696, "sectors": 22, "duration_ms": 900})
    assert conn.calls[0][0] == "fetchval" and "nidp.stock_daily_snapshot" in conn.calls[0][1] and "<= CURRENT_DATE" in conn.calls[0][1]
    assert conn.calls[1] == ("fetchrow", "SELECT analytics.refresh_all($1::date) AS summary", (date(2026, 10, 29),))
    assert out == {"as_of_date": "2026-10-29", "stock_card_rows": 2696, "sector_snapshot_rows": 22, "elapsed_ms": 900, "rows_inserted": 2718}


def test_an_explicit_date_is_used_as_given(monkeypatch):
    out, conn = _run(monkeypatch, date(2026, 10, 29), {"stock_cards": 10, "sectors": 2}, target=date(2026, 10, 12))
    assert [c[0] for c in conn.calls] == ["fetchrow"]
    assert conn.calls[0][2] == (date(2026, 10, 12),)
    assert out["as_of_date"] == "2026-10-12"


def test_zero_stock_cards_is_a_failure_not_a_silent_ok(monkeypatch):
    with pytest.raises(RuntimeError, match="0 stock cards written for 2026-10-29"):
        _run(monkeypatch, date(2026, 10, 29), {"stock_cards": 0, "sectors": 0})


def test_no_snapshot_at_all_is_a_failure(monkeypatch):
    with pytest.raises(RuntimeError, match="no session to refresh"):
        _run(monkeypatch, None, {"stock_cards": 5, "sectors": 1})
