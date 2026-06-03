"""Admin Data Pipeline Monitor — status + manual retrigger for cron jobs.

Endpoints:
  GET  /api/admin/data-pipeline/status         — current status of all jobs
  GET  /api/admin/data-pipeline/logs           — recent job-log rows
  POST /api/admin/data-pipeline/trigger/{job}  — manual retrigger
       supported jobs: nav_cron | analytics_sweep | v3_rescore |
                       nifty100_refresh | stale_refresh | drain_queue
  POST /api/admin/data-pipeline/cache/invalidate — nuke V3 Redis cache
"""
from __future__ import annotations
import asyncio
import logging
from typing import Any, Dict

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request

from routes.admin import require_admin
from services import nav_analytics_sweep, v3_score_cache

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin/data-pipeline", tags=["admin-data-pipeline"])


@router.get("/status")
async def get_pipeline_status(request: Request) -> Dict[str, Any]:
    """Last-success timestamps + next-run times + Redis cache stats."""
    await require_admin(request)
    return await nav_analytics_sweep.pipeline_status()


@router.get("/logs")
async def get_pipeline_logs(
    request: Request,
    job: str = Query(None, description="Filter by job: nav_cron | analytics_sweep | v3_rescore | nifty100_refresh"),
    limit: int = Query(30, ge=1, le=200),
) -> Dict[str, Any]:
    """Recent job-log rows for the admin monitoring table."""
    await require_admin(request)
    # `nav_cron` rows live in amfi_nav_fetch_log; `nifty100_refresh` /
    # `stock_refresh_manual` live in stock_refresh_job_log; the rest in
    # nav_analytics_job_log.
    if job == "nav_cron":
        from services import pg_client
        pool = await pg_client.get_pool()
        if pool is None:
            return {"logs": []}
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, 'nav_cron' AS job_name, status,
                       rows_parsed AS funds_total, rows_upserted AS funds_processed,
                       rows_skipped AS funds_skipped, NULL::int AS funds_failed,
                       duration_ms, error_msg, fetched_at AS started_at, fetched_at AS finished_at
                FROM amfi_nav_fetch_log
                ORDER BY fetched_at DESC LIMIT $1
                """,
                limit,
            )
        out = []
        for r in rows:
            d = dict(r)
            for k in ("started_at", "finished_at"):
                if d.get(k):
                    d[k] = d[k].isoformat()
            out.append(d)
        return {"logs": out}
    if job == "nifty100_refresh":
        from services import pg_client
        pool = await pg_client.get_pool()
        if pool is None:
            return {"logs": []}
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT id, job_name, status,
                           stocks_total AS funds_total,
                           stocks_succeeded AS funds_processed,
                           NULL::int AS funds_skipped,
                           stocks_failed AS funds_failed,
                           duration_ms, error_msg, started_at, finished_at
                    FROM stock_refresh_job_log
                    WHERE job_name IN ('nifty100_refresh', 'stock_refresh_manual')
                    ORDER BY started_at DESC LIMIT $1
                    """,
                    limit,
                )
        except Exception:  # noqa: BLE001 — table may not exist
            return {"logs": []}
        out = []
        for r in rows:
            d = dict(r)
            for k in ("started_at", "finished_at"):
                if d.get(k):
                    d[k] = d[k].isoformat()
            out.append(d)
        return {"logs": out}
    return {"logs": await nav_analytics_sweep.recent_logs(job, limit)}


# Background-task registry to prevent concurrent manual triggers of the same job
_running: Dict[str, bool] = {}


async def _run_bg(job_name: str, coro_factory) -> None:
    """Run a job coroutine in the background, guarding against double-run."""
    if _running.get(job_name):
        logger.info("[%s] already running — skipping duplicate trigger", job_name)
        return
    _running[job_name] = True
    try:
        await coro_factory()
    except Exception as e:  # noqa: BLE001
        logger.exception("[%s] background run failed: %s", job_name, e)
    finally:
        _running[job_name] = False


