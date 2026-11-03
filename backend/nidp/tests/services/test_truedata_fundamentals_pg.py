"""TrueData fundamentals loader against a real, disposable Postgres — TC-18..TC-27 of
test_reports/truedata_fundamentals_job_TESTCASES.md.

Opt-in: skipped unless NIDP_TDF_PG_DSN points at a THROWAWAY database (the tests drop and recreate the nidp schema).
nse_financials_quarterly is created with staging's column list, primary key and unique index (read from staging's
catalog on 2 Nov 2026; staging's table is a TimescaleDB hypertable, a plain table here); nse_financials_cashflow from
migration 090's own text; the provenance table from migration 190. With no network at all:

    docker run -d --rm --name tdf-pgtest --network none -e POSTGRES_PASSWORD=test postgres:16-alpine
    docker run --rm --network container:tdf-pgtest -v $PWD:/work:ro -w /work/backend \\
        -e NIDP_TDF_PG_DSN=postgresql://postgres:test@localhost:5432/postgres nivesh/backend:staging \\
        python -m pytest nidp/tests/services/test_truedata_fundamentals_pg.py -q -p no:cacheprovider
    docker stop tdf-pgtest

Staging's nse_financials_quarterly is a TimescaleDB hypertable (2.26.4, PG16, 24 uncompressed chunks on 2 Nov 2026).
To run the same tests on one: start timescale/timescaledb:2.26.4-pg16 instead and add -e NIDP_TDF_TIMESCALE=1.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from nidp.services.truedata_fundamentals import loader as L
from nidp.services.truedata_fundamentals import transform as T

DSN = os.environ.get("NIDP_TDF_PG_DSN")
TIMESCALE = os.environ.get("NIDP_TDF_TIMESCALE") == "1"     # run against timescale/timescaledb with a hypertable
pytestmark = pytest.mark.skipif(not DSN, reason="NIDP_TDF_PG_DSN not set (needs a throwaway Postgres)")

MIG = Path(__file__).resolve().parents[2] / "migrations"
D = Decimal

QUARTERLY_DDL = """
CREATE TABLE nidp.nse_financials_quarterly (
    symbol text NOT NULL, period_end date NOT NULL, period_start date, period_type text NOT NULL,
    consolidated boolean NOT NULL, audited boolean,
    revenue_from_ops_cr numeric(18,4), other_income_cr numeric(18,4), total_income_cr numeric(18,4),
    total_expenses_cr numeric(18,4), ebitda_cr numeric(18,4), finance_costs_cr numeric(18,4),
    depreciation_cr numeric(18,4), pbt_before_exc_cr numeric(18,4), exceptional_items_cr numeric(18,4),
    pbt_cr numeric(18,4), tax_expense_cr numeric(18,4), pat_continuing_cr numeric(18,4),
    pat_discontinuing_cr numeric(18,4), pat_cr numeric(18,4), pat_attrib_owners_cr numeric(18,4),
    pat_attrib_minority_cr numeric(18,4), eps_basic numeric(14,4), eps_diluted numeric(14,4),
    face_value numeric(10,4), equity_share_capital_cr numeric(18,4), other_equity_cr numeric(18,4),
    total_equity_cr numeric(18,4), long_term_debt_cr numeric(18,4), short_term_debt_cr numeric(18,4),
    cash_and_equiv_cr numeric(18,4), interest_earned_cr numeric(18,4), interest_expended_cr numeric(18,4),
    nim_pct numeric(8,4), filing_id text, xbrl_url text, broadcast_at timestamptz,
    source text NOT NULL, source_run_id uuid NOT NULL, ingested_at timestamptz NOT NULL DEFAULT now(),
    id bigserial NOT NULL, ir_url text, raw_data jsonb,
    current_assets_cr numeric(18,4), current_liabilities_cr numeric(18,4), trade_receivables_cr numeric(18,4),
    inventory_cr numeric(18,4), trade_payables_cr numeric(18,4),
    PRIMARY KEY (symbol, period_end, consolidated, period_type, source));
CREATE UNIQUE INDEX nse_financials_quarterly_sym_period_cons_type_uniq
    ON nidp.nse_financials_quarterly (symbol, period_end, consolidated, period_type);
