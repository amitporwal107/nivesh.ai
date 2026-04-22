"""Mirror PG master + analytics tables → Mongo (`pg_mirror_*` collections).

MongoDB is the persistent source-of-truth across forks/deploys. This script
snapshots the critical Postgres tables (master list + V3 primitives + NAV
history + performance ratios + benchmark master + latest holdings) into Mongo
mirror collections so production deployments can seamlessly restore a fresh
Postgres without having to re-run AMFI backfill, Groww scrapes, or Moneycontrol
imports.

Run schedule: weekly (or on-demand from Admin UI). The restore counterpart is
`scripts.restore_pg_from_mirrors`.

Usage:
    cd /app/backend && python -m scripts.mirror_pg_to_mongo [--dry-run]
"""
from __future__ import annotations
import argparse
import asyncio
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from dotenv import load_dotenv  # noqa: E402
load_dotenv(BACKEND_ROOT / ".env")

log = logging.getLogger("mirror_pg_to_mongo")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


# Tables to mirror. Each entry:
#   pg_table  → Mongo collection name (`pg_mirror_<table>`)
#   keys      → natural-key fields used for idempotent upsert on restore
#   projection (optional) → SQL WHERE clause to bound history tables
_MIRROR_SPEC: List[Dict[str, Any]] = [
    {"pg_table": "instrument_master",
     "keys": ["instrument_id"]},
    {"pg_table": "benchmark_master",
     "keys": ["category"]},
    {"pg_table": "mutual_fund_metadata",
     "keys": ["instrument_id"]},
    {"pg_table": "mutual_fund_performance_ratios",
     "keys": ["instrument_id", "ratios_date"]},
    {"pg_table": "mutual_fund_holdings",
     "keys": ["instrument_id", "holding_stock_slug", "holding_date"],
     # Latest snapshot only (keeps Mongo lean; holdings change infrequently).
     "where": "holding_date >= CURRENT_DATE - INTERVAL '180 days'"},
    {"pg_table": "mutual_fund_nav_history",
     "keys": ["instrument_id", "nav_date"],
     # Last 5 years — enough for V3 consistency/drawdown primitives.
     "where": "nav_date >= CURRENT_DATE - INTERVAL '5 years'"},
    {"pg_table": "mutual_fund_aum_history",
     "keys": ["instrument_id", "snapshot_date"]},
]


def _serialise_row(row) -> Dict[str, Any]:
    """Convert asyncpg row → JSON-serialisable dict for Mongo."""
    import uuid
    out: Dict[str, Any] = {}
    for k, v in dict(row).items():
        if isinstance(v, uuid.UUID):
            out[k] = str(v)
        elif isinstance(v, datetime):
            out[k] = v.replace(tzinfo=timezone.utc).isoformat() if v.tzinfo is None else v.isoformat()
        elif hasattr(v, "isoformat"):  # date
            out[k] = v.isoformat()
        elif hasattr(v, "__float__") and not isinstance(v, (int, float, bool)):
            try:
                out[k] = float(v)
            except (TypeError, ValueError):
                out[k] = str(v)
        else:
            out[k] = v
    return out


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


async def _mirror_one(conn, mongo_db, spec: Dict[str, Any], dry_run: bool) -> Dict[str, Any]:
    pg_table = spec["pg_table"]
    coll_name = f"pg_mirror_{pg_table}"
    where = spec.get("where")
    sql = f"SELECT * FROM {pg_table}" + (f" WHERE {where}" if where else "")
    t0 = time.perf_counter()
    rows = await conn.fetch(sql)
    docs = [_serialise_row(r) for r in rows]
    if dry_run:
        return {"table": pg_table, "rows": len(docs), "written": 0, "dry_run": True,
                "ms": round((time.perf_counter() - t0) * 1000)}

    coll = mongo_db[coll_name]
    # Full replace (simpler + deterministic for master data)
    await coll.drop()
    written = 0
    if docs:
        # Batch-insert in 5k chunks
        for i in range(0, len(docs), 5000):
            batch = docs[i:i + 5000]
            await coll.insert_many(batch, ordered=False)
            written += len(batch)
    # Record metadata
    await mongo_db["pg_mirror_meta"].update_one(
        {"_id": pg_table},
        {"$set": {
            "rows": len(docs),
            "keys": spec.get("keys", []),
            "mirrored_at": datetime.now(timezone.utc),
            "ms": round((time.perf_counter() - t0) * 1000),
        }},
        upsert=True,
    )
    return {"table": pg_table, "rows": len(docs), "written": written,
            "ms": round((time.perf_counter() - t0) * 1000)}


async def run(dry_run: bool = False) -> Dict[str, Any]:
    await _hydrate_secrets()
    from motor.motor_asyncio import AsyncIOMotorClient
    from services import pg_client

    mc = AsyncIOMotorClient(os.environ["MONGO_URL"])
    mongo_db = mc[os.environ["DB_NAME"]]
    pool = await pg_client.get_pool()
    if pool is None:
        raise RuntimeError("Postgres pool unavailable")

    results: List[Dict[str, Any]] = []
    t0 = time.perf_counter()
    async with pool.acquire() as conn:
        for spec in _MIRROR_SPEC:
            try:
                r = await _mirror_one(conn, mongo_db, spec, dry_run)
                log.info(f"  ✓ {r['table']:<35} rows={r['rows']:>7}  ms={r['ms']}")
                results.append(r)
            except Exception as e:  # noqa: BLE001
                log.error(f"  ✗ {spec['pg_table']:<35} FAILED: {e}")
                results.append({"table": spec["pg_table"], "error": str(e)[:200]})
    mc.close()
    total_rows = sum(r.get("rows", 0) for r in results)
    total_ms = round((time.perf_counter() - t0) * 1000)
    return {"status": "ok" if all("error" not in r for r in results) else "partial",
            "total_rows": total_rows, "total_ms": total_ms, "tables": results,
            "dry_run": dry_run}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    res = asyncio.run(run(dry_run=args.dry_run))
    log.info(f"Mirror complete: {res['status']} — {res['total_rows']} rows in {res['total_ms']}ms")
