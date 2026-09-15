"""A March quarter and its fiscal year are separate rows, so an annual upsert cannot touch a quarter.

Until migration 145 (symbol, period_end, consolidated) was unique, so a fiscal year and its March
quarter shared a row: the Screener backfill put full-year figures into 2,988 March quarters, and
where the year arrived first the quarter had nowhere to live (274 missing, 124 wrong TTM windows).
Both writers now conflict on (symbol, period_end, consolidated, period_type).
"""
import asyncio
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from nidp.services.nse_financials import writer as W  # noqa: E402

FLOWS = ("revenue_from_ops_cr", "total_income_cr", "pat_cr", "eps_basic", "ebitda_cr", "pbt_cr",
         "finance_costs_cr", "depreciation_cr", "raw_data", "source", "source_run_id")
BALANCE_SHEET = ("face_value", "equity_share_capital_cr", "total_equity_cr", "long_term_debt_cr",
                 "cash_and_equiv_cr")


def _captured_sql(monkeypatch):
    seen = {}

    class Conn:
        async def fetchrow(self, sql, *args):
            seen["sql"], seen["args"] = sql, args
            return {"id": 1}

    class Pool:
        def acquire(self):
            class A:
                async def __aenter__(self):
                    return Conn()

                async def __aexit__(self, *_):
                    return False
            return A()

    async def pool():
        return Pool()

    monkeypatch.setattr(W, "get_pool", pool)
    asyncio.run(W.upsert_financials("RELIANCE", {"period_end": "2026-03-31", "period_type": "annual",
                                                 "consolidated": True, "revenue_from_ops_cr": 1055780.0,
                                                 "pat_cr": 95754.0}, source="screener_in_annual"))
    return seen


def _set_clause(sql, col):
    m = re.search(rf"^\s+{col}\s+= (.+),?$", sql.split("DO UPDATE SET", 1)[1], re.M)
    assert m, col
    return m.group(1)


def test_conflict_target_includes_period_type(monkeypatch):
    sql = _captured_sql(monkeypatch)["sql"]
    assert "ON CONFLICT (symbol, period_end, consolidated, period_type)" in sql


def test_income_statement_columns_are_plain_coalesce(monkeypatch):
    sql = _captured_sql(monkeypatch)["sql"]
    for col in FLOWS[:-2]:                       # source / source_run_id take the new writer's values
        assert _set_clause(sql, col).startswith(f"COALESCE(EXCLUDED.{col},"), col
    assert "CASE WHEN EXCLUDED.period_type" not in sql


def test_balance_sheet_upsert_conflicts_on_the_annual_row():
    import inspect
    src = inspect.getsource(W.upsert_balance_sheet)
    assert "ON CONFLICT (symbol, period_end, consolidated, period_type)" in src
    assert "'annual'" in src


def test_balance_sheet_columns_still_fill_in_from_the_year_end(monkeypatch):
    sql = _captured_sql(monkeypatch)["sql"]
    for col in BALANCE_SHEET:
        assert _set_clause(sql, col).startswith(f"COALESCE(EXCLUDED.{col},"), col


def test_annual_rows_are_written_with_lowercase_period_type(monkeypatch):
    assert _captured_sql(monkeypatch)["args"][3] == "annual"   # the guard compares against 'annual'
