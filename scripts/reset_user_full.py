"""
Full reset for a single user across ALL portfolio surfaces.

Cleans:
  • MongoDB legacy V1/V2 collections (holdings, portfolios, analyses, caches…)
  • MongoDB auth sessions (logs the user out of every device)
  • MongoDB V4 CAS-ingest archive: portfolio_ingestion.pi_raw_parsed_data
  • Postgres V2: portfolio.user_holdings_snapshot, user_intelligence_snapshot
  • Postgres V4 CAS-ingest schema: portfolio_ingestion.{holdings, snapshots,
    ingestion_jobs, audit_log, users} — keyed by pan_hash derived from the
    user's PAN
  • Postgres nidp.validation_findings (if user-scoped)
  • Redis cache keys for the user
  • user_profiles flags back to onboarding-not-completed

Usage:
    python reset_user_full.py <email>

Env vars:
    MONGO_URL            - default mongodb://localhost:27017
    DB_NAME              - default test_database
    NIDP_POSTGRES_URL    - main app + NIDP postgres (V2 holdings)
    PI_POSTGRES_URL      - portfolio_ingestion schema postgres (V4 ingest)
                           [falls back to NIDP_POSTGRES_URL if unset]
    PI_MONGO_URL         - portfolio_ingestion mongo (V4 raw archive)
                           [falls back to MONGO_URL if unset]
    PI_MONGO_DB          - portfolio_ingestion mongo db name
                           [default "portfolio_ingestion"]
    REDIS_URL            - optional; skipped if unset
"""
import asyncio
import hashlib
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../backend"))

TARGET_EMAIL = sys.argv[1] if len(sys.argv) > 1 else "aporwal107@gmail.com"

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")
PG_URL = (
    os.environ.get("NIDP_POSTGRES_URL")
    or os.environ.get("POSTGRES_URL", "postgresql://nivesh:nivesh_local@localhost:5432/nivesh_dev")
)
# Portfolio-ingestion (V4 CAS pipeline) connections — default to the same
# Mongo cluster and a different DB; default to the same PG (we use a schema
# `portfolio_ingestion` inside it).
PI_PG_URL = os.environ.get("PI_POSTGRES_URL") or PG_URL
PI_MONGO_URL = os.environ.get("PI_MONGO_URL") or MONGO_URL
PI_MONGO_DB = os.environ.get("PI_MONGO_DB", "portfolio_ingestion")
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


def _pan_hash(pan: str) -> str:
    """Mirror portfolio_ingestion.services.checksum.pan_hash exactly:
    uppercase + strip, then SHA-256 hex. Must match what the API computed
    when it stored the user / snapshots / holdings."""
    return hashlib.sha256(pan.strip().upper().encode("utf-8")).hexdigest()


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

    # Sessions: log the user out of every device so the next /v4/ entry hits
    # the login screen with no stale token. Matches PRD V4 cold-start spec.
    try:
        sess = await db.user_sessions.delete_many({"user_id": user_id})
        if sess.deleted_count:
            print(f"  mongo user_sessions: deleted {sess.deleted_count}")
    except Exception as e:
        print(f"  mongo user_sessions: skip ({e})")

    await db.user_profiles.update_one(
        {"user_id": user_id},
        {"$set": RESET_PROFILE_FIELDS},
    )
    await db.users.update_one({"user_id": user_id}, {"$unset": {"cas_view_state": ""}})
    print(f"  mongo total deleted: {total}, profile reset done")
    client.close()


async def reset_pi_mongo(pan_hash: str | None):
    """Wipe the V4 CAS-ingest raw-payload archive for this user.

    Keyed by pan_hash (which is also the only stable user identifier the
    archive carries — there's no email/user_id stored there). If we don't
    have the PAN yet (e.g. user signed up but never uploaded), this is a
    no-op."""
    if not pan_hash:
        print("  pi mongo: no PAN known for user — nothing to delete")
        return
    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient(PI_MONGO_URL)
    try:
        db = client[PI_MONGO_DB]
        res = await db["pi_raw_parsed_data"].delete_many({"pan_hash": pan_hash})
        print(f"  pi mongo pi_raw_parsed_data: deleted {res.deleted_count}")
        # Diagnostic capture collection — not PAN-keyed reliably but small;
        # leave it alone (it's an admin tool, not user state).
    finally:
        client.close()


async def fetch_pi_pan_hash(external_user_id: str) -> str | None:
    """Look up the user's pan_hash in portfolio_ingestion.users via the
    `external_id` that maps to the host app's user_id. Returns None if the
    user has not yet uploaded a CAS via the V4 pipeline."""
    import asyncpg
    pg_url = PI_PG_URL.replace("postgresql://", "postgres://") if PI_PG_URL.startswith("postgresql://") else PI_PG_URL
    try:
        conn = await asyncpg.connect(pg_url)
    except Exception as e:
        print(f"  pi pg lookup: skip ({e})")
        return None
    try:
        row = await conn.fetchrow(
            "SELECT pan_hash FROM portfolio_ingestion.users WHERE external_id = $1",
            external_user_id,
        )
        return row["pan_hash"] if row else None
    finally:
        await conn.close()


