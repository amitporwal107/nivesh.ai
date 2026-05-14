"""Redis-backed live progress tracker for long-running admin pipeline jobs.

The `nav_analytics_job_log` / `stock_refresh_job_log` tables only get a row
when a job *finishes*. While a job is mid-flight the admin dashboard had no
visibility. This module fills that gap with a short-lived Redis record per
job-name that the sweep workers update as they stream through fund IDs.

Record shape (JSON at key `pipeline:progress:<job>`):
    {
      "job": "analytics_sweep",
      "status": "running" | "ok" | "failed",
      "total": 210,
      "processed": 87,
      "failed": 2,
      "started_at": "2026-04-23T18:35:21.123+00:00",
      "updated_at": "2026-04-23T18:35:29.456+00:00",
      "duration_ms": null            # filled on completion
    }

Lifecycle:
  * `start(job, total)`   — called once at job entry.
  * `tick(job, processed_delta=1, failed_delta=0)` — called per item.
  * `finish(job, status, error_msg=None)` — called in finally block.
  * Records auto-expire after `TTL_DONE_S` (kept briefly so the UI can
    show "just completed") or `TTL_RUNNING_S` (longer, to absorb long
    sweeps without silent disappearance).

`read(job)` / `read_all()` are used by the admin /status endpoint. The
read logic flags `status="stuck"` if a running record's `started_at` is
older than `STUCK_AFTER_S` — so the UI can warn operators.
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from services import redis_client

logger = logging.getLogger(__name__)

# Jobs that we track live progress for. Used by read_all() as the canonical
# job catalogue so the dashboard can render a row per job even when idle.
KNOWN_JOBS: List[str] = [
    "nav_cron",
    "analytics_sweep",
    "v3_rescore",
    "nifty100_refresh",
    "drain_queue",
    "stale_refresh",
]

TTL_RUNNING_S = 60 * 60 * 3        # 3h safety ceiling for any single run
TTL_DONE_S = 60 * 10               # keep completed rows for 10 min so UI
                                   # can show "just finished" state briefly
STUCK_AFTER_S = 15 * 60            # 15 min without completion → stuck
STALE_TICK_AFTER_S = 60            # no tick in 60s while running → stale warning

_KEY_PREFIX = "pipeline:progress:"


def _key(job: str) -> str:
    return f"{_KEY_PREFIX}{job}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def start(job: str, total: Optional[int] = None, phase: Optional[str] = None,
                message: Optional[str] = None) -> None:
    """Mark a job as running. Overwrites any prior record for this job."""
    payload = {
        "job": job,
        "status": "running",
        "total": total,
        "processed": 0,
        "failed": 0,
        "started_at": _now_iso(),
        "updated_at": _now_iso(),
        "duration_ms": None,
        "phase": phase,
        "message": message,
    }
    try:
        await redis_client.cache_set(_key(job), payload, ttl_s=TTL_RUNNING_S)
    except Exception as e:  # noqa: BLE001
        logger.warning("pipeline_progress.start(%s) failed: %s", job, e)


async def tick(
    job: str,
    processed_delta: int = 1,
    failed_delta: int = 0,
    total: Optional[int] = None,
    phase: Optional[str] = None,
    message: Optional[str] = None,
) -> None:
    """Increment progress counters for the running job. Cheap: single GET
    + SET per call. Called from sweep worker success/failure paths.

    Optional `phase` + `message` let the worker narrate what it's doing so
    the dashboard can tell the operator WHERE time is being spent.
    """
    try:
        cur = await redis_client.cache_get(_key(job)) or {}
        if not cur or cur.get("status") != "running":
            # Out-of-band tick (e.g. start() was skipped) — materialize a
            # minimal running record so we don't lose the update.
            cur = {
                "job": job, "status": "running", "total": total,
                "processed": 0, "failed": 0,
                "started_at": _now_iso(),
            }
        cur["processed"] = int(cur.get("processed", 0)) + int(processed_delta)
        cur["failed"] = int(cur.get("failed", 0)) + int(failed_delta)
        if total is not None:
            cur["total"] = total
        if phase is not None:
            cur["phase"] = phase
        if message is not None:
            cur["message"] = message
        cur["updated_at"] = _now_iso()
        await redis_client.cache_set(_key(job), cur, ttl_s=TTL_RUNNING_S)
    except Exception as e:  # noqa: BLE001
        logger.warning("pipeline_progress.tick(%s) failed: %s", job, e)


async def set_phase(job: str, phase: str, message: Optional[str] = None) -> None:
    """Update phase/message without touching counters. Used when the worker
    transitions between stages (e.g. download → parse → upsert)."""
    try:
        cur = await redis_client.cache_get(_key(job)) or {}
        if not cur:
            return
        cur["phase"] = phase
        if message is not None:
            cur["message"] = message
        cur["updated_at"] = _now_iso()
        await redis_client.cache_set(_key(job), cur, ttl_s=TTL_RUNNING_S)
    except Exception as e:  # noqa: BLE001
        logger.warning("pipeline_progress.set_phase(%s) failed: %s", job, e)


async def finish(
    job: str,
    status: str = "ok",
    error_msg: Optional[str] = None,
    total: Optional[int] = None,
    processed: Optional[int] = None,
    failed: Optional[int] = None,
) -> None:
    """Finalise the job. Caller may override counts (e.g. when total is only
    known at the end, like drain_queue)."""
    try:
        cur = await redis_client.cache_get(_key(job)) or {}
        started_at = cur.get("started_at") or _now_iso()
        if isinstance(started_at, str):
            try:
                t0 = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            except Exception:  # noqa: BLE001
                t0 = datetime.now(timezone.utc)
        else:
            t0 = datetime.now(timezone.utc)
        dur_ms = int((datetime.now(timezone.utc) - t0).total_seconds() * 1000)
        payload = {
            "job": job,
            "status": status,
            "total": total if total is not None else cur.get("total"),
            "processed": processed if processed is not None else cur.get("processed", 0),
            "failed": failed if failed is not None else cur.get("failed", 0),
            "started_at": started_at,
            "updated_at": _now_iso(),
            "duration_ms": dur_ms,
            "error_msg": (error_msg or "")[:500] or None,
        }
        await redis_client.cache_set(_key(job), payload, ttl_s=TTL_DONE_S)
    except Exception as e:  # noqa: BLE001
        logger.warning("pipeline_progress.finish(%s) failed: %s", job, e)


def _seconds_since(iso: Optional[str]) -> Optional[float]:
    if not iso:
        return None
    try:
        t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except Exception:  # noqa: BLE001
        return None
    return (datetime.now(timezone.utc) - t).total_seconds()


def _decorate(rec: Dict[str, Any]) -> Dict[str, Any]:
    """Add derived fields (elapsed_s, pct, stuck, stale_tick_s) consumed by the UI."""
    rec = dict(rec)
    elapsed = _seconds_since(rec.get("started_at"))
    rec["elapsed_s"] = round(elapsed, 1) if elapsed is not None else None
    total = rec.get("total") or 0
    processed = rec.get("processed") or 0
    rec["pct"] = round((processed / total) * 100, 1) if total else None
    # How long since the last tick? Useful to flag "no heartbeat" silently-
    # hung jobs even before the 15-min stuck threshold.
    stale = _seconds_since(rec.get("updated_at"))
    rec["stale_tick_s"] = round(stale, 1) if stale is not None else None
    rec["is_stale"] = bool(
        rec.get("status") == "running" and stale is not None
        and stale > STALE_TICK_AFTER_S
    )
    # Stuck detection: running too long without completion.
    if rec.get("status") == "running" and elapsed is not None and elapsed > STUCK_AFTER_S:
        rec["status"] = "stuck"
    return rec


async def read(job: str) -> Optional[Dict[str, Any]]:
    try:
        rec = await redis_client.cache_get(_key(job))
    except Exception as e:  # noqa: BLE001
        logger.warning("pipeline_progress.read(%s) failed: %s", job, e)
        return None
    return _decorate(rec) if rec else None


async def read_all() -> Dict[str, Dict[str, Any]]:
    """Return {job_name: record | None} for every known job. Records may be
    None when no run has happened within TTL."""
    out: Dict[str, Dict[str, Any]] = {}
    for j in KNOWN_JOBS:
        rec = await read(j)
        if rec:
            out[j] = rec
    return out


async def clear(job: str) -> None:
    """Drop a progress record (admin-only, used for manual recovery)."""
    try:
        await redis_client.cache_del(_key(job))
    except Exception as e:  # noqa: BLE001
        logger.warning("pipeline_progress.clear(%s) failed: %s", job, e)
