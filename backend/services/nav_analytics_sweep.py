"""V3 Engine Phase 2b — Parallel analytics sweep + composite score cache refresh.

Two jobs run nightly after the AMFI NAV cron completes:

1. `run_analytics_sweep()` — recomputes max_drawdown / consistency_score /
   downside_capture / aum_trend_score for every fund with ≥180 days of NAV
   history. Writes back to `mutual_fund_metadata`.

2. `run_v3_rescore()` — recomputes Quality + Health composite scores from
   the freshly-updated primitives, writes them to Postgres columns
   (durable fallback) AND Redis cache (fast read path), and invalidates
   stale entries.

Both jobs:
  • Run fund-level work **in parallel** via `asyncio.gather` batched by a
    semaphore (default 8 workers, tunable via env). At ~500 funds × ~30ms
    per compute = ~2s wall-clock.
  • Write an audit row to `nav_analytics_job_log` per invocation.
  • Are safe to re-run at any time — all writes are idempotent.

Both are also exposed via `POST /api/admin/data-pipeline/trigger/{job}`
so operators can retrigger after a failure from the admin UI.
"""
from __future__ import annotations
import asyncio
import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

from services import pg_client, nav_analytics, v3_scoring, v3_score_cache

logger = logging.getLogger(__name__)

# Default parallelism — safe for a 2-vCPU pod. Tunable via env.
DEFAULT_CONCURRENCY = int(os.environ.get("V3_SWEEP_CONCURRENCY", 8))
MIN_NAV_ROWS_FOR_ANALYTICS = 180  # ~6 months of trading days


# ── Helpers ──────────────────────────────────────────────────────────────
async def _eligible_fund_ids(min_nav_rows: int = MIN_NAV_ROWS_FOR_ANALYTICS) -> List[str]:
    """Return every instrument_id with enough NAV history to score."""
    pool = await pg_client.get_pool()
    if pool is None:
        return []
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT instrument_id::text AS iid, COUNT(*) AS navs
            FROM mutual_fund_nav_history
            GROUP BY instrument_id
            HAVING COUNT(*) >= $1
            ORDER BY MAX(nav_date) DESC
            """,
            min_nav_rows,
        )
    return [r["iid"] for r in rows]


async def _log_job_row(
    job_name: str, status: str, totals: Dict[str, int],
    duration_ms: int, error_msg: Optional[str] = None,
) -> None:
    pool = await pg_client.get_pool()
    if pool is None:
        return
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO nav_analytics_job_log
                    (job_name, status, funds_total, funds_processed,
                     funds_skipped, funds_failed, duration_ms, error_msg)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
                """,
                job_name, status,
                totals.get("total", 0), totals.get("processed", 0),
                totals.get("skipped", 0), totals.get("failed", 0),
                duration_ms, error_msg,
            )
    except Exception as e:  # noqa: BLE001
        logger.warning("[%s] audit log write failed: %s", job_name, e)


async def _last_success(job_name: str) -> Optional[Dict[str, Any]]:
    pool = await pg_client.get_pool()
    if pool is None:
        return None
    async with pool.acquire() as conn:
        r = await conn.fetchrow(
            """
            SELECT started_at, finished_at, funds_processed, funds_failed,
                   funds_total, duration_ms, status
            FROM nav_analytics_job_log
            WHERE job_name = $1 AND status IN ('ok', 'partial')
            ORDER BY finished_at DESC LIMIT 1
            """,
            job_name,
        )
    if not r:
        return None
    d = dict(r)
    for k in ("started_at", "finished_at"):
        if d.get(k):
            d[k] = d[k].isoformat()
    return d


