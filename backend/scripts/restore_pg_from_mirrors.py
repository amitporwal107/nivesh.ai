"""Restore Postgres master + analytics tables from Mongo `pg_mirror_*` collections.

Counterpart to `scripts.mirror_pg_to_mongo`. Idempotent — uses upsert on the
natural-key recorded in `pg_mirror_meta`. Use this as Phase 2 of the
post-deploy migration pipeline.

Usage:
    cd /app/backend && python -m scripts.restore_pg_from_mirrors [--only TABLE]
"""
from __future__ import annotations
import argparse
import asyncio
import logging
import os
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from dotenv import load_dotenv  # noqa: E402
load_dotenv(BACKEND_ROOT / ".env")

log = logging.getLogger("restore_pg_from_mirrors")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


async def _hydrate_secrets():
    from motor.motor_asyncio import AsyncIOMotorClient
    from helpers import secrets as _s
    mc = AsyncIOMotorClient(os.environ["MONGO_URL"])
    try:
        await _s.hydrate_from_db(mc[os.environ["DB_NAME"]])
    finally:
        mc.close()
    pg_url = _s.get("POSTGRES_URL")
    if not pg_url:
        raise RuntimeError("POSTGRES_URL missing from hydrated secrets")
    os.environ["POSTGRES_URL"] = pg_url


def _coerce_for_pg(col_name: str, val: Any, col_type: str) -> Any:
    """Convert JSON-round-tripped mongo value back to the PG column type."""
    if val is None:
        return None
    if col_type in ("uuid",):
        import uuid
        return uuid.UUID(str(val)) if not isinstance(val, uuid.UUID) else val
    if col_type in ("date",) and isinstance(val, str):
        try:
            return date.fromisoformat(val[:10])
        except ValueError:
            return None
    if col_type in ("timestamp without time zone",):
        if isinstance(val, str):
            try:
                dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
                # Strip tz so asyncpg doesn't complain about naive vs aware.
                return dt.replace(tzinfo=None)
            except ValueError:
                return None
        if isinstance(val, datetime) and val.tzinfo is not None:
            return val.replace(tzinfo=None)
        return val
    if col_type in ("timestamp with time zone",):
        if isinstance(val, str):
            try:
                dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    from datetime import timezone as _tz
                    dt = dt.replace(tzinfo=_tz.utc)
                return dt
            except ValueError:
                return None
        if isinstance(val, datetime) and val.tzinfo is None:
            from datetime import timezone as _tz
            return val.replace(tzinfo=_tz.utc)
        return val
    return val


async def _column_types(conn, table: str) -> Dict[str, str]:
    rows = await conn.fetch(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_name = $1", table,
    )
    return {r["column_name"]: r["data_type"] for r in rows}


async def _restore_one(pg_pool, mongo_db, table: str, keys: List[str]) -> Dict[str, Any]:
    coll = mongo_db[f"pg_mirror_{table}"]
    total = await coll.count_documents({})
    if total == 0:
        return {"table": table, "rows": 0, "upserted": 0, "skipped": "empty_mirror"}

    # Special-case: mutual_fund_holdings has no natural-key unique constraint
    # (PK is `id`). Use delete-by-instrument-then-insert so restores are
    # idempotent without ON CONFLICT.
    if table == "mutual_fund_holdings":
        return await _restore_holdings(pg_pool, coll, total)

    t0 = time.perf_counter()
    async with pg_pool.acquire() as conn:
        col_types = await _column_types(conn, table)
        if not col_types:
            return {"table": table, "error": "table_missing_in_pg"}

        # Build INSERT ... ON CONFLICT statement once.  Exclude columns PG
        # auto-fills (created_at) so a fresh DB's defaults win.
        cols = [c for c in col_types.keys() if c != "created_at"]
        placeholders = ", ".join(f"${i + 1}" for i in range(len(cols)))
        conflict_cols = ", ".join(keys)
        update_cols = [c for c in cols if c not in keys]
        update_set = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols)
        sql = (
            f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders}) "
            f"ON CONFLICT ({conflict_cols}) "
            + (f"DO UPDATE SET {update_set}" if update_cols else "DO NOTHING")
        )

        upserted = 0
        failed = 0
        cursor = coll.find({}, {"_id": 0})
        batch: List[tuple] = []
        async for doc in cursor:
            try:
                row_tuple = tuple(
                    _coerce_for_pg(c, doc.get(c), col_types.get(c, "text"))
                    for c in cols
                )
                batch.append(row_tuple)
                if len(batch) >= 1000:
                    try:
                        await conn.executemany(sql, batch)
                        upserted += len(batch)
                    except Exception:
                        # Single-row fallback for the problematic batch.
                        for row in batch:
                            try:
                                await conn.execute(sql, *row)
                                upserted += 1
                            except Exception:
                                failed += 1
                    batch = []
            except Exception as e:  # noqa: BLE001
                failed += 1
                if failed < 5:
                    log.warning(f"  row build failed in {table}: {e}")
        if batch:
            try:
                await conn.executemany(sql, batch)
                upserted += len(batch)
            except Exception:
                for row in batch:
                    try:
                        await conn.execute(sql, *row)
                        upserted += 1
                    except Exception:
                        failed += 1

    return {"table": table, "rows": total, "upserted": upserted, "failed": failed,
            "ms": round((time.perf_counter() - t0) * 1000)}


