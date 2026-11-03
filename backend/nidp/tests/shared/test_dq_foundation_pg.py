"""DQ foundation (PR-1) against a real, disposable Postgres: SH-*, PM-*, PC-*, GE-1, AS-2, G1-5 from
test_reports/dq_foundation_TESTCASES.md.

Opt-in: skipped unless NIDP_DQ_PG_DSN points at a THROWAWAY database (the test drops and recreates the nidp and dq
schemas there). The tables are created from the repository's own migration text (006, 077, 001's ledger) so the
schema cannot drift from what runs on staging; migration 184 is applied as a whole. With no network at all:

    docker run -d --rm --name dq-pgtest --network none -e POSTGRES_PASSWORD=test postgres:16-alpine
    docker run --rm --network container:dq-pgtest -v $PWD:/work:ro -w /work/backend \\
        -e NIDP_DQ_PG_DSN=postgresql://postgres:test@localhost:5432/postgres nivesh/backend:staging \\
        python -m pytest nidp/tests/shared/test_dq_foundation_pg.py -q -p no:cacheprovider
    docker stop dq-pgtest
"""
from __future__ import annotations

import asyncio
import datetime as dt
import os
import re
import uuid
from pathlib import Path

import pytest

DSN = os.environ.get("NIDP_DQ_PG_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="NIDP_DQ_PG_DSN not set (needs a throwaway Postgres)")

MIG = Path(__file__).resolve().parents[2] / "migrations"
D = dt.date(2026, 10, 19)            # target session
P = dt.date(2026, 10, 16)            # previous session


def _create_table(sql_file: str, table: str) -> str:
    text = (MIG / sql_file).read_text()
    m = re.search(rf"CREATE TABLE IF NOT EXISTS {re.escape(table)} \(.*?\n\);", text, re.S)
    assert m, f"{table} not found in {sql_file}"
    return m.group(0)


async def _fresh_db():
    import asyncpg
    conn = await asyncpg.connect(DSN)
    await conn.execute("DROP SCHEMA IF EXISTS nidp CASCADE; DROP SCHEMA IF EXISTS dq CASCADE;"
                       "CREATE SCHEMA nidp; CREATE SCHEMA dq;")
    await conn.execute(_create_table("001_nidp_base.sql", "nidp.schema_migrations"))
    await conn.execute(_create_table("006_nidp_validation.sql", "nidp.validation_runs"))
    await conn.execute(_create_table("006_nidp_validation.sql", "nidp.validation_findings"))
    await conn.execute("ALTER TABLE nidp.validation_runs ADD COLUMN IF NOT EXISTS asset text")   # migration 111
    await conn.execute(_create_table("077_dq_gates_schema.sql", "dq.feed_sla"))
    await conn.execute("""
        CREATE TABLE nidp.prices_eod (symbol text, series text, as_of_date date, close_price numeric,
                                      prev_close numeric);
        CREATE TABLE nidp.corporate_actions (symbol text, ex_date date, record_date date, action_type text);
        CREATE TABLE nidp.shareholding_pattern (symbol text, source text, period_end date, promoter_pct numeric,
                                                public_pct numeric, fii_pct numeric, dii_pct numeric,
                                                govt_holding_pct numeric);
    """)
    await conn.execute((MIG / "184_dq_foundation.sql").read_text())
    return conn


def run(coro):
    return asyncio.run(coro)


# ── SH: shareholding sum, by each source's definition ─────────────────────────────────────────

def test_shareholding_rule():
    from nidp.shared.validation.consistency_rules.equity import SHAREHOLDING_SUM

    async def go():
        conn = await _fresh_db()
        try:
            rows = [
                ("SH1", "NSE_SHP", dt.date(2026, 9, 30), 60, 38, None, None, None),       # 2pp NPNP: fine
                ("SH2", "NSE_SHP", dt.date(2026, 9, 30), 60, 41, None, None, None),       # 101: impossible
                ("SH3", "screener_in", dt.date(2026, 9, 30), 50, 15, 20, 15, 0),          # 100: fine
                ("SH4", "screener_in", dt.date(2026, 9, 30), 50, 5, 20, 15, 0),           # 90: bad
                ("SH5", "NSE_SHP", dt.date(2026, 3, 31), 60, 45, None, None, None),       # bad, but outside window
            ]
            await conn.executemany("INSERT INTO nidp.shareholding_pattern VALUES ($1,$2,$3,$4,$5,$6,$7,$8)", rows)
            findings = await SHAREHOLDING_SUM.check(conn, D)
            assert len(findings) == 1 and findings[0].actual == "2"          # SH2 and SH4 only
            # SH: a newer clean filing supersedes the bad one for the same symbol and source
            await conn.execute("INSERT INTO nidp.shareholding_pattern VALUES "
                               "('SH2','NSE_SHP','2026-10-15',60,39,NULL,NULL,NULL)")
            findings = await SHAREHOLDING_SUM.check(conn, D)
            assert findings[0].actual == "1"
        finally:
            await conn.close()
    run(go())


# ── PM: price move measured against NSE's own prev_close ──────────────────────────────────────

def test_price_move_rule():
    from nidp.shared.validation.consistency_rules.equity import PRICE_TEMPORAL_CHANGE

    async def go():
        conn = await _fresh_db()
        try:
            await conn.executemany("INSERT INTO nidp.prices_eod VALUES ($1,$2,$3,$4,$5)", [
                ("PM1", "EQ", dt.date(2026, 10, 12), 13.8, 13.5),   # stale-looking prior row
                ("PM1", "EQ", D, 130, 128),                          # vs NSE base 128: +1.6%
                ("PM2", "EQ", P, 100, 99),
                ("PM2", "EQ", D, 160, 100),                          # +60%, no action, traded before: flagged
                ("XYZ-RE", "BE", P, 1.0, 1.0), ("XYZ-RE", "BE", D, 1.4, 1.0),      # rights entitlement
                ("XYZ-RE1", "BE", P, 2.1, 2.1), ("XYZ-RE1", "BE", D, 1.3, 2.12),   # rights entitlement, -RE1
                ("PM4", "EQ", P, 100, 99), ("PM4", "EQ", D, 50, 100),              # split on the ex-date
                ("NEWCO", "EQ", D, 1133.8, 700),                     # listing day: issue price as base
            ])
            await conn.execute("INSERT INTO nidp.corporate_actions VALUES ('PM4', $1, NULL, 'SPLIT')", D)
            findings = await PRICE_TEMPORAL_CHANGE.check(conn, D)
            assert [f.entity_id for f in findings] == ["PM2"]
        finally:
            await conn.close()
    run(go())


# ── PC: prev_close continuity ────────────────────────────────────────────────────────────────

def test_prev_close_continuity_rule():
    from nidp.shared.validation.consistency_rules.equity import PREV_CLOSE_CONTINUITY

    async def go():
        conn = await _fresh_db()
        try:
            await conn.executemany("INSERT INTO nidp.prices_eod VALUES ($1,$2,$3,$4,$5)", [
                ("PC1", "EQ", dt.date(2026, 10, 12), 13.83, 13.0), ("PC1", "EQ", D, 130.05, 138.30),  # break
                ("PC2", "EQ", P, 100.00, 99.0), ("PC2", "EQ", D, 101.0, 100.00),                      # equal
                ("PC3", "EQ", P, 100.00, 99.0), ("PC3", "EQ", D, 51.0, 50.00),                        # split
                ("PC4", "EQ", D, 77.0, 70.0),                                                          # new listing
                ("PC5", "EQ", P, 42.10, 41.0), ("PC5", "BE", D, 43.0, 42.10),                          # EQ -> BE
                ("PC6", "EQ", P, 2.86, 2.80), ("PC6", "EQ", D, 2.9, 2.86),                             # paisa-exact
            ])
            await conn.execute("INSERT INTO nidp.corporate_actions VALUES ('PC3', $1, NULL, 'SPLIT')", D)
            findings = await PREV_CLOSE_CONTINUITY.check(conn, D)
            assert [f.entity_id for f in findings] == ["PC1"]
            assert findings[0].value_a == "13.83" and findings[0].value_b == "138.3"
        finally:
            await conn.close()
    run(go())


# ── GE-1: the Great Expectations insert succeeds against the 006 schema ───────────────────────

def test_ge_findings_insert():
    from nidp.services.quality_gate import great_expectations_runner as ge

    async def go():
        conn = await _fresh_db()
        try:
            result = {"findings": [{
                "success": False, "unexpected_percent": 3.0, "expectation_type": "expect_column_values_to_be_between",
                "message": "out of range", "kwargs": {"column": "close_price"}, "unexpected_count": 2,
                "column": "close_price", "columns": None, "element_count": 70, "partial_unexpected_list": [0, -1],
            }]}
            run_id = uuid.uuid4()
            assert await ge._persist_findings(conn, run_id, "bhavcopy", "2026-10-19", result) == 1
            row = await conn.fetchrow("SELECT * FROM nidp.validation_findings")
            assert row["validation_id"] == run_id and row["failure_class"] == "FIX" and row["severity"] == "WARN"
            assert row["target_date"] == D and row["sample_rows"] is not None
        finally:
            await conn.close()
    run(go())


# ── AS-2 + G1-5: migration 184 ────────────────────────────────────────────────────────────────

def test_migration_184_feed_dq_and_floors():
    async def go():
        conn = await _fresh_db()
        try:
            await conn.executemany(
                "INSERT INTO nidp.validation_runs (validation_id, job_run_id, ingester, asset, target_date, status, "
                "started_at) VALUES ($1,$2,$3,$4,$5,$6,$7)", [
                    (uuid.uuid4(), uuid.uuid4(), "bhavcopy", None, D, "PASSED", dt.datetime(2026, 10, 19, 13, 30,
                                                                                            tzinfo=dt.timezone.utc)),
                    (uuid.uuid4(), uuid.uuid4(), "delivery", None, D, "PASSED", dt.datetime(2026, 10, 19, 5, 0,
                                                                                            tzinfo=dt.timezone.utc)),
                    (uuid.uuid4(), uuid.uuid4(), "delivery", "delivery", D, "PARTIAL",
                     dt.datetime(2026, 10, 20, 5, 0, tzinfo=dt.timezone.utc)),
                ])
            rows = {r["ingester"]: r["dq_status"] for r in await conn.fetch("SELECT * FROM nidp.v_feed_dq")}
            assert rows == {"bhavcopy": "PASSED", "delivery": "PARTIAL"}   # NULL-asset rows count; latest wins
            floors = {r["feed"]: r["row_count_min"] for r in await conn.fetch(
                "SELECT feed, row_count_min FROM dq.feed_sla WHERE gate_id = 1")}
            assert floors == {"bhavcopy": 1500, "fno_bhavcopy": 25000, "delivery": 1500, "index_close": 20}
            await conn.execute((MIG / "184_dq_foundation.sql").read_text())                    # re-runnable
            assert await conn.fetchval("SELECT count(*) FROM dq.feed_sla WHERE gate_id = 1") == 4
        finally:
            await conn.close()
    run(go())
