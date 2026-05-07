"""Feed health + per-ingester run history. Backed by nidp.v_feed_status
and nidp.job_log."""
from __future__ import annotations

from typing import Any, Dict, List
import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from nidp.shared.storage.pg import get_pool
from nidp.services.query_api.auth import require_bearer


logger = logging.getLogger(__name__)
router = APIRouter(prefix="", tags=["feeds"], dependencies=[Depends(require_bearer)])


@router.get("/feeds")
async def feeds() -> Dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            rows = await conn.fetch("""
                SELECT ingester, source_class, expected_freq, schedule_cron,
                       confidence, is_primary,
                       last_run_status, consecutive_failures,
                       last_run_at, last_success_at, last_failure_at,
                       last_target_date, last_rows_inserted,
                       last_run_duration_ms,
                       success_count, failure_count, partial_count,
                       last_error_message
                  FROM nidp.v_feed_status
                 ORDER BY ingester
            """)
        except Exception as e:                                        # noqa: BLE001
            logger.warning("feeds: v_feed_status query failed: %s", e)
            return {"feeds": [], "error": str(e)[:200]}

    feeds_out: List[Dict[str, Any]] = [
        {
            "ingester":             r["ingester"],
            "source_class":         r["source_class"],
            "expected_freq":        r["expected_freq"],
            "schedule_cron":        r["schedule_cron"],
            "confidence":           float(r["confidence"]) if r["confidence"] is not None else None,
            "is_primary":           r["is_primary"],
            "last_run_status":      r["last_run_status"],
            "consecutive_failures": r["consecutive_failures"],
            "last_run_at":          r["last_run_at"].isoformat() if r["last_run_at"] else None,
            "last_success_at":      r["last_success_at"].isoformat() if r["last_success_at"] else None,
            "last_failure_at":      r["last_failure_at"].isoformat() if r["last_failure_at"] else None,
            "last_target_date":     r["last_target_date"].isoformat() if r["last_target_date"] else None,
            "last_rows_inserted":   r["last_rows_inserted"],
            "last_run_duration_ms": r["last_run_duration_ms"],
            "success_count":        r["success_count"],
            "failure_count":        r["failure_count"],
            "partial_count":        r["partial_count"],
            "last_error_message":   (r["last_error_message"] or "")[:200] if r["last_error_message"] else None,
        }
        for r in rows
    ]
    return {"feeds": feeds_out, "error": None}


@router.get("/feeds/{ingester}/runs")
async def feed_runs(ingester: str, limit: int = Query(20, ge=1, le=100)) -> Dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT run_id, target_date, status,
                   started_at, finished_at, duration_ms,
                   rows_fetched, rows_inserted, rows_skipped,
                   error_class, error_message
              FROM nidp.job_log
             WHERE ingester = $1
             ORDER BY started_at DESC
             LIMIT $2
        """, ingester, limit)

    return {
        "ingester": ingester,
        "runs": [
            {
                "run_id":        str(r["run_id"]),
                "target_date":   r["target_date"].isoformat() if r["target_date"] else None,
                "status":        r["status"],
                "started_at":    r["started_at"].isoformat() if r["started_at"] else None,
                "finished_at":   r["finished_at"].isoformat() if r["finished_at"] else None,
                "duration_ms":   r["duration_ms"],
                "rows_fetched":  r["rows_fetched"],
                "rows_inserted": r["rows_inserted"],
                "rows_skipped":  r["rows_skipped"],
                "error_class":   r["error_class"],
                "error_message": (r["error_message"] or "")[:500] if r["error_message"] else None,
            }
            for r in rows
        ],
    }
