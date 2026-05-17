"""
Full reset for a single user: MongoDB portfolio data + NIDP PostgreSQL + Redis.
Usage: python reset_user_full.py <email>
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../backend"))

TARGET_EMAIL = sys.argv[1] if len(sys.argv) > 1 else "aporwal107@gmail.com"

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")
PG_URL = os.environ.get("NIDP_POSTGRES_URL") or os.environ.get("POSTGRES_URL", "postgresql://nivesh:nivesh_local@localhost:5432/nivesh_dev")
REDIS_URL = os.environ.get("REDIS_URL", "")

RESET_COLLECTIONS = [
    "holdings", "portfolios", "portfolio_analysis", "portfolio_analysis_deep",
    "portfolio_snapshots", "portfolio_holdings", "ai_insights", "action_plans",
    "pending_actions", "cas_parsed_responses", "cas_transactions", "detected_sips",
    "saved_scenarios", "scenario_simulations", "upload_tasks", "chat_sessions",
    "chat_messages", "copilot_cache", "allocation_analysis_cache",
    "fund_performance_cache", "mfd_profile_signal_cache", "gmail_imports",
    "capital_gains_summary", "international_funds_cache", "fund_holdings_cache",
]

RESET_PROFILE_FIELDS = {
    "onboarding_completed": False, "journey_type": None,
    "risk_profile": None, "playbook": None, "goals": [], "selected_sources": [],
}


async def reset_mongo(user_id: str):
    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]

    total = 0
    for col in RESET_COLLECTIONS:
        try:
            res = await db[col].delete_many({"user_id": user_id})
            if res.deleted_count:
                print(f"  mongo {col}: deleted {res.deleted_count}")
            total += res.deleted_count
        except Exception as e:
            print(f"  mongo {col}: skip ({e})")

    await db.user_profiles.update_one(
        {"user_id": user_id},
        {"$set": RESET_PROFILE_FIELDS},
    )
    await db.users.update_one({"user_id": user_id}, {"$unset": {"cas_view_state": ""}})
    print(f"  mongo total deleted: {total}, profile reset done")
    client.close()


async def reset_nidp_pg(email: str):
    import asyncpg
    pg_url = PG_URL.replace("postgresql://", "postgres://") if PG_URL.startswith("postgresql://") else PG_URL
    conn = await asyncpg.connect(pg_url)
    try:
        # user_intelligence_snapshot
        n1 = await conn.fetchval(
            "DELETE FROM portfolio.user_intelligence_snapshot WHERE external_user_id = $1 RETURNING count(*)",
            email,
        ) or 0
        # user_holdings_snapshot cascades to holding_security_map
        n2 = await conn.fetchval(
            "WITH deleted AS (DELETE FROM portfolio.user_holdings_snapshot WHERE external_user_id = $1 RETURNING 1) SELECT count(*) FROM deleted",
            email,
        ) or 0
        # Also clear any nidp.validation_findings or job data if user-scoped
        try:
            n3 = await conn.fetchval(
                "WITH deleted AS (DELETE FROM nidp.validation_findings WHERE external_user_id = $1 RETURNING 1) SELECT count(*) FROM deleted",
                email,
            ) or 0
            if n3:
                print(f"  pg nidp.validation_findings: deleted {n3}")
        except Exception:
            pass
        print(f"  pg user_intelligence_snapshot: deleted {n1}")
        print(f"  pg user_holdings_snapshot (+security_map cascade): deleted {n2}")
    finally:
        await conn.close()


async def reset_redis(user_id: str):
    if not REDIS_URL:
        print("  redis: REDIS_URL not set, skipping")
        return
    try:
        import redis.asyncio as aioredis
        rc = aioredis.from_url(REDIS_URL)
        patterns = [
            f"snap:*:{user_id}", f"score:user:{user_id}*",
            f"v3:user:{user_id}*", f"actionplan:{user_id}*", f"copilot:{user_id}*",
        ]
        total = 0
        for pat in patterns:
            cursor = 0
            while True:
                cursor, keys = await rc.scan(cursor=cursor, match=pat, count=200)
                if keys:
                    await rc.delete(*keys)
                    total += len(keys)
                if cursor == 0:
                    break
        await rc.aclose()
        print(f"  redis: cleared {total} keys")
    except Exception as e:
        print(f"  redis: skip ({e})")


async def main():
    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]
    user = await db.users.find_one({"email": TARGET_EMAIL}, {"_id": 0, "user_id": 1, "name": 1})
    client.close()

    if not user:
        print(f"ERROR: no user found with email {TARGET_EMAIL}")
        sys.exit(1)

    user_id = user["user_id"]
    print(f"\nResetting: {TARGET_EMAIL} (user_id={user_id})\n")

    print("[1/3] MongoDB reset...")
    await reset_mongo(user_id)

    print("\n[2/3] NIDP PostgreSQL reset...")
    await reset_nidp_pg(TARGET_EMAIL)

    print("\n[3/3] Redis cache flush...")
    await reset_redis(user_id)

    print(f"\nDone. {TARGET_EMAIL} is clean — ready for fresh CAS upload.")


if __name__ == "__main__":
    asyncio.run(main())