async def reset_pi_pg(pan_hash: str | None):
    """Wipe portfolio_ingestion schema state for this PAN.

    Order matters because of FKs:
        holdings (FK→snapshots) → snapshots (FK→ingestion_jobs)
        → ingestion_jobs (FK→users) → audit_log → users
    """
    if not pan_hash:
        print("  pi pg: no PAN known for user — nothing to delete")
        return
    import asyncpg
    pg_url = PI_PG_URL.replace("postgresql://", "postgres://") if PI_PG_URL.startswith("postgresql://") else PI_PG_URL
    try:
        conn = await asyncpg.connect(pg_url)
    except Exception as e:
        print(f"  pi pg: skip ({e})")
        return
    try:
        n_h = await conn.fetchval(
            "WITH d AS (DELETE FROM portfolio_ingestion.holdings WHERE pan_hash = $1 RETURNING 1) "
            "SELECT count(*) FROM d", pan_hash) or 0
        n_s = await conn.fetchval(
            "WITH d AS (DELETE FROM portfolio_ingestion.snapshots WHERE pan_hash = $1 RETURNING 1) "
            "SELECT count(*) FROM d", pan_hash) or 0
        n_j = await conn.fetchval(
            "WITH d AS (DELETE FROM portfolio_ingestion.ingestion_jobs WHERE pan_hash = $1 RETURNING 1) "
            "SELECT count(*) FROM d", pan_hash) or 0
        # audit_log is append-only operationally but for a reset we want
        # zero trace; column is pan_hash NOT NULL on every event we write.
        try:
            n_a = await conn.fetchval(
                "WITH d AS (DELETE FROM portfolio_ingestion.audit_log WHERE pan_hash = $1 RETURNING 1) "
                "SELECT count(*) FROM d", pan_hash) or 0
            if n_a:
                print(f"  pi pg audit_log: deleted {n_a}")
        except Exception:
            pass
        n_u = await conn.fetchval(
            "WITH d AS (DELETE FROM portfolio_ingestion.users WHERE pan_hash = $1 RETURNING 1) "
            "SELECT count(*) FROM d", pan_hash) or 0
        print(f"  pi pg holdings: deleted {n_h}")
        print(f"  pi pg snapshots: deleted {n_s}")
        print(f"  pi pg ingestion_jobs: deleted {n_j}")
        print(f"  pi pg users: deleted {n_u}")
    finally:
        await conn.close()


async def reset_nidp_pg(email: str):
    """Best-effort cleanup of the legacy V2/NIDP Postgres tables.

    Staging may not have the V2 `portfolio.*` schema (V4 deployments run
    only the `portfolio_ingestion` schema), so every statement is wrapped
    individually — a missing table is logged and skipped, not fatal."""
    import asyncpg
    pg_url = PG_URL.replace("postgresql://", "postgres://") if PG_URL.startswith("postgresql://") else PG_URL
    try:
        conn = await asyncpg.connect(pg_url)
    except Exception as e:
        print(f"  nidp pg: connect failed, skipping ({e})")
        return
    try:
        # Each delete in its own savepoint-style try so one missing schema
        # doesn't poison the whole transaction.
        for label, sql in [
            ("portfolio.user_intelligence_snapshot",
             "WITH d AS (DELETE FROM portfolio.user_intelligence_snapshot WHERE external_user_id = $1 RETURNING 1) SELECT count(*) FROM d"),
            ("portfolio.user_holdings_snapshot (+security_map cascade)",
             "WITH d AS (DELETE FROM portfolio.user_holdings_snapshot WHERE external_user_id = $1 RETURNING 1) SELECT count(*) FROM d"),
            ("nidp.validation_findings",
             "WITH d AS (DELETE FROM nidp.validation_findings WHERE external_user_id = $1 RETURNING 1) SELECT count(*) FROM d"),
        ]:
            try:
                n = await conn.fetchval(sql, email) or 0
                print(f"  pg {label}: deleted {n}")
            except asyncpg.UndefinedTableError:
                print(f"  pg {label}: table missing (V4-only deployment), skipping")
            except asyncpg.UndefinedColumnError as e:
                print(f"  pg {label}: column missing, skipping ({e})")
            except Exception as e:
                print(f"  pg {label}: skip ({type(e).__name__}: {e})")
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
    user = await db.users.find_one(
        {"email": TARGET_EMAIL},
        {"_id": 0, "user_id": 1, "name": 1, "pan": 1, "kyc_pan": 1},
    )
    client.close()

    if not user:
        print(f"ERROR: no user found with email {TARGET_EMAIL}")
        sys.exit(1)

    user_id = user["user_id"]
    # PAN may live on the user doc itself in newer flows, or only in
    # portfolio_ingestion.users for V4. Try both.
    pan_from_user = user.get("pan") or user.get("kyc_pan")

    print(f"\nResetting: {TARGET_EMAIL} (user_id={user_id})\n")

    # Look up pan_hash from the V4 ingest schema first; fall back to
    # hashing whatever PAN the user doc itself carries.
    pi_pan_hash = await fetch_pi_pan_hash(user_id)
    if not pi_pan_hash and pan_from_user:
        pi_pan_hash = _pan_hash(pan_from_user)
        print(f"  (derived pan_hash from user.pan: {pi_pan_hash[:12]}…)")
    if pi_pan_hash:
        print(f"  PAN hash for V4 cleanup: {pi_pan_hash[:12]}…")

    print("\n[1/5] MongoDB (legacy V1/V2 + sessions) reset...")
    await reset_mongo(user_id)

    print("\n[2/5] Mongo portfolio_ingestion (V4 raw archive) reset...")
    await reset_pi_mongo(pi_pan_hash)

    print("\n[3/5] Postgres portfolio_ingestion (V4 holdings/snapshots/jobs) reset...")
    await reset_pi_pg(pi_pan_hash)

    print("\n[4/5] NIDP PostgreSQL (V2 snapshots) reset...")
    await reset_nidp_pg(TARGET_EMAIL)

    print("\n[5/5] Redis cache flush...")
    await reset_redis(user_id)

    print(f"\nDone. {TARGET_EMAIL} is clean — ready for fresh CAS upload.")


if __name__ == "__main__":
    asyncio.run(main())
