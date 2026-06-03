#!/usr/bin/env python3
"""Post-deploy cache clear — run inside the backend container via docker exec.

Deletes all rows from:
  - MongoDB  fund_performance_cache  (mfapi.in-based rankings)
  - Postgres portfolio_performance_cache  (XIRR / waterfall / contributors)

Called by GitHub Actions after every successful backend deploy so users always
see data computed with the deployed code, not a previous version's cached output.
"""
import asyncio
import os
import sys


async def clear() -> None:
    results: dict = {}

    mongo_uri = os.environ.get("MONGODB_URL", "")
    pg_dsn    = os.environ.get("DATABASE_URL", "")
    db_name   = os.environ.get("MONGO_DB_NAME", "nivesh")

    if mongo_uri:
        try:
            from motor.motor_asyncio import AsyncIOMotorClient
            client = AsyncIOMotorClient(mongo_uri)
            r = await client[db_name].fund_performance_cache.delete_many({})
            results["mongo_fund_performance_cache"] = r.deleted_count
            client.close()
        except Exception as e:
            results["mongo_error"] = str(e)

    if pg_dsn:
        try:
            import asyncpg
            conn = await asyncpg.connect(pg_dsn)
            status = await conn.execute("DELETE FROM portfolio_performance_cache")
            results["pg_portfolio_performance_cache"] = int(status.split()[-1])
            await conn.close()
        except Exception as e:
            results["pg_error"] = str(e)

    print("cache clear:", results)
    if "mongo_error" in results or "pg_error" in results:
        sys.exit(1)


asyncio.run(clear())
