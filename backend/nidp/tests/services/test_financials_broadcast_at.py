"""Quarterly financials must carry the exchange broadcast time.

broadcast_at was NULL on every nse_financials_quarterly row (none of the four
sources returns a filing time), so fundamentals could not be used point-in-time.
It now comes from the matching NSE results announcement.
"""
import asyncio
from datetime import date

import nidp.shared.storage.pg as pg
from nidp.services.nse_financials import service as svc


class _Conn:
    async def fetchval(self, sql, *args):
        self.sql, self.args = sql, args
        return "2026-08-12T17:05:00+05:30"


class _Acquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *exc):
        return False


class _Pool:
    def __init__(self):
        self.conn = _Conn()

    def acquire(self):
        return _Acquire(self.conn)


def test_broadcast_at_comes_from_the_results_announcement(monkeypatch):
    pool = _Pool()

    async def _get_pool():
        return pool

    monkeypatch.setattr(pg, "get_pool", _get_pool)
    got = asyncio.run(svc._results_broadcast_at("TCS", date(2026, 8, 12)))
    assert got == "2026-08-12T17:05:00+05:30"
    assert "nidp.corporate_announcements" in pool.conn.sql
    assert "financial result" in pool.conn.sql
    assert pool.conn.args == ("TCS", date(2026, 8, 12))