@router.post("/trigger/{job_name}")
async def trigger_job(job_name: str, request: Request, background: BackgroundTasks) -> Dict[str, Any]:
    """Manually retrigger a pipeline job. Returns 202-like ack; the job runs
    in the background. Poll `/status` or `/logs` for completion."""
    await require_admin(request)
    if _running.get(job_name):
        raise HTTPException(status_code=409, detail=f"{job_name} already running")

    if job_name == "nav_cron":
        from scripts.fetch_amfi_navs import run as _run_amfi
        async def _factory(): await _run_amfi(dry_run=False)
    elif job_name == "analytics_sweep":
        async def _factory(): await nav_analytics_sweep.run_analytics_sweep()
    elif job_name == "v3_rescore":
        async def _factory(): await nav_analytics_sweep.run_v3_rescore()
    elif job_name == "nifty100_refresh":
        from services import groww_stock_scraper as _gs
        async def _factory(): await _gs.refresh_nifty_100()
    elif job_name == "stale_refresh":
        from services import mf_scheduler as _sch
        async def _factory(): await _sch._stale_refresh_job()
    elif job_name == "drain_queue":
        from services import fund_data_resolver as _fdr
        async def _factory(): await _fdr.drain_queue(max_items=30, force=True)
    else:
        raise HTTPException(status_code=400, detail=f"Unknown job: {job_name}")

    background.add_task(_run_bg, job_name, _factory)
    return {"status": "accepted", "job": job_name, "message": "Running in background"}


@router.post("/cache/invalidate")
async def invalidate_cache(request: Request) -> Dict[str, Any]:
    """Nuke the entire V3 score Redis cache. Next API read recomputes."""
    await require_admin(request)
    deleted = await v3_score_cache.invalidate_all()
    return {"status": "ok", "keys_deleted": deleted}


@router.post("/cache/invalidate-performance")
async def invalidate_performance_caches(request: Request) -> Dict[str, Any]:
    """Clear all per-user performance caches so the next request recomputes
    with the current code.

    Clears:
      - MongoDB  fund_performance_cache  (mfapi.in-based 1Y/3M/1M rankings)
      - Postgres portfolio_performance_cache  (XIRR / waterfall / contributors)

    Called automatically by the GitHub Actions deploy workflow after each
    successful health check, so users always see data computed with the
    deployed code — never stale data from a previous version.
    """
    await require_admin(request)
    from deps import db
    from services import pg_client

    results: Dict[str, Any] = {}

    # Clear MongoDB fund_performance_cache
    try:
        res = await db.fund_performance_cache.delete_many({})
        results["mongo_fund_performance_cache"] = {"deleted": res.deleted_count}
    except Exception as e:
        logger.warning("invalidate-performance: mongo clear failed: %s", e)
        results["mongo_fund_performance_cache"] = {"error": str(e)}

    # Clear Postgres portfolio_performance_cache
    try:
        pool = await pg_client.get_pool()
        if pool:
            async with pool.acquire() as conn:
                # execute() returns "DELETE N" — split to get row count
                status = await conn.execute("DELETE FROM portfolio_performance_cache")
                deleted_pg = int(status.split()[-1]) if status else 0
            results["pg_portfolio_performance_cache"] = {"deleted": deleted_pg}
        else:
            results["pg_portfolio_performance_cache"] = {"skipped": "no pg pool"}
    except Exception as e:
        logger.warning("invalidate-performance: pg clear failed: %s", e)
        results["pg_portfolio_performance_cache"] = {"error": str(e)}

    logger.info("invalidate-performance: %s", results)
    return {"status": "ok", "cleared": results}


@router.post("/progress/{job_name}/clear")
async def clear_progress(job_name: str, request: Request) -> Dict[str, Any]:
    """Clear a stuck live-progress record (admin recovery). Does NOT kill the
    underlying task — use when a progress record is orphaned (job crashed
    silently) and you want the UI to stop showing 'running/stuck'."""
    await require_admin(request)
    from services import pipeline_progress
    await pipeline_progress.clear(job_name)
    return {"status": "ok", "cleared": job_name}
