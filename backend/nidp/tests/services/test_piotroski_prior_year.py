"""Piotroski needs a prior-year quarter; the lookup never found one.

Every writer stores period_type = 'quarterly' (lowercase) but the query matched
'QUARTERLY' exactly, so prior was always None and the F-score capped at 2 for
the whole universe (staging, 2026-09-08).
"""
import asyncio

from nidp.services.fundamental_engine import service as svc


class _Conn:
    def __init__(self):
        self.sql = None

    async def fetch(self, sql, *args, **kwargs):
        self.sql = sql
        return []


def _sql() -> str:
    conn = _Conn()
    asyncio.run(svc._fetch_prior_year_quarters(conn, ["TCS"]))
    return conn.sql


def test_period_type_is_matched_case_insensitively():
    sql = _sql()
    assert "= 'QUARTERLY'" not in sql
    assert sql.count("ILIKE 'quarterly'") == 2


def test_prior_year_is_a_window_not_an_exact_date():
    sql = _sql()
    assert "INTERVAL '400 days'" in sql and "INTERVAL '330 days'" in sql
    assert "(f.consolidated = l.consolidated) DESC" in sql
