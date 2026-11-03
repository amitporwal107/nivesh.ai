"""TrueData long price history + TD_* macro refresh on a REAL PostgreSQL — TC-13 … TC-17 from
test_reports/truedata_price_history_TESTCASES.md.

Runs only when PG_TEST_DSN points at a THROWAWAY database (it drops and recreates schema nidp). The recipe used for the
PR: `postgres:16-alpine` with `--network none`, and the backend image joined to its network namespace:
    docker run -d --rm --name tdh-pg --network none -e POSTGRES_PASSWORD=pgtest -e POSTGRES_DB=nidp_test postgres:16-alpine
    docker run --rm --network container:tdh-pg -v <worktree>:/work:ro -w /work/backend \
        -e PG_TEST_DSN=postgresql://postgres:pgtest@localhost:5432/nidp_test ... python -m pytest <this file>
Schema: the real migrations 001 (job_log, source_registry), 003 (corporate_actions), 008 (fred_macro), 022 (feed fields), 026
(prices_eod_adjusted), the unique index of 135 that JobRun's upsert needs, and 191 (twice: re-runnable).

Every price below is MOCK — not real data. TrueData is a fake transport (the containers have no network anyway).
"""
from __future__ import annotations

import asyncio
import gzip
import json
import os
import re
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

DSN = os.environ.get("PG_TEST_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="PG_TEST_DSN not set: needs a throwaway PostgreSQL")

MIG = Path(__file__).resolve().parents[2] / "migrations"
READY = {"TRUEDATA_USERNAME": "u", "TRUEDATA_PASSWORD": "p"}


def _shadow():
    from nidp.shared import market_data_source as mds
    return mds.resolve({"source": "shadow"}, READY, integrated=False)


def weekdays(start, n):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


HIST = weekdays(date(2024, 3, 11), 14)
WH = weekdays(date(2024, 4, 1), 12)


def bar(d, c):
    return {"timestamp": d.isoformat(), "open": c, "high": c + 1, "low": c - 1, "close": c, "volume": 100, "oi": 0}


def write(dirpath: Path, sym, rows):
    dirpath.mkdir(parents=True, exist_ok=True)
    with gzip.open(dirpath / f"{sym}.json.gz", "wt") as fh:
        json.dump({"symbol": sym, "from": "x", "to": "y", "rows": rows}, fh)


async def _fresh_schema():
    import asyncpg
    conn = await asyncpg.connect(DSN)
    try:
        await conn.execute("DROP SCHEMA IF EXISTS nidp CASCADE")
        for f in ("001_nidp_base.sql", "003_nidp_flows_events.sql", "008_nidp_fred_macro.sql",
                  "022_nidp_feed_management.sql", "026_nidp_price_adjustments.sql"):
            await conn.execute((MIG / f).read_text())
        idx = re.search(r"CREATE UNIQUE INDEX IF NOT EXISTS source_registry_ingester_key[^;]+;",
                        (MIG / "135_source_registry_dedupe_and_staleness.sql").read_text()).group(0)
        await conn.execute(idx)
        for _ in range(2):                                            # TC-13: re-runnable
            await conn.execute((MIG / "191_truedata_price_history.sql").read_text())
    finally:
        await conn.close()


async def _seed_prices(conn, sym, days, closes):
    run = uuid.uuid4()
    await conn.executemany(
        "INSERT INTO nidp.prices_eod_adjusted (symbol, as_of_date, raw_close, adj_open, adj_high, adj_low, adj_close, "
        "adj_volume, source_run_id) VALUES ($1, $2, $3, $3, $3, $3, $3, 10, $4)",
        [(sym, d, c, run) for d, c in zip(days, closes)])


@pytest.fixture
def pg(monkeypatch):
    monkeypatch.setenv("NIDP_POSTGRES_URL", DSN)
    from nidp.shared.storage import pg as pgmod
    monkeypatch.setattr(pgmod, "_pool", None)
    asyncio.run(_fresh_schema())
    yield pgmod
    pgmod._pool = None


async def _q(sql, *a):
    import asyncpg
    conn = await asyncpg.connect(DSN)
    try:
        return await conn.fetch(sql, *a)
    finally:
        await conn.close()


def q(sql, *a):
    return asyncio.run(_q(sql, *a))


# ── TC-13 migration + view ──────────────────────────────────────────────────────────────────────────────────────

def test_tc13_migration_is_rerunnable_constrained_and_the_view_prefers_our_prices(pg):
    assert q("SELECT count(*) n FROM nidp.schema_migrations WHERE filename = '191_truedata_price_history.sql'")[0]["n"] == 1
    pk = q("SELECT a.attname FROM pg_index i JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey) "
           "WHERE i.indrelid = 'nidp.prices_eod_history'::regclass AND i.indisprimary ORDER BY a.attname")
    assert [r["attname"] for r in pk] == ["as_of_date", "source", "symbol"]

    async def run():
        import asyncpg
        conn = await asyncpg.connect(DSN)
        try:
            rid = uuid.uuid4()
            with pytest.raises(asyncpg.CheckViolationError):
                await conn.execute("INSERT INTO nidp.prices_eod_history (symbol, as_of_date, adj_close, stitch_factor, "
                                   "source_run_id) VALUES ('X', '2020-01-01', 0, 1, $1)", rid)
            await _seed_prices(conn, "VVV", WH[:3], [110, 111, 112])
            await conn.executemany(
                "INSERT INTO nidp.prices_eod_history (symbol, as_of_date, adj_close, stitch_factor, source_run_id) "
                "VALUES ($1, $2, $3, 1, $4)",
                [("VVV", date(2024, 3, 27), 100, rid), ("VVV", date(2024, 3, 28), 101, rid),
                 ("VVV", date(2024, 4, 1), 999, rid),                       # history on our day: hidden by the view
                 ("NOWH", date(2020, 1, 1), 50, rid)])                      # no warehouse rows: all history shows
            v = await conn.fetch("SELECT as_of_date, adj_close, basis_source FROM nidp.v_prices_eod_long_research "
                                 "WHERE symbol = 'VVV' ORDER BY as_of_date")
            n = await conn.fetchval("SELECT count(*) FROM nidp.v_prices_eod_long_research WHERE symbol = 'NOWH'")
            return v, n
        finally:
            await conn.close()

    v, n = asyncio.run(run())
    assert [(r["as_of_date"].isoformat(), float(r["adj_close"]), r["basis_source"]) for r in v] == [
        ("2024-03-27", 100.0, "truedata_history"), ("2024-03-28", 101.0, "truedata_history"),
        ("2024-04-01", 110.0, "NIDP_PRICE_ADJUSTER"), ("2024-04-02", 111.0, "NIDP_PRICE_ADJUSTER"),
        ("2024-04-03", 112.0, "NIDP_PRICE_ADJUSTER")]
    assert n == 1


# ── TC-14 / TC-15 loader ────────────────────────────────────────────────────────────────────────────────────────

def _files(tmp_path):
    raw, ov = tmp_path / "raw", tmp_path / "ov"
    for sym in ("AAA", "BBB", "CCC", "DDD", "EEE", "FFF"):
        write(raw, sym, [bar(d, 100.0 + i) for i, d in enumerate(HIST)])
        write(ov, sym, [bar(d, 100.0 + i) for i, d in enumerate(HIST)][-5:] + [bar(d, 120.0) for d in WH])
    return str(raw), str(ov)


async def _seed_loader(conn):
    await _seed_prices(conn, "AAA", WH, [120.0] * 12)
    await _seed_prices(conn, "BBB", WH, [120.0 * 1.06] * 12)
    await _seed_prices(conn, "CCC", weekdays(date(2025, 10, 1), 12), [120.0] * 12)       # late coverage → SEAM_GAP
    await _seed_prices(conn, "DDD", WH, [120.0] * 6 + [123.0] * 6)                       # basis moves → UNSTABLE
    await _seed_prices(conn, "EEE", WH, [360.0] * 12)                                    # factor 3 + demerger → LOADED
    await _seed_prices(conn, "FFF", WH, [360.0] * 12)                                    # factor 3, no record → flagged
    await conn.execute("INSERT INTO nidp.corporate_actions (symbol, action_type, purpose, ex_date, source, source_run_id) "
                       "VALUES ('EEE', 'DEMERGER', 'Demerger', '2025-04-07', 'NSE', $1), "
                       "('FFF', 'DIVIDEND', 'Dividend', '2025-04-07', 'NSE', $1)", uuid.uuid4())


def counts():
    r = q("SELECT (SELECT count(*) FROM nidp.prices_eod_history) h, (SELECT count(*) FROM nidp.prices_eod_history_stitch) s, "
          "(SELECT count(*) FROM nidp.job_log WHERE ingester = 'truedata_history') j")[0]
    return r["h"], r["s"], r["j"]


def test_tc14_tc15_loader_batches_runs_skips_replaces_and_rolls_back_exactly(pg, tmp_path):
    from nidp.services.truedata_history import service as H
    raw, ov = _files(tmp_path)

    async def seed():
        import asyncpg
        conn = await asyncpg.connect(DSN)
        try:
            await _seed_loader(conn)
        finally:
            await conn.close()
    asyncio.run(seed())

    async def load(**kw):
        try:
            return await H.load(None, raw_dir=raw, overlap_dir=ov, switch=_shadow, batch_size=2, **kw)
        finally:
            await pg.close_pool()

    # TC-15: dry run writes nothing anywhere
    rep = asyncio.run(load(dry_run=True))
    assert rep["status_counts"] == {"LOADED": 3, "SEAM_GAP": 1, "UNSTABLE": 1, "FACTOR_OUT_OF_RANGE": 1}
    assert counts() == (0, 0, 0)

    # TC-14: run 1 — three batches of two, one transaction each
    r1 = asyncio.run(load())
    assert r1["job_status"] == "OK" and r1["rows_inserted"] == 42 and counts() == (42, 6, 1)
    bbb = q("SELECT stitch_factor, adj_close FROM nidp.prices_eod_history WHERE symbol = 'BBB' ORDER BY as_of_date DESC LIMIT 1")
    assert float(bbb[0]["stitch_factor"]) == pytest.approx(1.06) and float(bbb[0]["adj_close"]) == pytest.approx(113 * 1.06)
    st = {r["symbol"]: r for r in q("SELECT * FROM nidp.prices_eod_history_stitch")}
    assert st["CCC"]["status"] == "SEAM_GAP" and st["DDD"]["status"] == "UNSTABLE" and st["AAA"]["rows_loaded"] == 14
    assert st["EEE"]["status"] == "LOADED" and float(st["EEE"]["stitch_factor"]) == 3.0 and "2025-04-07" in st["EEE"]["reason"]
    assert st["FFF"]["status"] == "FACTOR_OUT_OF_RANGE" and st["FFF"]["rows_loaded"] == 0
    assert st["AAA"]["history_to"] == date(2024, 3, 28) and st["AAA"]["warehouse_from"] == date(2024, 4, 1)
    job = q("SELECT status, rows_inserted, metadata FROM nidp.job_log WHERE run_id = $1", uuid.UUID(r1["run_id"]))[0]
    assert job["status"] == "OK" and job["rows_inserted"] == 42
    assert q("SELECT last_run_status FROM nidp.source_registry WHERE ingester = 'truedata_history'")[0]["last_run_status"] == "OK"

    # research view: history then ours, continuous at the seam (BBB: 113 x 1.06 then 120 x 1.06)
    v = q("SELECT as_of_date, adj_close, basis_source FROM nidp.v_prices_eod_long_research WHERE symbol = 'BBB' "
          "AND as_of_date BETWEEN '2024-03-27' AND '2024-04-02' ORDER BY as_of_date")
    assert [r["basis_source"] for r in v] == ["truedata_history"] * 2 + ["NIDP_PRICE_ADJUSTER"] * 2

    # run 2 — already loaded symbols are skipped, nothing rewritten
    r2 = asyncio.run(load())
    assert r2["status_counts"] == {"SKIPPED_EXISTING": 3, "SEAM_GAP": 1, "UNSTABLE": 1, "FACTOR_OUT_OF_RANGE": 1}
    assert r2["rows_inserted"] == 0
    assert q("SELECT DISTINCT source_run_id FROM nidp.prices_eod_history")[0]["source_run_id"] == uuid.UUID(r1["run_id"])

    # run 3 — replace: same rows, now under run 3
    r3 = asyncio.run(load(replace=True))
    assert r3["rows_inserted"] == 42
    assert [r["source_run_id"] for r in q("SELECT DISTINCT source_run_id FROM nidp.prices_eod_history")] == [uuid.UUID(r3["run_id"])]

    # rollback run 3: exactly its rows and stitch records
    async def rb(rid, dry=False):
        try:
            return await H.rollback(rid, dry_run=dry)
        finally:
            await pg.close_pool()
    assert asyncio.run(rb(r3["run_id"], dry=True)) == {"run_id": r3["run_id"], "dry_run": True,
                                                          "would_delete_rows": 42, "would_delete_stitch": 6}
    assert asyncio.run(rb(r3["run_id"])) == {"run_id": r3["run_id"], "deleted_rows": 42, "deleted_stitch": 6}
    assert counts() == (0, 12, 3)                                      # runs 1 and 2 stitch records stay


def test_tc14_a_failure_inside_a_batch_leaves_nothing_of_that_batch(pg):
    from nidp.services.truedata_history import bars as B
    from nidp.services.truedata_history import service as H
    good = B.StitchResult("GOOD", B.LOADED, rows=[{"symbol": "GOOD", "as_of_date": date(2020, 1, 1), "adj_open": 1,
                                                   "adj_high": 1, "adj_low": 1, "adj_close": 1.0, "volume": 1,
                                                   "stitch_factor": 1.0}])
    bad = B.StitchResult("BAD", B.LOADED, rows=[dict(good.rows[0], symbol="BAD", adj_close=-1.0)])   # violates CHECK
    # fails AFTER the rows were inserted in the same transaction: its stitch record cannot be written
    late = B.StitchResult("LATE", B.LOADED, rows=[dict(good.rows[0], symbol="LATE")], max_dev_pct="not a number")

    async def run():
        import asyncpg
        conn = await asyncpg.connect(DSN, server_settings={"search_path": "nidp,public"})
        try:
            with pytest.raises(asyncpg.CheckViolationError):
                await H.write_batch(conn, uuid.uuid4(), [good, bad])
            with pytest.raises(Exception) as late_exc:
                await H.write_batch(conn, uuid.uuid4(), [good, late])
            return type(late_exc.value).__name__
        finally:
            await conn.close()
    assert asyncio.run(run()) in ("DataError", "InvalidTextRepresentationError")
    assert counts()[:2] == (0, 0)


# ── TC-16 macro refresh ─────────────────────────────────────────────────────────────────────────────────────────

class _Transport:
    def __init__(self, rows):
        self.rows, self.calls = rows, []

    def __call__(self, method, url, data, headers, timeout):
        if "auth.truedata.in" in url:
            return 200, b'{"access_token": "t", "expires_in": 3600}'
        from urllib.parse import parse_qs, urlsplit
        sym = parse_qs(urlsplit(url).query)["symbol"][0]
        self.calls.append(sym)
        rows = self.rows.get(sym)
        if not rows:
            return 200, f"No data exists for {sym}".encode()
        return 200, ("timestamp,open,high,low,close,volume,oi\n" + "\n".join(
            f"{d},{c},{c},{c},{c},0,0" for d, c in rows)).encode()


def test_tc16_macro_inserts_only_new_days_never_rewrites_and_rolls_back_exactly(pg):
    from nidp.shared.sources import truedata as td
    from nidp.services.truedata_macro import service as M
    old = uuid.uuid4()

    async def seed():
        import asyncpg
        conn = await asyncpg.connect(DSN)
        try:
            await conn.execute(
                "INSERT INTO nidp.fred_macro (as_of_date, series_id, series_name, value, units, frequency, source, "
                "source_run_id) VALUES ('2026-10-30', 'TD_MCX_CRUDEOIL_1M', 'x', 5000, 'INR per barrel', 'daily', "
                "'truedata', $1), ('2026-10-30', 'DGS10', 'y', 4.1, 'Percent', 'Daily', 'FRED', $1)", old)
        finally:
            await conn.close()
    asyncio.run(seed())
    tr = _Transport({"CRUDEOIL-I": [("2026-10-30", 9999), ("2026-11-02", 5100), ("2026-11-03", 5200)],
                     "NIFTY 50": [("2026-11-02", 25000)]})
    cl = td.TrueDataClient(td.Credentials("u", "p"), transport=tr, min_interval=0)

    async def refresh(now):
        try:
            return await M.refresh(client=cl, switch=_shadow, now_ist=now, codes=["CRUDEOIL-I", "NIFTY 50"])
        finally:
            await pg.close_pool()

    r1 = asyncio.run(refresh(datetime(2026, 11, 3, 0, 15)))
    assert r1["job_status"] == "OK" and r1["rows_inserted"] == 2              # crude 11-02, Nifty 11-02 (new series)
    rows = q("SELECT as_of_date, series_id, series_name, value, source_run_id FROM nidp.fred_macro "
             "WHERE source = 'truedata' ORDER BY series_id, as_of_date")
    assert [(r["as_of_date"].isoformat(), r["series_id"], float(r["value"])) for r in rows] == [
        ("2026-10-30", "TD_MCX_CRUDEOIL_1M", 5000.0), ("2026-11-02", "TD_MCX_CRUDEOIL_1M", 5100.0),
        ("2026-11-02", "TD_NIFTY_50", 25000.0)]                               # 10-30 not rewritten; 11-03 partial
    assert rows[1]["series_name"] == "MCX crude oil, near-month continuous future, close"

    tr.calls.clear()
    r2 = asyncio.run(refresh(datetime(2026, 11, 3, 0, 20)))
    assert tr.calls == [] and r2["rows_inserted"] == 0                          # both up to date: no call

    assert asyncio.run(_rollback(pg, M, r1["run_id"])) == {"run_id": r1["run_id"], "deleted_rows": 2}
    left = q("SELECT series_id, source_run_id FROM nidp.fred_macro ORDER BY series_id")
    assert [(r["series_id"], r["source_run_id"]) for r in left] == [("DGS10", old), ("TD_MCX_CRUDEOIL_1M", old)]
    jobs = q("SELECT status FROM nidp.job_log WHERE ingester = 'truedata_macro' ORDER BY started_at")
    assert [j["status"] for j in jobs] == ["OK", "OK"]


async def _rollback(pg, M, rid):
    try:
        return await M.rollback(rid)
    finally:
        await pg.close_pool()


# ── TC-17 the route's SQL on the real view ──────────────────────────────────────────────────────────────────────

def test_tc17_route_reads_the_real_view(pg, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from nidp.services.daas_api import auth, keys, ratelimit
    from nidp.services.daas_api.routers import prices

    async def seed():
        import asyncpg
        conn = await asyncpg.connect(DSN)
        try:
            await _seed_prices(conn, "RRR", WH[:2], [210, 211])
            await conn.execute("INSERT INTO nidp.prices_eod_history (symbol, as_of_date, adj_close, stitch_factor, "
                               "source_run_id) VALUES ('RRR', '2024-03-28', 200, 1.06, $1)", uuid.uuid4())
        finally:
            await conn.close()
    asyncio.run(seed())
    rec = keys.KeyRecord(key_id="00000000-0000-0000-0000-000000000009", key_prefix="nvd_t", name="t",
                         owner_email="t@nivesh", plan="internal", rate_limit_rpm=1500, daily_quota=None,
                         status="active", expires_at=None)

    async def _resolve(_t):
        return rec

    async def _consume(key_id, *, limit_rpm, daily_quota):
        return ratelimit.LimitDecision(allowed=True, limit_rpm=limit_rpm, remaining_rpm=limit_rpm - 1, reset_seconds=60,
                                       daily_quota=daily_quota, daily_used=1, daily_remaining=None, reason=None)
    monkeypatch.setattr(auth, "_resolve", _resolve)
    monkeypatch.setattr(ratelimit, "consume", _consume)
    # the router binds get_pool at import; an earlier test may have left a fake bound there (test_daas_api patches the
    # pg module only), so pin the REAL pool for this test
    monkeypatch.setattr(prices, "get_pool", pg.get_pool)
    app = FastAPI()
    app.include_router(prices.router, prefix="/v1")
    with TestClient(app) as c:
        body = c.get("/v1/prices/research-long/rrr", headers={"X-API-Key": "nvd_t_x"}, params={"limit": 2}).json()
        older = c.get("/v1/prices/research-long/rrr", headers={"X-API-Key": "nvd_t_x"},
                      params={"end": "2024-03-31"}).json()
    assert [(d["as_of_date"], d["adj_close"], d["basis_source"]) for d in body["data"]] == [
        ("2024-04-02", 211.0, "NIDP_PRICE_ADJUSTER"), ("2024-04-01", 210.0, "NIDP_PRICE_ADJUSTER")]
    assert body["pagination"]["next_offset"] == 2
    assert [(d["as_of_date"], d["stitch_factor"], d["basis_source"]) for d in older["data"]] == [
        ("2024-03-28", 1.06, "truedata_history")]
