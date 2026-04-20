"""Admin routes for datastore (Postgres/Redis) control + Groww bootstrap.

All endpoints require admin privilege. Shell commands are invoked via subprocess
with a hard timeout to prevent the API from hanging.
"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request

from deps import db, require_admin

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

# Services the admin may control. We whitelist to avoid arbitrary-command risks.
_ALLOWED_SERVICES = {"postgres", "redis"}
_ALLOWED_ACTIONS = {"start", "stop", "restart", "status"}
_SUPERVISORCTL = "sudo supervisorctl"


async def _run_cmd(cmd: str, timeout: int = 30) -> Dict[str, Any]:
    """Run a shell command with a timeout; capture stdout/stderr."""
    loop = asyncio.get_event_loop()
    try:
        result = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda: subprocess.run(
                    cmd, shell=True, capture_output=True, text=True, timeout=timeout,
                ),
            ),
            timeout=timeout + 5,
        )
        return {
            "ok": result.returncode == 0,
            "stdout": (result.stdout or "").strip(),
            "stderr": (result.stderr or "").strip(),
            "returncode": result.returncode,
        }
    except asyncio.TimeoutError:
        return {"ok": False, "stdout": "", "stderr": "command timed out", "returncode": -1}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "stdout": "", "stderr": str(e), "returncode": -1}


@router.get("/admin/datastores/status")
async def datastore_status(request: Request) -> Dict[str, Any]:
    """Return service status + data counts for Postgres and Redis."""
    await require_admin(request)

    # Supervisor status for postgres + redis
    sup_result = await _run_cmd(f"{_SUPERVISORCTL} status postgres redis")
    svc_status: Dict[str, str] = {}
    for line in sup_result.get("stdout", "").splitlines():
        parts = line.split()
        if len(parts) >= 2:
            svc_status[parts[0]] = parts[1]

    # Postgres data counts (best-effort)
    pg_counts: Dict[str, Any] = {}
    try:
        from services import pg_client
        pool = await pg_client.get_pool()
        if pool:
            async with pool.acquire() as conn:
                for (tbl, key) in [
                    ("instrument_master", "instruments"),
                    ("mutual_fund_holdings", "mf_holdings"),
                    ("mutual_fund_metadata", "mf_metadata"),
                    ("mutual_fund_performance_ratios", "mf_ratios"),
                    ("scrape_audit_log", "scrape_logs"),
                ]:
                    try:
                        row = await conn.fetchrow(f"SELECT COUNT(*) AS c FROM {tbl}")
                        pg_counts[key] = row["c"] if row else 0
                    except Exception:
                        pg_counts[key] = None
    except Exception as e:
        logger.debug(f"pg_counts failed: {e}")

    # Redis key count + sample
    redis_info: Dict[str, Any] = {"configured": False}
    try:
        from services.redis_client import get_client as get_redis
        r = await get_redis()
        if r is not None:
            redis_info["configured"] = True
            try:
                redis_info["dbsize"] = await r.dbsize()
                groww_keys = await r.keys("groww:*")
                redis_info["groww_fundamentals_cached"] = len(groww_keys)
            except Exception as e:
                redis_info["error"] = str(e)
    except Exception as e:
        redis_info["error"] = str(e)

    # MongoDB mirror stats (source of truth for PG restore)
    mongo_mirror: Dict[str, Any] = {}
    try:
        mongo_mirror["fund_holdings_cache"] = await db.fund_holdings_cache.count_documents({})
        mongo_mirror["fund_performance_cache"] = await db.fund_performance_cache.count_documents({})
    except Exception as e:
        mongo_mirror["error"] = str(e)

    return {
        "postgres": {
            "supervisor_status": svc_status.get("postgres", "UNKNOWN"),
            "counts": pg_counts,
        },
        "redis": {
            "supervisor_status": svc_status.get("redis", "UNKNOWN"),
            **redis_info,
        },
        "mongo_mirror": mongo_mirror,
    }


@router.post("/admin/datastores/{service}/{action}")
async def datastore_control(service: str, action: str, request: Request) -> Dict[str, Any]:
    """Start/stop/restart a datastore service via supervisorctl. Admin only."""
    user = await require_admin(request)
    service = service.lower()
    action = action.lower()
    if service not in _ALLOWED_SERVICES:
        raise HTTPException(status_code=400, detail=f"service must be one of {sorted(_ALLOWED_SERVICES)}")
    if action not in _ALLOWED_ACTIONS:
        raise HTTPException(status_code=400, detail=f"action must be one of {sorted(_ALLOWED_ACTIONS)}")

    cmd = f"{_SUPERVISORCTL} {action} {service}"
    logger.info(f"[admin={user.get('email')}] datastore control: {cmd}")
    result = await _run_cmd(cmd, timeout=30)

    # Refetch supervisor status after action
    await asyncio.sleep(1)
    status_result = await _run_cmd(f"{_SUPERVISORCTL} status {service}")
    new_status = "UNKNOWN"
    for line in status_result.get("stdout", "").splitlines():
        parts = line.split()
        if len(parts) >= 2:
            new_status = parts[1]
            break

    return {
        "ok": result["ok"],
        "service": service,
        "action": action,
        "output": result["stdout"] or result["stderr"],
        "new_status": new_status,
    }


@router.post("/admin/datastores/restore-pg-from-mongo")
async def restore_pg_from_mongo(request: Request) -> Dict[str, Any]:
    """Replay every `fund_holdings_cache` payload into Postgres.
    
    Use this after a fork resets PG, or any time you want to reconcile.
    Safe to re-run (upsert-based).
    """
    user = await require_admin(request)
    logger.info(f"[admin={user.get('email')}] triggered restore_pg_from_mongo")
    cmd = "cd /app/backend && /root/.venv/bin/python -m scripts.restore_pg_from_mongo"
    result = await _run_cmd(cmd, timeout=120)
    # Parse last summary line from stdout
    summary = ""
    for line in reversed(result.get("stdout", "").splitlines()):
        if "Restore complete" in line or "Nothing to restore" in line:
            summary = line
            break
    return {
        "ok": result["ok"],
        "summary": summary,
        "stdout_tail": "\n".join(result.get("stdout", "").splitlines()[-15:]),
        "stderr_tail": "\n".join(result.get("stderr", "").splitlines()[-10:]),
    }


@router.post("/admin/datastores/apply-pg-schema")
async def apply_pg_schema(request: Request) -> Dict[str, Any]:
    """Apply the PG schema migration (idempotent). Useful after a fresh fork."""
    user = await require_admin(request)
    logger.info(f"[admin={user.get('email')}] applying PG schema")
    schema_file = "/app/backend/migrations/001_phase2_mf_schema.sql"
    if not os.path.exists(schema_file):
        raise HTTPException(status_code=500, detail="Schema file not found")
    cmd = f"PGPASSWORD=postgres psql -h localhost -U postgres -d nivesh -f {schema_file}"
    result = await _run_cmd(cmd, timeout=60)
    return {
        "ok": result["ok"],
        "output_tail": "\n".join(result.get("stdout", "").splitlines()[-10:]),
        "error_tail": "\n".join(result.get("stderr", "").splitlines()[-10:]),
    }


# ──────────────────────────────────────────────────────────────────────────
# Groww bootstrap — adhoc full-portfolio scrape
# ──────────────────────────────────────────────────────────────────────────

@router.post("/admin/groww/bootstrap")
async def groww_bootstrap(request: Request) -> Dict[str, Any]:
    """Kick off a Groww scrape for ALL unique MF schemes across ALL users.
    
    Builds the scrape queue from `holdings` collection (dedupe by scheme),
    then runs the scrape batch in the background.
    Returns immediately with a job summary; progress visible in `scrape_audit_log`.
    """
    user = await require_admin(request)
    logger.info(f"[admin={user.get('email')}] triggered Groww bootstrap")

    # 1) Collect unique MF scheme names from all holdings
    pipeline: List[Dict[str, Any]] = [
        {"$match": {"asset_type": {"$in": ["mutual_fund", "MUTUAL_FUND"]}}},
        {"$group": {"_id": "$name", "users": {"$addToSet": "$user_id"}}},
    ]
    scheme_docs = await db.holdings.aggregate(pipeline).to_list(5000)
    total_unique = len(scheme_docs)
    if total_unique == 0:
        return {"ok": True, "queued": 0, "message": "No mutual fund holdings found in any user portfolio."}

    # 2) Enqueue via seed_portfolio_queue (uses fund_data_resolver internally)
    from services import fund_data_resolver
    seed_result = await fund_data_resolver.seed_portfolio_queue(user_id=None, emails=None)

    # 3) Kick off the MF scheduler for background drainage (non-blocking)
    try:
        from services import mf_scheduler
        mf_scheduler.start()
        scheduler_state = mf_scheduler.status()
    except Exception as e:
        scheduler_state = {"error": str(e)}

    return {
        "ok": True,
        "unique_schemes": total_unique,
        "seeded": seed_result,
        "scheduler": scheduler_state,
        "message": (
            f"Bootstrap kicked off for {total_unique} unique MF schemes. "
            "Scheduler drains the queue in the background — watch /admin/mf/stats for progress."
        ),
    }


@router.get("/admin/groww/progress")
async def groww_progress(request: Request) -> Dict[str, Any]:
    """Return the current state of the scrape queue + recent audit log."""
    await require_admin(request)
    queue_pending = await db.scrape_queue.count_documents({"status": "pending"})
    queue_done = await db.scrape_queue.count_documents({"status": "done"})
    queue_failed = await db.scrape_queue.count_documents({"status": "failed"})
    cache_count = await db.fund_holdings_cache.count_documents({})

    # Recent audit rows (if PG up)
    recent_audit: List[Dict[str, Any]] = []
    try:
        from services import pg_client
        pool = await pg_client.get_pool()
        if pool:
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT instrument_name, status, holdings_count, source, duration_ms, created_at "
                    "FROM scrape_audit_log ORDER BY created_at DESC LIMIT 20"
                )
                recent_audit = [
                    {
                        "instrument_name": r["instrument_name"],
                        "status": r["status"],
                        "holdings_count": r["holdings_count"],
                        "source": r["source"],
                        "duration_ms": r["duration_ms"],
                        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                    }
                    for r in rows
                ]
    except Exception as e:
        logger.debug(f"recent_audit fetch failed: {e}")

    return {
        "queue": {"pending": queue_pending, "done": queue_done, "failed": queue_failed},
        "fund_holdings_cache_count": cache_count,
        "recent_audit": recent_audit,
    }
