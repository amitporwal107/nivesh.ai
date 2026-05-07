"""Feed health + per-ingester run history. Backed by nidp.v_feed_status
and nidp.job_log."""
from __future__ import annotations

import os
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
import logging

from fastapi import APIRouter, Depends, Query

from nidp.shared.storage.pg import get_pool
from nidp.services.query_api.auth import require_bearer


logger = logging.getLogger(__name__)
router = APIRouter(prefix="", tags=["feeds"], dependencies=[Depends(require_bearer)])


_GCP_PROJECT = os.environ.get("GCP_PROJECT", "niveshdataintelligence")


def _job_name(ingester: str) -> str:
    return f"nidp-{ingester.replace('_', '-')}"


def _cloud_logs_url(
    job_name: str,
    started_at: Optional[datetime],
    finished_at: Optional[datetime],
) -> Optional[str]:
    """Build a Cloud Console Logs deep-link narrowed to one Cloud Run
    job's run window. The +/- 30s padding handles clock skew between
    the job_log timestamp and Cloud Logging's ingestion."""
    if started_at is None:
        return None
    end = finished_at or (started_at + timedelta(hours=1))
    start_iso = (started_at - timedelta(seconds=30)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    end_iso   = (end + timedelta(seconds=30)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    query = (
        f'resource.type="cloud_run_job"\n'
        f'resource.labels.job_name="{job_name}"\n'
        f'timestamp>="{start_iso}"\n'
        f'timestamp<="{end_iso}"'
    )
    encoded = urllib.parse.quote(query, safe="")
    return (
        f"https://console.cloud.google.com/logs/query;query={encoded}"
        f"?project={_GCP_PROJECT}"
    )


def _cloud_logs_url_recent(job_name: str, hours: int = 24) -> str:
    """Looser variant — last N hours of logs for this job. Used when a
    specific run window isn't available."""
    query = (
        f'resource.type="cloud_run_job"\n'
        f'resource.labels.job_name="{job_name}"'
    )
    encoded = urllib.parse.quote(query, safe="")
    return (
        f"https://console.cloud.google.com/logs/query;query={encoded}"
        f";duration=PT{hours}H?project={_GCP_PROJECT}"
    )


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

    feeds_out: List[Dict[str, Any]] = []
    for r in rows:
        job_name = _job_name(r["ingester"])
        feeds_out.append({
            "ingester":             r["ingester"],
            "job_name":             job_name,
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
            "last_error_message":   r["last_error_message"],     # full text — UI truncates if needed
            "cloud_logs_url":       _cloud_logs_url(job_name, r["last_run_at"], None),
            "cloud_logs_url_24h":   _cloud_logs_url_recent(job_name, hours=24),
        })
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

    job_name = _job_name(ingester)
    return {
        "ingester": ingester,
        "job_name": job_name,
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
                "error_message": r["error_message"],   # full text, no truncation
                "cloud_logs_url": _cloud_logs_url(job_name, r["started_at"], r["finished_at"]),
            }
            for r in rows
        ],
    }


@router.get("/feeds/{ingester}/calendar")
async def feed_calendar(
    ingester: str,
    days: int = Query(7, ge=1, le=30),
) -> Dict[str, Any]:
    """Per-day status for the last N days, derived from job_log. One
    cell per calendar day. Useful for the Console's week-strip widget.

    Status priority within a day (worst wins): FAILED > PARTIAL > OK >
    SKIPPED. Days with no runs return status=null."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT
                COALESCE(target_date, started_at::date) AS day,
                bool_or(status IN ('OK', 'GREEN'))      AS any_ok,
                bool_or(status = 'PARTIAL')             AS any_partial,
                bool_or(status = 'FAILED')              AS any_failed,
                bool_or(status = 'SKIPPED')             AS any_skipped,
                count(*)                                AS run_count,
                sum(rows_inserted)                      AS rows_total,
                max(started_at)                         AS last_attempt
              FROM nidp.job_log
             WHERE ingester = $1
               AND started_at >= NOW() - ($2 * INTERVAL '1 day')
             GROUP BY day
             ORDER BY day DESC
        """, ingester, days)

    by_day: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        if r["any_failed"]:
            status = "FAILED"
        elif r["any_partial"]:
            status = "PARTIAL"
        elif r["any_ok"]:
            status = "OK"
        elif r["any_skipped"]:
            status = "SKIPPED"
        else:
            status = None
        by_day[r["day"].isoformat()] = {
            "status":       status,
            "run_count":    r["run_count"],
            "rows_total":   r["rows_total"],
            "last_attempt": r["last_attempt"].isoformat() if r["last_attempt"] else None,
        }

    # Fill the gap days (no runs) so the UI can render a fixed-width
    # strip without computing date arithmetic itself.
    today = datetime.utcnow().date()
    calendar: List[Dict[str, Any]] = []
    for offset in range(days):
        d = (today - timedelta(days=offset))
        key = d.isoformat()
        cell = by_day.get(key, {
            "status":       None,
            "run_count":    0,
            "rows_total":   None,
            "last_attempt": None,
        })
        calendar.append({"date": key, **cell})

    return {
        "ingester":  ingester,
        "job_name":  _job_name(ingester),
        "days":      days,
        "calendar":  calendar,
    }