async def recent_logs(job_name: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
    pool = await pg_client.get_pool()
    if pool is None:
        return []
    async with pool.acquire() as conn:
        if job_name:
            rows = await conn.fetch(
                """
                SELECT id, job_name, status, funds_total, funds_processed,
                       funds_skipped, funds_failed, duration_ms, error_msg,
                       started_at, finished_at
                FROM nav_analytics_job_log
                WHERE job_name = $1
                ORDER BY started_at DESC LIMIT $2
                """,
                job_name, limit,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT id, job_name, status, funds_total, funds_processed,
                       funds_skipped, funds_failed, duration_ms, error_msg,
                       started_at, finished_at
                FROM nav_analytics_job_log
                ORDER BY started_at DESC LIMIT $1
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
    return out


# ── Parallel sweep runners ───────────────────────────────────────────────
async def _process_one_analytics(iid: str, sem: asyncio.Semaphore) -> Tuple[str, str]:
    """Single-fund analytics refresh. Returns (iid, status)."""
    from services import pipeline_progress
    async with sem:
        try:
            await nav_analytics.refresh_all_analytics(iid)
            await pipeline_progress.tick("analytics_sweep", processed_delta=1)
            return iid, "ok"
        except Exception as e:  # noqa: BLE001
            logger.warning("[analytics_sweep] %s failed: %s", iid, e)
            await pipeline_progress.tick("analytics_sweep", processed_delta=0, failed_delta=1)
            return iid, "failed"


async def run_analytics_sweep(
    concurrency: int = DEFAULT_CONCURRENCY,
    only_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Parallel recompute of NAV-derived primitives for every eligible fund."""
    from services import pipeline_progress
    t_start = time.time()
    await pipeline_progress.start("analytics_sweep", total=None,
                                   phase="enumerate",
                                   message="finding funds with ≥180 NAV days")
    ids = only_ids or await _eligible_fund_ids()
    await pipeline_progress.set_phase(
        "analytics_sweep", "compute",
        message=f"recomputing max_dd / consistency / downside / AUM-trend on {len(ids)} funds",
    )
    # Re-emit total now that we know it.
    await pipeline_progress.tick("analytics_sweep", processed_delta=0, total=len(ids))
    if not ids:
        dur = int((time.time() - t_start) * 1000)
        await _log_job_row("analytics_sweep", "ok",
                           {"total": 0, "processed": 0, "skipped": 0, "failed": 0}, dur)
        await pipeline_progress.finish("analytics_sweep", "ok", total=0, processed=0, failed=0)
        return {"status": "ok", "funds_total": 0, "duration_ms": dur}

    try:
        sem = asyncio.Semaphore(concurrency)
        results = await asyncio.gather(*[_process_one_analytics(iid, sem) for iid in ids])
    except Exception as e:  # noqa: BLE001
        dur = int((time.time() - t_start) * 1000)
        await _log_job_row("analytics_sweep", "failed",
                           {"total": len(ids), "processed": 0, "skipped": 0, "failed": len(ids)},
                           dur, str(e)[:500])
        await pipeline_progress.finish("analytics_sweep", "failed", error_msg=str(e))
        raise
    processed = sum(1 for _, s in results if s == "ok")
    failed = sum(1 for _, s in results if s == "failed")
    dur = int((time.time() - t_start) * 1000)
    status = "ok" if failed == 0 else ("partial" if processed > 0 else "failed")
    totals = {"total": len(ids), "processed": processed, "skipped": 0, "failed": failed}
    await _log_job_row("analytics_sweep", status, totals, dur)
    await pipeline_progress.finish(
        "analytics_sweep", status, total=len(ids),
        processed=processed, failed=failed,
    )
    logger.info(
        f"[analytics_sweep] status={status} processed={processed}/{len(ids)} "
        f"failed={failed} duration={dur}ms"
    )
    # Invalidate score cache for processed funds — primitives changed
    if processed:
        ok_ids = [i for i, s in results if s == "ok"]
        await v3_score_cache.invalidate_many(ok_ids)
    return {"status": status, **totals, "duration_ms": dur}


async def _compute_and_cache_scores(iid: str) -> Tuple[str, str]:
    """Pull primitives, compute Quality+Health, write to PG + Redis."""
    pool = await pg_client.get_pool()
    if pool is None:
        return iid, "failed"
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT mfmd.aum_cr::float, mfmd.fund_age_years::float,
                       mfmd.expense_ratio::float, mfmd.expense_ratio_direct::float,
                       mfmd.expense_trend_delta::float,
                       mfmd.manager_tenure_years::float,
                       mfmd.turnover_ratio::float, mfmd.top10_concentration_pct::float,
                       mfmd.category_avg_1y::float, mfmd.category_avg_3y::float, mfmd.category_avg_5y::float,
                       mfmd.max_drawdown_pct::float, mfmd.consistency_score::float,
                       mfmd.downside_capture_pct::float, mfmd.aum_trend_score::float,
                       mfpr.ret_1y::float, mfpr.ret_3y::float, mfpr.ret_5y::float,
                       mfpr.sharpe::float, mfpr.sortino::float
                FROM mutual_fund_metadata mfmd
                LEFT JOIN LATERAL (
                  SELECT * FROM mutual_fund_performance_ratios
                  WHERE instrument_id = mfmd.instrument_id
                  ORDER BY ratios_date DESC LIMIT 1
                ) mfpr ON TRUE
                WHERE mfmd.instrument_id = $1::uuid
                """,
                iid,
            )
        if not row:
            return iid, "skipped"
        f = dict(row)
        quality = v3_scoring.compute_quality_score(f)
        health = v3_scoring.compute_health_score(f)

        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE mutual_fund_metadata SET
                    quality_score = $2, health_score = $3, v3_scored_at = NOW()
                WHERE instrument_id = $1::uuid
                """,
                iid, quality["score"], health["score"],
            )
        await v3_score_cache.set(iid, {
            "quality": quality, "health": health,
            "engine_version": v3_scoring.ENGINE_VERSION,
        })
        return iid, "ok"
    except Exception as e:  # noqa: BLE001
        logger.warning("[v3_rescore] %s failed: %s", iid, e)
        return iid, "failed"


async def run_v3_rescore(
    concurrency: int = DEFAULT_CONCURRENCY,
    only_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Parallel recompute of Quality+Health composites → PG + Redis."""
    from services import pipeline_progress
    t_start = time.time()
    pool = await pg_client.get_pool()
    if pool is None:
        await pipeline_progress.finish("v3_rescore", "failed", error_msg="no_pg")
        return {"status": "failed", "reason": "no_pg"}

    if only_ids:
        ids = only_ids
    else:
        await pipeline_progress.start("v3_rescore", total=None,
                                       phase="enumerate",
                                       message="loading MF instrument list")
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT instrument_id::text AS iid FROM mutual_fund_metadata"
            )
        ids = [r["iid"] for r in rows]
    if only_ids:
        await pipeline_progress.start("v3_rescore", total=len(ids),
                                       phase="compute",
                                       message=f"rescoring {len(ids)} fund(s)")
    else:
        await pipeline_progress.set_phase(
            "v3_rescore", "compute",
            message=f"Quality + Health rescore on {len(ids)} funds",
        )
        await pipeline_progress.tick("v3_rescore", processed_delta=0, total=len(ids))
    if not ids:
        dur = int((time.time() - t_start) * 1000)
        await _log_job_row("v3_rescore", "ok",
                           {"total": 0, "processed": 0, "skipped": 0, "failed": 0}, dur)
        await pipeline_progress.finish("v3_rescore", "ok", total=0, processed=0, failed=0)
        return {"status": "ok", "funds_total": 0, "duration_ms": dur}

    try:
        sem = asyncio.Semaphore(concurrency)
        async def worker(i: str) -> Tuple[str, str]:
            async with sem:
                res = await _compute_and_cache_scores(i)
                if res[1] == "ok":
                    await pipeline_progress.tick("v3_rescore", processed_delta=1)
                elif res[1] == "failed":
                    await pipeline_progress.tick("v3_rescore", processed_delta=0, failed_delta=1)
                return res
        results = await asyncio.gather(*[worker(i) for i in ids])
    except Exception as e:  # noqa: BLE001
        dur = int((time.time() - t_start) * 1000)
        await pipeline_progress.finish("v3_rescore", "failed", error_msg=str(e))
        await _log_job_row("v3_rescore", "failed",
                           {"total": len(ids), "processed": 0, "skipped": 0, "failed": len(ids)},
                           dur, str(e)[:500])
        raise
    processed = sum(1 for _, s in results if s == "ok")
    skipped = sum(1 for _, s in results if s == "skipped")
    failed = sum(1 for _, s in results if s == "failed")
    dur = int((time.time() - t_start) * 1000)
    status = "ok" if failed == 0 else ("partial" if processed > 0 else "failed")
    totals = {"total": len(ids), "processed": processed, "skipped": skipped, "failed": failed}
    await _log_job_row("v3_rescore", status, totals, dur)
    await pipeline_progress.finish(
        "v3_rescore", status, total=len(ids),
        processed=processed, failed=failed,
    )
    logger.info(
        f"[v3_rescore] status={status} processed={processed}/{len(ids)} "
        f"skipped={skipped} failed={failed} duration={dur}ms"
    )
    return {"status": status, **totals, "duration_ms": dur}


# ── Status snapshot for Admin UI ────────────────────────────────────────
async def pipeline_status() -> Dict[str, Any]:
    """Used by `GET /api/admin/data-pipeline/status`."""
    from services import mf_scheduler, pipeline_progress
    last_nav = await _last_nav_cron_summary()
    last_sweep = await _last_success("analytics_sweep")
    last_rescore = await _last_success("v3_rescore")
    last_nifty100 = await _last_stock_refresh_summary()
    scrape_queue = await _scrape_queue_summary()
    sched = await _scheduler_snapshot()
    cache_stats = await v3_score_cache.get_stats()
    # Live progress overlay — any job currently running (or recently finished)
    # surfaces a record here with real-time counts + pct + elapsed_s.
    live = await pipeline_progress.read_all()
    return {
        "jobs": {
            "nav_cron": last_nav,
            "analytics_sweep": last_sweep,
            "v3_rescore": last_rescore,
            "nifty100_refresh": last_nifty100,
        },
        "live_progress": live,
        "scrape_queue": scrape_queue,
        "scheduler": sched,
        "redis_cache": cache_stats,
    }


async def _last_stock_refresh_summary() -> Optional[Dict[str, Any]]:
    """Read from stock_refresh_job_log — the latest run of nifty100_refresh
    (scheduled) or stock_refresh_manual (admin-triggered subset)."""
    pool = await pg_client.get_pool()
    if pool is None:
        return None
    try:
        async with pool.acquire() as conn:
            r = await conn.fetchrow(
                """
                SELECT job_name, status, stocks_total, stocks_succeeded,
                       stocks_failed, duration_ms, error_msg,
                       started_at, finished_at
                FROM stock_refresh_job_log
                ORDER BY started_at DESC LIMIT 1
                """
            )
    except Exception:  # noqa: BLE001 — table may not exist pre-migration
        return None
    if not r:
        return None
    d = dict(r)
    # Normalize to the shape the frontend expects (mirror analytics_sweep keys)
    d["funds_total"] = d.pop("stocks_total", None)
    d["funds_processed"] = d.pop("stocks_succeeded", None)
    d["funds_failed"] = d.pop("stocks_failed", None)
    for k in ("started_at", "finished_at"):
        if d.get(k):
            d[k] = d[k].isoformat()
    return d


async def _scrape_queue_summary() -> Dict[str, int]:
    """Count MF holdings scrape queue by status."""
    try:
        from deps import db
        pipeline = [{"$group": {"_id": "$status", "n": {"$sum": 1}}}]
        out = {"queued": 0, "done": 0, "failed": 0}
        async for row in db.scrape_queue.aggregate(pipeline):
            key = row.get("_id") or "queued"
            out[key] = int(row.get("n", 0))
        return out
    except Exception:  # noqa: BLE001
        return {"queued": 0, "done": 0, "failed": 0}


async def _last_nav_cron_summary() -> Optional[Dict[str, Any]]:
    """Read from amfi_nav_fetch_log (populated by fetch_amfi_navs.py)."""
    pool = await pg_client.get_pool()
    if pool is None:
        return None
    try:
        async with pool.acquire() as conn:
            r = await conn.fetchrow(
                """
                SELECT status, rows_parsed, rows_upserted, rows_skipped,
                       duration_ms, error_msg, fetched_at
                FROM amfi_nav_fetch_log
                ORDER BY fetched_at DESC LIMIT 1
                """
            )
    except Exception:  # noqa: BLE001 — table may not exist pre-migration
        return None
    if not r:
        return None
    d = dict(r)
    if d.get("fetched_at"):
        d["fetched_at"] = d["fetched_at"].isoformat()
    return d


async def _scheduler_snapshot() -> List[Dict[str, Any]]:
    try:
        from services import mf_scheduler
        if mf_scheduler._scheduler is None:
            return []
        out = []
        for j in mf_scheduler._scheduler.get_jobs():
            out.append({
                "id": j.id,
                "next_run_time": j.next_run_time.isoformat() if j.next_run_time else None,
                "trigger": str(j.trigger),
            })
        return out
    except Exception:  # noqa: BLE001
        return []
