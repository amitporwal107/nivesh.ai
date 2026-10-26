"""bar_repair.PgStore against a real, disposable Postgres: plan, apply (snapshot first), a second apply that changes
nothing, and restore back to the exact pre-apply rows (NUMERIC, JSONB, TEXT[], timestamps included).

Opt-in: skipped unless SCANNER_REPAIR_PG_DSN points at a THROWAWAY database (the test drops and recreates
stock_ohlcv, stock_technical_features and positional_signals there). Example, with no network at all:

    docker run -d --rm --name scanner-repair-pgtest --network none -e POSTGRES_PASSWORD=test postgres:16-alpine
    docker run --rm --network container:scanner-repair-pgtest -v $PWD:/work:ro -w /work/backend \\
        -e SCANNER_REPAIR_PG_DSN=postgresql://postgres:test@localhost:5432/postgres ... nivesh/backend:staging \\
        python -m pytest tests/test_scanner_bar_repair_pg.py -q -p no:cacheprovider
    docker stop scanner-repair-pgtest
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import date
from pathlib import Path

import pytest

from services.positional_engine import ENGINE_VERSION, bar_repair, ohlcv_store, pipeline

DSN = os.environ.get("SCANNER_REPAIR_PG_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="SCANNER_REPAIR_PG_DSN not set (needs a throwaway Postgres)")

MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / "015_positional_engine.sql"
S1, S2, S3, HOL, MISS, LAST = (date(2026, 9, 29), date(2026, 9, 30), date(2026, 10, 1), date(2026, 10, 2),
                               date(2026, 10, 5), date(2026, 10, 6))


class Warehouse:
    async def sessions(self, start, end, extra=()):
        return {d for d in (S1, S2, S3, MISS, LAST) if start <= d <= end}

    async def rows(self, d):
        return 2


def scored(sym: str, score: float, actionable: bool) -> dict:
    return {
        "nse_symbol": sym, "actionable": actionable, "reasons": ["Trend up", "Volume above average"],
        "features": {"close": 101.25, "sma_50": 98.5, "sma_200": 90.125, "rsi_14": 61.3, "atr_14": 2.75,
                     "return_5d_pct": 1.5, "return_20d_pct": 6.25, "high_20d": 103.0, "swing_low_20": 95.5,
                     "swing_high_20": 103.0},
        "scores": {"sub_scores": {"trend": .8, "momentum": .7, "structure": .6, "accumulation": .5, "sector": .5,
                                  "risk": .4},
                   "weights": {"trend": .25, "momentum": .15, "structure": .2, "accumulation": .2, "sector": .1,
                               "risk": .1},
                   "scan_hits": ["atlas.trend_up"], "final_score": score, "confidence": "HIGH", "stage": "BREAKOUT"},
        "pre_breakout": {"signals": [], "accumulation_score": 0.42},
        "price_adjustment": {"price_basis": "warehouse_adjusted", "factor_steps": 0, "break_truncated_at": None,
                             "bars_dropped": 0},
        "trade_plan": {"timeframe_days_min": 5, "timeframe_days_max": 15, "entry": 101.25, "stoploss": 96.5,
                       "target": 110.75, "risk_reward": 2.0} if actionable else None,
    }


async def dump(pool) -> dict:
    out = {}
    async with pool.acquire() as conn:
        for table, _col in bar_repair.TABLES:
            out[table] = sorted(r["j"] for r in await conn.fetch(f"SELECT to_jsonb(t)::text j FROM {table} t"))
    return out


async def seed(pool):
    async with pool.acquire() as conn:
        await conn.execute("DROP TABLE IF EXISTS stock_ohlcv, stock_technical_features, positional_signals, "
                           "chartink_scan_hits, positional_outcomes CASCADE")
        await conn.execute(MIGRATION.read_text())
        bars = []
        for d, a, b in ((S1, 10, 20), (S2, 11, 21), (S3, 12.3456, 22), (LAST, 13, 23)):
            bars += [("AAA", d, a, a + 1, a - 1, a, 1000 + int(a), 500, 50.25, "bhavcopy"),
                     ("BBB", d, b, b + 1, b - 1, b, 2000 + int(b), None, None, "bhavcopy")]
        bars += [("AAA", HOL, 12.3456, 13.3456, 11.3456, 12.3456, 1012, 500, 50.25, "bhavcopy"),     # copies 1 Oct
                 ("BBB", HOL, 22, 23, 21, 22, 2022, None, None, "bhavcopy")]
        await conn.executemany(
            "INSERT INTO stock_ohlcv (nse_symbol, bar_date, open_price, high_price, low_price, close_price, volume,"
            " delivery_qty, delivery_pct, source) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)", bars)
        for d in (S3, HOL, LAST):
            await pipeline.write_scored(conn, d, [scored("AAA", .7123, True), scored("BBB", .4, False)])
        await conn.execute("UPDATE stock_technical_features SET engine_version = 'positional.v1.0'")
        await conn.execute("UPDATE positional_signals SET engine_version = 'positional.v1.0'")


def test_pg_apply_twice_then_restore_exactly(tmp_path, monkeypatch):
    import asyncpg
    from services import pg_client

    async def scenario():
        pool = await asyncpg.create_pool(DSN, min_size=1, max_size=3)

        async def get_pool():
            return pool
        monkeypatch.setattr(pg_client, "get_pool", get_pool)
        await seed(pool)
        before = await dump(pool)
        store = bar_repair.PgStore(pool)

        async def ingest(d):          # the real upsert path of the ingester, with a file's parsed bars
            n = await ohlcv_store.upsert_bars([
                {"nse_symbol": "AAA", "bar_date": d, "open": 12.5, "high": 13.5, "low": 11.5, "close": 12.5,
                 "volume": 1012, "delivery_qty": 400, "delivery_pct": 40.0, "source": "bhavcopy"},
                {"nse_symbol": "BBB", "bar_date": d, "open": 22.5, "high": 23.5, "low": 21.5, "close": 22.5,
                 "volume": 2022, "source": "bhavcopy"}])
            return {"date": d.isoformat(), "status": "written", "rows_written": n}

        async def score(d):
            return {"ok": True}, [scored("AAA", .6543, True), scored("BBB", .3, False), scored("CCC", .5, True)]

        plan = await bar_repair.plan_repair(store, Warehouse())
        assert [p["date"] for p in plan["phantom"]] == [HOL] and [m["date"] for m in plan["missing"]] == [MISS]

        snap = tmp_path / "snap.json"
        out = await bar_repair.apply_repair(store, Warehouse(), ingest, score, str(snap))
        assert out["deleted"] == {"stock_ohlcv": 2, "stock_technical_features": 2, "positional_signals": 1}
        assert out["after"]["pending"] == {"delete_dates": [], "backfill_dates": [], "recompute_dates": []}
        async with pool.acquire() as conn:
            assert await conn.fetchval("SELECT count(*) FROM stock_ohlcv WHERE bar_date = $1", HOL) == 0
            assert await conn.fetchval("SELECT count(*) FROM stock_ohlcv WHERE bar_date = $1", MISS) == 2
            got = await conn.fetch("SELECT nse_symbol, engine_version, components->'price_adjustment'->>'price_basis' b"
                                   " FROM stock_technical_features WHERE as_of_date = $1 ORDER BY 1", LAST)
            assert [(r[0], r[1], r[2]) for r in got] == [(s, ENGINE_VERSION, "warehouse_adjusted")
                                                          for s in ("AAA", "BBB", "CCC")]
            assert await conn.fetchval("SELECT count(*) FROM positional_signals WHERE signal_date = $1", LAST) == 2
            assert await conn.fetchval("SELECT count(*) FROM stock_technical_features WHERE as_of_date = $1", S3) == 2
        after_first = await dump(pool)

        second = await bar_repair.apply_repair(store, Warehouse(), ingest, score, str(tmp_path / "again.json"))
        assert second["changed"] is False and await dump(pool) == after_first
        assert not (tmp_path / "again.json").exists()

        s = json.loads(snap.read_text())
        assert {t: len(r) for t, r in s["rows"].items()} == {"stock_ohlcv": 2, "stock_technical_features": 4,
                                                              "positional_signals": 2}
        await bar_repair.restore_snapshot(store, str(snap))
        assert await dump(pool) == before
        await bar_repair.restore_snapshot(store, str(snap))
        assert await dump(pool) == before
        await pool.close()

    asyncio.run(scenario())
