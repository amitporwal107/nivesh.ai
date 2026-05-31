"""Clear per-user performance caches.

Run via:
    docker exec nivesh-backend python -m scripts.clear_performance_caches

Clears:
  - MongoDB  fund_performance_cache  (mfapi.in / DaaS fund rankings)
  - Postgres portfolio_performance_cache  (XIRR, waterfall, contributors)

Called automatically by GitHub Actions after every backend deploy so users
always see data computed by the deployed code, not a previous version.
Also run nightly by /etc/cron.d/nivesh-cache-clear to prevent stale data
accumulating when no deploy has occurred.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("clear_performance_caches")


async def clear() -> dict:
    results: dict = {}

    mongo_uri = os.environ.get("MONGO_URL") or os.environ.get("MONGODB_URL", "")
    pg_dsn    = os.environ.get("DATABASE_URL", "")
    # db name embedded in URI after last slash, before any query string
    db_name   = os.environ.get("MONGO_DB_NAME") or (
        mongo_uri.rsplit("/", 1)[-1].split("?")[0] if mongo_uri else "nivesh"
    )

    if mongo_uri:
        try:
            from motor.motor_asyncio import AsyncIOMotorClient
            client = AsyncIOMotorClient(mongo_uri)
            r1 = await client[db_name].fund_performance_cache.delete_many({})
            r2 = await client[db_name].portfolio_analytics_cache.delete_many({})
            results["mongo_fund_performance_cache"] = r1.deleted_count
            results["mongo_portfolio_analytics_cache"] = r2.deleted_count
            client.close()
            logger.info("mongo fund_performance_cache cleared: %d docs", r1.deleted_count)
            logger.info("mongo portfolio_analytics_cache cleared: %d docs", r2.deleted_count)
        except Exception as e:
            results["mongo_error"] = str(e)
            logger.error("mongo clear failed: %s", e)
    else:
        results["mongo_skipped"] = "MONGODB_URL not set"
        logger.warning("MONGODB_URL not set — skipping mongo clear")

    if pg_dsn:
        try:
            import asyncpg
            conn = await asyncpg.connect(pg_dsn)
            status = await conn.execute("DELETE FROM portfolio_performance_cache")
            deleted = int(status.split()[-1])
            results["pg_portfolio_performance_cache"] = deleted
            await conn.close()
            logger.info("pg portfolio_performance_cache cleared: %d rows", deleted)
        except Exception as e:
            results["pg_error"] = str(e)
            logger.error("pg clear failed: %s", e)
    else:
        results["pg_skipped"] = "DATABASE_URL not set"
        logger.warning("DATABASE_URL not set — skipping pg clear")

    return results


if __name__ == "__main__":
    results = asyncio.run(clear())
    has_error = any(k.endswith("_error") for k in results)
    print("result:", results)
    sys.exit(1 if has_error else 0)
