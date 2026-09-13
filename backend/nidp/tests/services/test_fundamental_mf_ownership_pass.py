"""fundamental_engine fills mf_pct from the AMC monthly disclosures (migration 141)
and survives its failure. mf_pct was NULL for every row: _populate_extended copies it
from v_shareholding_latest, which no shareholding source populates."""
import asyncio
import inspect
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
        return 613


def test_mf_pass_calls_the_migration_141_function_with_a_timeout():
    conn = _Conn()
    assert asyncio.run(svc._populate_mf_ownership(conn, date(2026, 9, 11))) == 613
    sql, timeout = conn.calls[0]
    assert "nidp.populate_mf_ownership" in sql
    assert timeout == svc._POPULATE_TIMEOUT_S


def test_mf_failure_is_not_fatal():
    assert asyncio.run(svc._populate_mf_ownership(_Conn(fail=True), date(2026, 9, 11))) == 0


def test_mf_pass_runs_after_the_extended_pass():
    """The regression: _populate_extended resets mf_pct to NULL on every run, so the MF
    pass must come after it or the derived value is wiped each time the engine executes."""
    src = inspect.getsource(svc)
    extended = src.index("await _populate_extended(conn, target_date)")
    mf = src.index("await _populate_mf_ownership(conn, target_date)")
    assert mf > extended
