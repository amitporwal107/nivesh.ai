"""Post-deployment migration orchestrator.

Single source-of-truth for the 7-phase sequence that gets a fresh Postgres
(e.g. a freshly-provisioned production Neon database) fully hydrated with all
master + V3 primitive + analytics data, seamlessly carried over from
Mongo-mirror snapshots taken in the preview environment.

Sequence (each phase is idempotent and safe to re-run):

  Phase 0  hydrate secrets from Mongo system_config
  Phase 1  health-check Postgres + Mongo + Redis
  Phase 2  apply ALL PG migrations (001…006) in order
  Phase 3  restore PG master+analytics from `pg_mirror_*` Mongo collections
           (instrument_master, benchmark_master, mutual_fund_metadata,
            mutual_fund_performance_ratios, mutual_fund_holdings,
            mutual_fund_nav_history, mutual_fund_aum_history)
  Phase 4  replay `fund_holdings_cache` → PG (historic scrapes)
  Phase 5  analytics sweep (consistency / drawdown / downside capture)
  Phase 6  invalidate Redis V3 cache + full V3 rescore
  Phase 7  smoke test (count funds + primitives + scored rows)

CLI:
    cd /app/backend && python -m scripts.post_deploy_migrate [--skip-sweep]
                                                            [--skip-rescore]
"""
from __future__ import annotations
import argparse
import asyncio
import glob
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from dotenv import load_dotenv  # noqa: E402
load_dotenv(BACKEND_ROOT / ".env")

log = logging.getLogger("post_deploy")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

MIGRATIONS_DIR = BACKEND_ROOT / "migrations"


# ── Phase 0 ────────────────────────────────────────────────────────────
async def phase_hydrate_secrets() -> Dict[str, Any]:
    from motor.motor_asyncio import AsyncIOMotorClient
    from helpers import secrets as _s
    mc = AsyncIOMotorClient(os.environ["MONGO_URL"])
    try:
        await _s.hydrate_from_db(mc[os.environ["DB_NAME"]])
    finally:
        mc.close()
    pg_url = _s.get("POSTGRES_URL")
    redis_url = _s.get("REDIS_URL")
    if not pg_url:
        raise RuntimeError("POSTGRES_URL missing from hydrated secrets")
    os.environ["POSTGRES_URL"] = pg_url
    if redis_url:
        os.environ["REDIS_URL"] = redis_url
    return {"pg_url_set": bool(pg_url), "redis_url_set": bool(redis_url)}


# ── Phase 1 ────────────────────────────────────────────────────────────
async def phase_health_check() -> Dict[str, Any]:
    from motor.motor_asyncio import AsyncIOMotorClient
    out: Dict[str, Any] = {}

    # Mongo
    try:
        mc = AsyncIOMotorClient(os.environ["MONGO_URL"], serverSelectionTimeoutMS=5000)
        await mc.admin.command("ping")
        out["mongo"] = "ok"
        mc.close()
    except Exception as e:  # noqa: BLE001
        out["mongo"] = f"err:{e}"

    # Postgres
    try:
        from services import pg_client
        pool = await pg_client.get_pool()
        if pool is None:
            out["postgres"] = "err:pool_unavailable"
        else:
            async with pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            out["postgres"] = "ok"
    except Exception as e:  # noqa: BLE001
        out["postgres"] = f"err:{str(e)[:150]}"

    # Redis (optional — cache-only)
    try:
        from services import v3_score_cache
        stats = await v3_score_cache.get_stats()
        out["redis"] = "ok" if stats.get("configured") else "not_configured"
    except Exception as e:  # noqa: BLE001
        out["redis"] = f"err:{str(e)[:150]}"
    return out


# ── Phase 2 ────────────────────────────────────────────────────────────
async def phase_apply_migrations() -> Dict[str, Any]:
    """Apply all *.sql migrations in filename order. Uses asyncpg so no
    external psql binary is required (works on Neon + local)."""
    from services import pg_client
    pool = await pg_client.get_pool()
    if pool is None:
        return {"status": "err", "reason": "pg_pool_unavailable"}

    files = sorted(glob.glob(str(MIGRATIONS_DIR / "*.sql")))
    applied: List[Dict[str, Any]] = []
    async with pool.acquire() as conn:
        # Track applied migrations
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "  filename TEXT PRIMARY KEY,"
            "  applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()"
            ")"
        )
        for f in files:
            name = os.path.basename(f)
            existing = await conn.fetchval(
                "SELECT 1 FROM schema_migrations WHERE filename = $1", name,
            )
            if existing:
                applied.append({"file": name, "status": "already_applied"})
                continue
            sql = Path(f).read_text()
            try:
                async with conn.transaction():
                    await conn.execute(sql)
                    await conn.execute(
                        "INSERT INTO schema_migrations (filename) VALUES ($1) "
                        "ON CONFLICT (filename) DO NOTHING",
                        name,
                    )
                applied.append({"file": name, "status": "applied"})
                log.info(f"  ✓ migration {name}")
            except Exception as e:  # noqa: BLE001
                # Migration files here have been manually run before this
                # tracking table existed — they're known idempotent so we can
                # mark them as applied on first-run failure due to duplicate
                # objects. Only swallow the duplicate-type errors.
                msg = str(e)
                if any(tok in msg.lower() for tok in (
                    "already exists", "duplicate column", "duplicate key",
                )):
                    await conn.execute(
                        "INSERT INTO schema_migrations (filename) VALUES ($1) "
                        "ON CONFLICT (filename) DO NOTHING",
                        name,
                    )
                    applied.append({"file": name, "status": "marked_applied"})
                    log.info(f"  ↺ migration {name} (already in DB — marked applied)")
                else:
                    applied.append({"file": name, "status": "error", "error": msg[:300]})
                    log.error(f"  ✗ migration {name}: {msg[:200]}")
                    raise
    return {"status": "ok", "applied": applied}


