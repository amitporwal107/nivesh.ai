"""
Restore PostgreSQL MF data from the MongoDB `fund_holdings_cache` mirror.

MongoDB is persistent across forks; PostgreSQL is wiped on fork. This script
replays every cached scrape payload into PG so users don't have to re-scrape
from Groww. Run it once after PG is initialized (e.g. from restore_datastores.sh).

Idempotent — uses `persist_scrape` which is upsert-based.

Usage:
    cd /app/backend && python -m scripts.restore_pg_from_mongo

Environment (from backend/.env):
    MONGO_URL       (required)
    DB_NAME         (required)
    POSTGRES_URL    (required)
"""
from __future__ import annotations
import asyncio
import logging
import os
import sys
from pathlib import Path

# Ensure the backend root is importable when invoked via `python scripts/xxx.py`
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from dotenv import load_dotenv

load_dotenv(BACKEND_ROOT / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("pg_restore")

# Silence asyncpg notice chatter during bulk upsert
logging.getLogger("asyncpg").setLevel(logging.WARNING)


async def _restore_all() -> dict:
    from motor.motor_asyncio import AsyncIOMotorClient
    from services import pg_client
    from services.pg_writer import persist_scrape
    from helpers import secrets as _secrets

    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME") or "test_database"

    if not mongo_url:
        logger.error("MONGO_URL not set — aborting")
        return {"ok": False, "reason": "no_mongo_url"}

    logger.info("Connecting to Mongo db=%s", db_name)
    client = AsyncIOMotorClient(mongo_url, serverSelectionTimeoutMS=5000)
    db = client[db_name]

    # Hydrate admin-managed secrets (POSTGRES_URL, REDIS_URL) from Mongo
    await _secrets.hydrate_from_db(db)
    pg_url = _secrets.get("POSTGRES_URL")
    if not pg_url:
        logger.error("POSTGRES_URL not configured (env or system_config.secrets) — aborting")
        return {"ok": False, "reason": "no_pg_url"}

    # Confirm PG pool is reachable before hammering it
    pool = await pg_client.get_pool()
    if pool is None:
        logger.error("PG pool unavailable — aborting restore")
        return {"ok": False, "reason": "pg_pool_unavailable"}

    total = await db.fund_holdings_cache.count_documents({})
    logger.info("Found %s cached scrape payloads in fund_holdings_cache", total)
    if total == 0:
        logger.info("Nothing to restore. Exiting.")
        return {"ok": True, "restored": 0, "failed": 0, "skipped": 0}

    restored, failed, skipped = 0, 0, 0
    cursor = db.fund_holdings_cache.find({}, {"_id": 0})
    async for doc in cursor:
        scheme_name = doc.get("scheme_name") or doc.get("metadata", {}).get("scheme_name") or "?"
        if not doc.get("valid", True):
            logger.debug("SKIP invalid scrape: %s", scheme_name)
            skipped += 1
            continue
        try:
            mf_id = await persist_scrape(doc)
            if mf_id:
                restored += 1
                if restored % 10 == 0:
                    logger.info("  …restored %s/%s", restored, total)
            else:
                failed += 1
                logger.warning("persist_scrape returned None for %s", scheme_name[:60])
        except Exception as e:
            failed += 1
            logger.warning("FAIL %s: %s", scheme_name[:60], e)

    logger.info(
        f"Restore complete: {restored} restored, {failed} failed, {skipped} skipped "
        f"(total {total})"
    )
    # Close connections
    try:
        client.close()
    except Exception:
        pass
    return {"ok": True, "restored": restored, "failed": failed, "skipped": skipped}


def main() -> int:
    try:
        result = asyncio.run(_restore_all())
    except KeyboardInterrupt:
        logger.warning("Interrupted by user")
        return 130
    except Exception as e:
        logger.exception("Unhandled failure: %s", e)
        return 1
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    sys.exit(main())
