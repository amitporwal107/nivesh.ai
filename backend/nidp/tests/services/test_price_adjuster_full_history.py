"""A new corporate action must rewrite the symbol's whole adjusted history.

The nightly run rewrites only rows >= since (today − 30d) but applies every
known action, so a fresh split left older rows on the old factor and the
adjusted series jumped at the window boundary.
"""
import asyncio
from datetime import date

from nidp.services.price_adjuster import service as svc


class _Conn:
    def __init__(self):
        self.calls = []

    async def execute(self, *args, **kwargs):
        return "SET"

    async def fetch(self, sql, *args, **kwargs):
        self.calls.append((sql, args))
        return []


def test_full_history_symbols_bypass_the_since_filter():
    conn = _Conn()
    asyncio.run(svc._load_prices(conn, since=date(2026, 8, 12), symbols=None,
                                 full_history=["ANANDRATHI"]))
    sql, args = conn.calls[0]
    assert "(as_of_date >= $1::date OR symbol = ANY($2::text[]))" in sql
    assert args == (date(2026, 8, 12), ["ANANDRATHI"])


def test_without_full_history_only_since_applies():
    conn = _Conn()
    asyncio.run(svc._load_prices(conn, since=date(2026, 8, 12), symbols=None))
    sql, args = conn.calls[0]
    assert "symbol = ANY" not in sql
    assert args == (date(2026, 8, 12),)
