"""An annual P&L upsert must never overwrite a March quarter's income statement.

(symbol, period_end, consolidated) is unique, so a fiscal year and its March quarter share a
row. The Screener backfill writes quarters and then annual P&L; with plain COALESCE(EXCLUDED, ...)
the year won, putting full-year figures into 2,988 March quarters on 2026-09-12/13.
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
GUARD = "EXCLUDED.period_type = 'annual' AND nidp.nse_financials_quarterly.period_type ILIKE 'quarterly'"


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


def test_income_statement_columns_keep_the_quarter_when_an_annual_row_collides(monkeypatch):
    sql = _captured_sql(monkeypatch)["sql"]
    for col in FLOWS:
        clause = _set_clause(sql, col)
        assert clause.startswith(f"CASE WHEN {GUARD} THEN nidp.nse_financials_quarterly.{col} ELSE"), col


def test_balance_sheet_columns_still_fill_in_from_the_year_end(monkeypatch):
    sql = _captured_sql(monkeypatch)["sql"]
    for col in BALANCE_SHEET:
        assert _set_clause(sql, col).startswith(f"COALESCE(EXCLUDED.{col},"), col


def test_annual_rows_are_written_with_lowercase_period_type(monkeypatch):
    assert _captured_sql(monkeypatch)["args"][3] == "annual"   # the guard compares against 'annual'