# ── Phase 3 ────────────────────────────────────────────────────────────
async def phase_restore_from_mirrors() -> Dict[str, Any]:
    from scripts import restore_pg_from_mirrors as rm
    return await rm.run()


# ── Phase 4 ────────────────────────────────────────────────────────────
async def phase_replay_fund_holdings_cache() -> Dict[str, Any]:
    from scripts import restore_pg_from_mongo as rpm
    return await rpm._restore_all()


# ── Phase 5 ────────────────────────────────────────────────────────────
async def phase_analytics_sweep() -> Dict[str, Any]:
    from services.nav_analytics_sweep import run_analytics_sweep
    return await run_analytics_sweep()


# ── Phase 6 ────────────────────────────────────────────────────────────
async def phase_v3_rescore() -> Dict[str, Any]:
    from services import v3_score_cache
    from services.nav_analytics_sweep import run_v3_rescore
    try:
        n = await v3_score_cache.invalidate_all()
    except Exception as e:  # noqa: BLE001
        n = f"skip:{e}"
    res = await run_v3_rescore()
    return {"cache_invalidated": n, "rescore": res}


# ── Phase 7 ────────────────────────────────────────────────────────────
async def phase_smoke_check() -> Dict[str, Any]:
    from services import pg_client
    pool = await pg_client.get_pool()
    if pool is None:
        return {"status": "err", "reason": "pg_pool_unavailable"}
    async with pool.acquire() as conn:
        counts = {
            "instruments": await conn.fetchval("SELECT COUNT(*) FROM instrument_master"),
            "mf_metadata": await conn.fetchval("SELECT COUNT(*) FROM mutual_fund_metadata"),
            "mf_nav_history": await conn.fetchval("SELECT COUNT(*) FROM mutual_fund_nav_history"),
            "mf_performance_ratios": await conn.fetchval("SELECT COUNT(*) FROM mutual_fund_performance_ratios"),
            "mf_scored": await conn.fetchval(
                "SELECT COUNT(*) FROM mutual_fund_metadata WHERE quality_score IS NOT NULL"
            ),
            "benchmark_master": await conn.fetchval("SELECT COUNT(*) FROM benchmark_master"),
            "mc_debt_enriched": await conn.fetchval(
                "SELECT COUNT(*) FROM mutual_fund_metadata WHERE moneycontrol_imid IS NOT NULL"
            ),
        }
    return {"status": "ok", "counts": counts}


# ── Orchestrator ───────────────────────────────────────────────────────
PHASES = [
    ("0_hydrate_secrets", phase_hydrate_secrets, False),
    ("1_health_check",    phase_health_check,    False),
    ("2_apply_migrations", phase_apply_migrations, False),
    ("3_restore_mirrors",  phase_restore_from_mirrors, False),
    # Phase 4 is redundant once Phase 3 has finished unless fund_holdings_cache
    # has scrapes taken _after_ the last mirror snapshot. Skip-able via flag.
    ("4_replay_scrape_cache", phase_replay_fund_holdings_cache, True),
    ("5_analytics_sweep",  phase_analytics_sweep, True),
    ("6_v3_rescore",       phase_v3_rescore,      True),
    ("7_smoke_check",      phase_smoke_check,     False),
]


async def run_all(skip: List[str] | None = None) -> Dict[str, Any]:
    skip = skip or []
    summary: Dict[str, Any] = {"started_at": time.time(), "phases": []}
    for name, fn, skippable in PHASES:
        phase_key = name.split("_", 1)[1]
        if skippable and phase_key in skip:
            summary["phases"].append({"name": name, "status": "skipped"})
            log.info(f"⏭  {name} (skipped by flag)")
            continue
        log.info(f"▶  {name}")
        t0 = time.perf_counter()
        try:
            res = await fn()
            summary["phases"].append({
                "name": name, "status": "ok", "ms": round((time.perf_counter() - t0) * 1000),
                "result": res,
            })
            log.info(f"✓ {name} ({round((time.perf_counter() - t0) * 1000)}ms)")
        except Exception as e:  # noqa: BLE001
            summary["phases"].append({"name": name, "status": "error", "error": str(e)[:400]})
            log.error(f"✗ {name}: {e}")
            summary["overall"] = "error"
            summary["duration_ms"] = round((time.perf_counter() - t0) * 1000)
            return summary
    summary["overall"] = "ok"
    summary["duration_ms"] = round((time.time() - summary["started_at"]) * 1000)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-replay",  dest="skip", action="append_const", const="replay_scrape_cache")
    parser.add_argument("--skip-sweep",   dest="skip", action="append_const", const="analytics_sweep")
    parser.add_argument("--skip-rescore", dest="skip", action="append_const", const="v3_rescore")
    args = parser.parse_args()
    out = asyncio.run(run_all(skip=args.skip or []))
    log.info(f"POST-DEPLOY {out['overall'].upper()} in {out.get('duration_ms')}ms")
    if out["overall"] != "ok":
        sys.exit(1)