"""
OLD_RUN = str(uuid.uuid4())


def _cashflow_ddl() -> str:
    text = (MIG / "090_screener_balance_cashflow.sql").read_text()
    m = re.search(r"CREATE TABLE IF NOT EXISTS nidp\.nse_financials_cashflow \(.*?\n\);", text, re.S)
    assert m
    return m.group(0)


async def fresh_db():
    import asyncpg
    conn = await asyncpg.connect(DSN)
    await conn.execute("DROP SCHEMA IF EXISTS nidp CASCADE; CREATE SCHEMA nidp;")
    await conn.execute(QUARTERLY_DDL)
    if TIMESCALE:                                               # staging's table is a hypertable
        await conn.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
        await conn.execute("SELECT create_hypertable('nidp.nse_financials_quarterly', 'period_end', "
                           "chunk_time_interval => interval '1 year')")
    await conn.execute(_cashflow_ddl())
    mig = (MIG / "190_truedata_fundamentals_fills.sql").read_text()
    await conn.execute(mig)
    await conn.execute(mig)                                     # TC-27: idempotent
    await seed(conn)
    return conn


async def seed(conn):
    """Rows other sources own, as on staging: a March quarter (trendlyne) with equity set, the fiscal-year row
    (screener) on the same date with nothing set, a September quarter, a yahoo cash-flow row with CFO only."""
    q = """INSERT INTO nidp.nse_financials_quarterly (symbol, period_end, period_type, consolidated, source,
               source_run_id, revenue_from_ops_cr, total_equity_cr, finance_costs_cr, raw_data)
           VALUES ($1, $2, $3, true, $4, $5::uuid, $6, $7, $8, $9::jsonb)"""
    await conn.executemany(q, [
        ("AAAA", date(2026, 3, 31), "quarterly", "trendlyne_mcp", OLD_RUN, D("640"), D("1"), None, '{"tl": 1}'),
        ("AAAA", date(2026, 3, 31), "annual", "screener_in_annual", OLD_RUN, D("2600"), None, D("12"), None),
        ("AAAA", date(2026, 9, 30), "quarterly", "trendlyne_mcp", OLD_RUN, D("650"), None, None, None),
        ("AAAA", date(2026, 6, 30), "quarterly", "trendlyne_mcp", OLD_RUN, D("645"), None, D("2"), None),
    ])
    await conn.execute("""INSERT INTO nidp.nse_financials_cashflow (symbol, period_end, consolidated, cfo_cr, source,
                          source_run_id) VALUES ('AAAA', '2025-03-31', true, 400, 'yahoo_finance', $1::uuid)""", OLD_RUN)


def offer(kind, pe, quarter, values, fid=9, may_insert=False, symbol="AAAA"):
    return T.Offer(kind, symbol, date.fromisoformat(pe), True, quarter, fid, "2026-10-20T10:00:00", "crore",
                   "revenue anchor (annual row) ratio 1", {k: D(v) for k, v in values.items()}, may_insert)


BS_FY = offer("balance_sheet", "2026-03-31", "Yearly", {"current_assets_cr": "600.5", "total_equity_cr": "700.25",
                                                        "current_liabilities_cr": "300"}, fid=100, may_insert=True)
BS_FY_NEW = offer("balance_sheet", "2025-03-31", "Yearly", {"current_assets_cr": "500", "total_equity_cr": "650"},
                  fid=90, may_insert=True)
BS_H1_NO_ROW = offer("balance_sheet", "2025-09-30", "Second quarter", {"current_assets_cr": "550"}, fid=95)
BS_H1 = offer("balance_sheet", "2026-09-30", "Second quarter", {"current_assets_cr": "610", "inventory_cr": "0"},
              fid=200)
CF_NEW = offer("cash_flow", "2026-03-31", "Yearly", {"cfo_cr": "520", "cfi_cr": "-128", "cff_cr": "-421",
                                                     "capex_cr": "-40.78", "net_change_cash_cr": "-19"},
               fid=100, may_insert=True)
CF_FILL = offer("cash_flow", "2025-03-31", "Yearly", {"cfo_cr": "999", "capex_cr": "-30"}, fid=90, may_insert=True)
FC_Q2 = offer("finance_costs", "2026-09-30", "Second quarter", {"finance_costs_cr": "3.21"}, fid=200)
FC_Q4 = offer("finance_costs", "2026-03-31", "Yearly", {"finance_costs_cr": "3.0"}, fid=100)
FC_Q1_SET = offer("finance_costs", "2026-06-30", "First quarter", {"finance_costs_cr": "2.5"}, fid=150)
FC_NO_ROW = offer("finance_costs", "2025-12-31", "Third quarter", {"finance_costs_cr": "2.9"}, fid=170)
ALL = [BS_FY, BS_FY_NEW, BS_H1_NO_ROW, BS_H1, CF_NEW, CF_FILL, FC_Q2, FC_Q4, FC_Q1_SET, FC_NO_ROW]


async def snapshot(conn):
    q = await conn.fetch("SELECT * FROM nidp.nse_financials_quarterly ORDER BY symbol, period_end, consolidated, "
                         "period_type")
    c = await conn.fetch("SELECT * FROM nidp.nse_financials_cashflow ORDER BY symbol, period_end, consolidated")
    return [tuple(r.values()) for r in q], [tuple(r.values()) for r in c]


async def qrow(conn, pe, ptype):
    return await conn.fetchrow("SELECT * FROM nidp.nse_financials_quarterly WHERE symbol='AAAA' AND period_end=$1 "
                               "AND consolidated AND period_type=$2", date.fromisoformat(pe), ptype)


async def load(conn, offers, run_id):
    async with conn.transaction():
        q, c = await L.read_rows(conn, L.offer_keys(offers), lock=True)
        plan = L.build_plan(offers, q, c)
        return await L.apply_plan(conn, plan, run_id)


def run(coro):
    return asyncio.run(coro)


# ── TC-18 .. TC-22 ───────────────────────────────────────────────────────────────────────────────────────────

def test_tc18_to_tc22_fill_only_inserts_provenance():
    async def go():
        conn = await fresh_db()
        try:
            rid = str(uuid.uuid4())
            out = await load(conn, ALL, rid)
            # TC-18: NULL columns filled on both rows of 2026-03-31; the trendlyne equity (1) is not overwritten
            mq, fy = await qrow(conn, "2026-03-31", "quarterly"), await qrow(conn, "2026-03-31", "annual")
            assert (mq["current_assets_cr"], mq["total_equity_cr"], mq["current_liabilities_cr"]) == \
                (D("600.5000"), D("1.0000"), D("300.0000"))
            assert (fy["current_assets_cr"], fy["total_equity_cr"]) == (D("600.5000"), D("700.2500"))
            assert (mq["source"], mq["source_run_id"], mq["raw_data"]) == ("trendlyne_mcp", uuid.UUID(OLD_RUN),
                                                                            '{"tl": 1}')   # owner + raw untouched
            assert fy["revenue_from_ops_cr"] == D("2600.0000") and fy["finance_costs_cr"] == D("12.0000")
            # TC-19: FY with no row → one annual 'truedata' row; H1 with no row → nothing; no share capital
            new = await qrow(conn, "2025-03-31", "annual")
            assert (new["source"], str(new["source_run_id"]), new["current_assets_cr"]) == ("truedata", rid,
                                                                                           D("500.0000"))
            assert new["equity_share_capital_cr"] is None
            assert json.loads(new["raw_data"])["truedata_fundamentals"]["td_filing_id"] == 90
            assert await conn.fetchval("SELECT count(*) FROM nidp.nse_financials_quarterly "
                                       "WHERE period_end = '2025-09-30'") == 0
            # TC-20: cash flow inserted where none; existing yahoo row: only NULL capex filled, CFO 400 kept
            cfn = await conn.fetchrow("SELECT * FROM nidp.nse_financials_cashflow WHERE period_end='2026-03-31'")
            assert (cfn["cfo_cr"], cfn["capex_cr"], cfn["source"], str(cfn["source_run_id"])) == \
                (D("520.0000"), D("-40.7800"), "truedata", rid)
            cfo = await conn.fetchrow("SELECT * FROM nidp.nse_financials_cashflow WHERE period_end='2025-03-31'")
            assert (cfo["cfo_cr"], cfo["capex_cr"], cfo["source"]) == (D("400.0000"), D("-30.0000"), "yahoo_finance")
            # TC-21: finance costs on NULL quarterly rows only
            assert (await qrow(conn, "2026-09-30", "quarterly"))["finance_costs_cr"] == D("3.2100")
            assert mq["finance_costs_cr"] == D("3.0000")
            assert fy["finance_costs_cr"] == D("12.0000")                      # annual row untouched
            assert (await qrow(conn, "2026-06-30", "quarterly"))["finance_costs_cr"] == D("2.0000")  # set: kept
            assert await conn.fetchval("SELECT count(*) FROM nidp.nse_financials_quarterly "
                                       "WHERE period_end = '2025-12-31'") == 0
            # TC-22: provenance — one row per write, exact columns and values
            prov = await conn.fetch("SELECT * FROM nidp.truedata_fundamentals_fills WHERE run_id = $1::uuid "
                                    "ORDER BY kind, period_end, period_type", rid)
            got = [(p["kind"], str(p["period_end"]), p["period_type"], p["row_source"], p["inserted"],
                    list(p["columns_filled"]), json.loads(p["values_written"]), p["td_filing_id"]) for p in prov]
            assert got == [
                ("balance_sheet", "2025-03-31", "annual", "truedata", True, ["current_assets_cr", "total_equity_cr"],
                 {"current_assets_cr": "500", "total_equity_cr": "650"}, 90),
                ("balance_sheet", "2026-03-31", "annual", "screener_in_annual", False,
                 ["current_assets_cr", "current_liabilities_cr", "total_equity_cr"],
                 {"current_assets_cr": "600.5", "current_liabilities_cr": "300", "total_equity_cr": "700.25"}, 100),
                ("balance_sheet", "2026-03-31", "quarterly", "trendlyne_mcp", False,
                 ["current_assets_cr", "current_liabilities_cr"],
                 {"current_assets_cr": "600.5", "current_liabilities_cr": "300"}, 100),
                ("balance_sheet", "2026-09-30", "quarterly", "trendlyne_mcp", False,
                 ["current_assets_cr", "inventory_cr"], {"current_assets_cr": "610", "inventory_cr": "0"}, 200),
                ("cash_flow", "2025-03-31", "annual", "yahoo_finance", False, ["capex_cr"], {"capex_cr": "-30"}, 90),
                ("cash_flow", "2026-03-31", "annual", "truedata", True,
                 ["capex_cr", "cff_cr", "cfi_cr", "cfo_cr", "net_change_cash_cr"],
                 {"capex_cr": "-40.78", "cff_cr": "-421", "cfi_cr": "-128", "cfo_cr": "520",
                  "net_change_cash_cr": "-19"}, 100),
                ("finance_costs", "2026-03-31", "quarterly", "trendlyne_mcp", False, ["finance_costs_cr"],
                 {"finance_costs_cr": "3.0"}, 100),
                ("finance_costs", "2026-09-30", "quarterly", "trendlyne_mcp", False, ["finance_costs_cr"],
                 {"finance_costs_cr": "3.21"}, 200)]
            assert all(p["unit"] == "crore" and p["unit_how"].startswith("revenue anchor") for p in prov)
            assert out["rows_written"] == 8
            assert out["balance_sheet_insert_rows"] == 1 and out["cash_flow_insert_rows"] == 1
        finally:
            await conn.close()
    run(go())


# ── TC-23 dry run ────────────────────────────────────────────────────────────────────────────────────────────

def test_tc23_dry_run_writes_nothing_and_matches_the_real_run(monkeypatch):
    async def go():
        import asyncpg
        conn = await fresh_db()
        pool = await asyncpg.create_pool(DSN, min_size=1, max_size=2)

        async def get_pool():
            return pool
        monkeypatch.setattr(L, "get_pool", get_pool)
        try:
            before = await snapshot(conn)
            dry = await L.Warehouse().load(ALL, None, dry_run=True)
            assert await snapshot(conn) == before
            assert await conn.fetchval("SELECT count(*) FROM nidp.truedata_fundamentals_fills") == 0
            real = await L.Warehouse().load(ALL, str(uuid.uuid4()), dry_run=False)
            assert dry["would_write_rows"] == real["rows_written"] == 8
            for k in ("balance_sheet_fill_rows", "balance_sheet_insert_rows", "cash_flow_fill_rows",
                      "balance_sheet_columns_written", "cash_flow_columns_written", "finance_costs_columns_written",
                      "cash_flow_insert_rows", "finance_costs_fill_rows", "balance_sheet_half_year_no_row",
                      "finance_costs_already_set", "finance_costs_no_quarterly_row"):
                assert dry.get(k) == real.get(k), k
        finally:
            await pool.close()
            await conn.close()
    run(go())


# ── TC-24 rollback ───────────────────────────────────────────────────────────────────────────────────────────

def test_tc24_rollback_restores_exactly_and_is_idempotent():
    async def go():
        conn = await fresh_db()
        try:
            before = await snapshot(conn)
            rid = str(uuid.uuid4())
            await load(conn, ALL, rid)
            assert await snapshot(conn) != before
            out = await L.rollback_run(conn, rid)
            assert await snapshot(conn) == before                          # every row, every column, as before
            assert out["provenance_rows"] == 8 and out["inserted_rows_deleted"] == 2
            assert out["columns_reset_to_null"] == 10 and out.get("columns_changed_since_kept", 0) == 0
            again = await L.rollback_run(conn, rid)
            assert again == {"provenance_rows": 0}
            assert await conn.fetchval("SELECT count(*) FROM nidp.truedata_fundamentals_fills "
                                       "WHERE rolled_back_at IS NOT NULL") == 8
        finally:
            await conn.close()
    run(go())


def test_tc24_rollback_keeps_a_value_another_writer_set_since():
    async def go():
        conn = await fresh_db()
        try:
            rid = str(uuid.uuid4())
            await load(conn, ALL, rid)
            # a later Trendlyne build writes its own equity on the fiscal-year row we filled
            await conn.execute("UPDATE nidp.nse_financials_quarterly SET total_equity_cr = 999 "
                               "WHERE symbol='AAAA' AND period_end='2026-03-31' AND period_type='annual'")
            out = await L.rollback_run(conn, rid)
            fy = await qrow(conn, "2026-03-31", "annual")
            assert fy["total_equity_cr"] == D("999.0000")                    # kept
            assert fy["current_assets_cr"] is None                           # ours: back to NULL
            assert out["columns_changed_since_kept"] == 1
        finally:
            await conn.close()
    run(go())


def test_tc24_rollback_refuses_a_non_uuid():
    async def go():
        conn = await fresh_db()
        try:
            with pytest.raises(ValueError):
                await L.rollback_run(conn, "1; DROP TABLE x")
        finally:
            await conn.close()
    run(go())


# ── TC-25 idempotent rerun ───────────────────────────────────────────────────────────────────────────────────

def test_tc25_same_input_twice_writes_nothing_new():
    async def go():
        conn = await fresh_db()
        try:
            await load(conn, ALL, str(uuid.uuid4()))
            after_first = await snapshot(conn)
            second = await load(conn, ALL, str(uuid.uuid4()))
            assert second["rows_written"] == 0 and await snapshot(conn) == after_first
        finally:
            await conn.close()
    run(go())


# ── TC-26 one transaction ────────────────────────────────────────────────────────────────────────────────────

def test_tc26_error_mid_load_leaves_nothing():
    async def go():
        conn = await fresh_db()
        try:
            before = await snapshot(conn)
            bad = offer("cash_flow", "2024-03-31", "Yearly", {"cfo_cr": "1e20"}, fid=80, may_insert=True)
            import asyncpg
            with pytest.raises(asyncpg.exceptions.NumericValueOutOfRangeError):
                await load(conn, ALL + [bad], str(uuid.uuid4()))        # fills ran first, then the insert fails
            assert await snapshot(conn) == before
            assert await conn.fetchval("SELECT count(*) FROM nidp.truedata_fundamentals_fills") == 0
        finally:
            await conn.close()
    run(go())


# ── references (unit anchors) ────────────────────────────────────────────────────────────────────────────────

def test_read_references_shares_from_market_cap_and_close_on_its_date(monkeypatch):
    async def go():
        import asyncpg
        conn = await fresh_db()
        pool = await asyncpg.create_pool(DSN, min_size=1, max_size=2)

        async def get_pool():
            return pool
        monkeypatch.setattr(L, "get_pool", get_pool)
        try:
            await conn.execute("""
                CREATE TABLE nidp.stock_features_daily (symbol text, as_of_date date, market_cap_cr numeric,
                                                        close numeric, fundamentals_as_of date);
                CREATE TABLE nidp.prices_eod (symbol text, as_of_date date, series text, close_price numeric);
                INSERT INTO nidp.stock_features_daily VALUES ('AAAA', '2026-11-02', 1000, 1300, '2026-10-12'),
                                                              ('ZZZZ', '2026-11-02', NULL, 10, NULL);
                INSERT INTO nidp.prices_eod VALUES ('AAAA', '2026-10-12', 'EQ', 100), ('AAAA', '2026-11-02', 'EQ', 130),
                                                   ('AAAA', '2026-10-12', 'BE', 99);""")
            refs = await L.read_references(conn)
            assert refs.known == {"AAAA", "ZZZZ"} and refs.bse_map == {}          # no BSE view here: still runs
            assert refs.shares == {"AAAA": pytest.approx(1000 * 1e7 / 100)}        # close of 12 Oct, EQ series
            assert refs.ours.fy_revenue("AAAA", True, date(2026, 3, 31)) == (2600.0, "annual row")
            assert refs.ours.quarter_revenue("AAAA", True, date(2026, 9, 30)) == 650.0
            via = await L.Warehouse().references(["aaaa"])          # read-only transaction, BSE view absent
            assert via.known == {"AAAA"} and via.caps == {"AAAA": 1000.0}
            await conn.execute("""CREATE VIEW nidp.v_bse_scrip_to_nse AS
                SELECT '2026-11-01'::date AS as_of_date, '500001' AS scrip_code, 'AAAA' AS nse_symbol
                UNION ALL SELECT '2026-10-01', '500001', 'OLDNAME'""")
            assert (await L.Warehouse().references()).bse_map == {"500001": "AAAA"}   # latest mapping wins
        finally:
            await pool.close()
            await conn.close()
    run(go())


# ── TC-35 / TC-36 / TC-37: the real gate reads the database it would write to ────────────────────────────────

def test_tc35_to_tc37_gate_reads_current_database(monkeypatch):
    async def go():
        import asyncpg
        admin = await asyncpg.connect(DSN)
        if not await admin.fetchval("SELECT 1 FROM pg_database WHERE datname = 'nidp_staging'"):
            await admin.execute("CREATE DATABASE nidp_staging")
        other = await admin.fetchval("SELECT current_database()")
        await admin.close()
        staging_dsn = DSN.rsplit("/", 1)[0] + "/nidp_staging"
        cases = [(staging_dsn, {}, ("staging", True)),
                 (staging_dsn, {"NIDP_HOME": "/opt/nidp-staging"}, ("staging", True)),
                 (staging_dsn, {"NIDP_HOME": "/opt/nidp"}, ("production", False)),
                 (staging_dsn, {"APP_ENV": "production"}, ("production", False))]
        if other not in ("nidp_staging", "nidp"):
            cases.append((DSN, {"NIDP_ENV": "staging"}, ("unknown", False)))
        for dsn, env, want in cases:
            pool = await asyncpg.create_pool(dsn, min_size=1, max_size=1)

            async def get_pool(p=pool):
                return p
            monkeypatch.setattr(L, "get_pool", get_pool)
            try:
                v = await L.Warehouse().load_gate(env)
                assert (v.environment, v.allowed) == want, (dsn.rsplit("/", 1)[1], env, v.reason)
            finally:
                await pool.close()
    run(go())
