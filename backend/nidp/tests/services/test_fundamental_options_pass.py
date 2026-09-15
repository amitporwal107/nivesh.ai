"""fundamental_engine runs the restored options pass (migration 139) and
survives its failure — options_pcr sat at 0% after migration 091 dropped it."""
import asyncio
from datetime import date

from nidp.services.fundamental_engine import service as svc


class _Conn:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    async def fetchval(self, sql, *args, **kwargs):
        self.calls.append((sql, kwargs.get("timeout")))
        if self.fail:
            raise TimeoutError()
        return 7


def test_options_pass_calls_the_restored_function_with_a_timeout():
    conn = _Conn()
    assert asyncio.run(svc._populate_options(conn, date(2026, 9, 11))) == 7
    sql, timeout = conn.calls[0]
    assert "nidp.populate_stock_options_features" in sql
    assert timeout == svc._POPULATE_TIMEOUT_S


def test_options_failure_is_not_fatal():
    assert asyncio.run(svc._populate_options(_Conn(fail=True), date(2026, 9, 11))) == 0
