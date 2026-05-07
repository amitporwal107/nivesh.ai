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
    """Per-ingester health view. Three enhancements over a plain
    v_feed_status read:

      1. effective_last_success_at = COALESCE(source_registry, max(job_log.started_at)
         WHERE status='OK'). The ingester upsert doesn't always update
         source_registry.last_success_at, so falling back to job_log
         keeps the column populated.
      2. last_7_days = [{date, status}] for the trailing week, derived
         from job_log. Drives the dashboard's mini week-strip widget.
      3. Sort by last_run_at DESC NULLS LAST — most-active feeds at top,
         dormant/never-run feeds at the bottom.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Single query: v_feed_status + last_success_at fallback in one
        # round-trip via LATERAL/CTE.
        try:
            rows = await conn.fetch("""
                WITH last_ok AS (
                    SELECT DISTINCT ON (ingester)
                        ingester, started_at AS log_last_success_at
                      FROM nidp.job_log
                     WHERE status IN ('OK', 'GREEN')
                     ORDER BY ingester, started_at DESC
                )
                SELECT v.ingester, v.source_class, v.expected_freq, v.schedule_cron,
                       v.confidence, v.is_primary,
                       v.last_run_status, v.consecutive_failures,
                       v.last_run_at,
                       COALESCE(v.last_success_at, l.log_last_success_at)
                                                       AS last_success_at,
                       v.last_failure_at,
                       v.last_target_date, v.last_rows_inserted,
                       v.last_run_duration_ms,
                       v.success_count, v.failure_count, v.partial_count,
                       v.last_error_message
                  FROM nidp.v_feed_status v
                  LEFT JOIN last_ok l USING (ingester)
                 ORDER BY
                    CASE WHEN v.last_run_at IS NULL THEN 1 ELSE 0 END,
                    v.last_run_at DESC,
                    v.ingester
            """)
        except Exception as e:                                        # noqa: BLE001
            logger.warning("feeds: v_feed_status query failed: %s", e)
            return {"feeds": [], "error": str(e)[:200]}

        # Trailing-week per-day status, all ingesters in one query.
        try:
            cal_rows = await conn.fetch("""
                SELECT ingester,
                       COALESCE(target_date, started_at::date) AS day,
                       bool_or(status IN ('OK', 'GREEN')) AS any_ok,
                       bool_or(status = 'PARTIAL')        AS any_partial,
                       bool_or(status = 'FAILED')         AS any_failed,
                       bool_or(status = 'SKIPPED')        AS any_skipped,
                       count(*)                           AS run_count
                  FROM nidp.job_log
                 WHERE started_at >= NOW() - INTERVAL '7 days'
                 GROUP BY ingester, day
            """)
        except Exception as e:                                        # noqa: BLE001
            logger.warning("feeds: 7-day calendar query failed: %s", e)
            cal_rows = []

    cal_by_ing: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for r in cal_rows:
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
        cal_by_ing.setdefault(r["ingester"], {})[r["day"].isoformat()] = {
            "status":    status,
            "run_count": r["run_count"],
        }

    today = datetime.utcnow().date()
    seven_days = [(today - timedelta(days=i)).isoformat()
                  for i in reversed(range(7))]    # oldest → newest

    feeds_out: List[Dict[str, Any]] = []
    for r in rows:
        job_name = _job_name(r["ingester"])
        last_7 = [
            {
                "date":       d,
                "is_today":   d == today.isoformat(),
                **(cal_by_ing.get(r["ingester"], {}).get(d) or {"status": None, "run_count": 0}),
            }
            for d in seven_days
        ]
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
            "last_error_message":   r["last_error_message"],
            "cloud_logs_url":       _cloud_logs_url(job_name, r["last_run_at"], None),
            "cloud_logs_url_24h":   _cloud_logs_url_recent(job_name, hours=24),
            "last_7_days":          last_7,
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