async def _restore_holdings(pg_pool, coll, total: int) -> Dict[str, Any]:
    """Delete-then-insert restore for mutual_fund_holdings (no unique key)."""
    t0 = time.perf_counter()
    async with pg_pool.acquire() as conn:
        col_types = await _column_types(conn, "mutual_fund_holdings")
        # Exclude id (serial) + created_at (default) so PG assigns new ones.
        cols = [c for c in col_types.keys() if c not in ("id", "created_at")]
        placeholders = ", ".join(f"${i + 1}" for i in range(len(cols)))
        sql = f"INSERT INTO mutual_fund_holdings ({', '.join(cols)}) VALUES ({placeholders})"

        # Delete by the instrument_ids we're about to restore
        iids = await coll.distinct("instrument_id")
        if iids:
            import uuid
            iids_uuid = [uuid.UUID(str(x)) for x in iids]
            await conn.execute(
                "DELETE FROM mutual_fund_holdings WHERE instrument_id = ANY($1::uuid[])",
                iids_uuid,
            )

        upserted = 0
        failed = 0
        batch: List[tuple] = []
        async for doc in coll.find({}, {"_id": 0}):
            try:
                row = tuple(_coerce_for_pg(c, doc.get(c), col_types.get(c, "text")) for c in cols)
                batch.append(row)
                if len(batch) >= 1000:
                    await conn.executemany(sql, batch)
                    upserted += len(batch)
                    batch = []
            except Exception as e:  # noqa: BLE001
                failed += 1
                if failed < 3:
                    log.warning(f"  holdings row failed: {e}")
        if batch:
            await conn.executemany(sql, batch)
            upserted += len(batch)
    return {"table": "mutual_fund_holdings", "rows": total, "upserted": upserted,
            "failed": failed, "ms": round((time.perf_counter() - t0) * 1000)}


async def run(only: str | None = None) -> Dict[str, Any]:
    await _hydrate_secrets()
    from motor.motor_asyncio import AsyncIOMotorClient
    from services import pg_client

    mc = AsyncIOMotorClient(os.environ["MONGO_URL"])
    mongo_db = mc[os.environ["DB_NAME"]]
    pool = await pg_client.get_pool()
    if pool is None:
        raise RuntimeError("Postgres pool unavailable")

    # Restore in dependency-safe order.
    order = [
        "instrument_master", "benchmark_master",
        "mutual_fund_metadata", "mutual_fund_performance_ratios",
        "mutual_fund_holdings", "mutual_fund_nav_history",
        "mutual_fund_aum_history",
    ]
    if only:
        order = [t for t in order if t == only]

    results: List[Dict[str, Any]] = []
    t0 = time.perf_counter()
    for table in order:
        meta = await mongo_db["pg_mirror_meta"].find_one({"_id": table})
        keys = (meta or {}).get("keys") or ["instrument_id"]
        try:
            r = await _restore_one(pool, mongo_db, table, keys)
            results.append(r)
            log.info(f"  ✓ {table:<35} upserted={r.get('upserted', 0):>7}/{r.get('rows', 0)}  ms={r.get('ms', '-')}")
        except Exception as e:  # noqa: BLE001
            results.append({"table": table, "error": str(e)[:200]})
            log.error(f"  ✗ {table}: {e}")
    mc.close()
    total_ms = round((time.perf_counter() - t0) * 1000)
    ok = all("error" not in r for r in results)
    return {"status": "ok" if ok else "partial", "total_ms": total_ms, "tables": results}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", type=str, default=None, help="Restore a single table only")
    args = parser.parse_args()
    res = asyncio.run(run(only=args.only))
    log.info(f"Restore complete: {res['status']} in {res['total_ms']}ms")
