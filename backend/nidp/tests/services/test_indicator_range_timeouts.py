"""Range backfills must not inherit the pool's 120 s command_timeout.

On 2026-09-11 the recompute's first query (the symbol list over ~1.2M price
rows) timed out under nightly load and killed the whole run.
"""
import asyncio
from datetime import date

from nidp.services.technical_indicator_engine import service as svc


class _Conn:
    def __init__(self):
        self.timeouts = []

    async def fetch(self, sql, *args, timeout=None):
        self.timeouts.append(timeout)
        return []


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


def test_range_symbol_query_uses_the_long_timeout():
    pool = _Pool()
    assert asyncio.run(svc.compute_date_range(pool, date(2026, 9, 1), date(2026, 9, 11))) == []
    assert pool.conn.timeouts == [svc._RANGE_QUERY_TIMEOUT_S]
    assert svc._RANGE_QUERY_TIMEOUT_S > 120
