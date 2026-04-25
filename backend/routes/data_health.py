"""Public data-health summary — used by the global stale-data banner.

Aggregates the underlying admin pipeline status into a small,
non-sensitive payload that any authenticated user can consume.

Banner severity rules:
  - ERROR  : any job's last status == "failed" within 7d, OR critical job
             not run in > 36h (nav_cron / analytics_sweep / v3_rescore)
  - WARN   : pg_mirror > 7d stale, OR MS ratings coverage < 30%, OR
             scrape_queue.failed > 0
  - OK     : everything fresh and healthy

Endpoint:
  GET /api/data-health/summary
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request

from deps import db, get_current_user
from services import nav_analytics_sweep

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/data-health", tags=["data-health"])


# ── Staleness thresholds (hours) ─────────────────────────────────────────
_STALE_HOURS_CRITICAL = 36   # daily jobs — alert beyond this
_STALE_HOURS_MIRROR = 24 * 7  # weekly mirror — 7 days
_MS_COVERAGE_WARN_PCT = 30.0


def _hours_since(iso_or_dt) -> Optional[float]:
    """Return age in hours from an ISO string or datetime; None if missing."""
    if not iso_or_dt:
        return None
    try:
        if isinstance(iso_or_dt, datetime):
            ts = iso_or_dt
        else:
            ts = datetime.fromisoformat(str(iso_or_dt).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - ts).total_seconds() / 3600.0
    except (TypeError, ValueError):
        return None


_FRIENDLY_NAME = {
    "nav_cron": "AMFI NAV refresh",
    "analytics_sweep": "Analytics sweep (drawdown / consistency)",
    "v3_rescore": "V3 fund rescore",
    "nifty100_refresh": "Nifty 100 stock refresh",
}


def _classify_job(name: str, summary: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return zero-or-more issue dicts for a single job."""
    out: List[Dict[str, Any]] = []
    label = _FRIENDLY_NAME.get(name, name)
    if summary is None:
        out.append({
            "job": name,
            "label": label,
            "severity": "warn",
            "message": f"{label}: no run history found.",
            "last_run_at": None,
        })
        return out

    started_at = summary.get("started_at") or summary.get("fetched_at") or summary.get("finished_at")
    age_h = _hours_since(started_at)
    status = (summary.get("status") or "").lower()

    if status in ("failed", "error", "fail"):
        out.append({
            "job": name,
            "label": label,
            "severity": "error",
            "message": f"{label} failed: {summary.get('error_msg') or 'unknown error'}",
            "last_run_at": started_at,
        })
    elif age_h is not None and age_h > _STALE_HOURS_CRITICAL:
        out.append({
            "job": name,
            "label": label,
            "severity": "error" if name in ("nav_cron", "analytics_sweep") else "warn",
            "message": f"{label} hasn't run in {age_h:.0f}h (last run {started_at[:10] if isinstance(started_at, str) else 'unknown'}).",
            "last_run_at": started_at,
        })
    return out


async def _ms_rating_coverage() -> Dict[str, Any]:
    """Compute Morningstar rating coverage from the pg_mirror collection."""
    try:
        total = await db.pg_mirror_mutual_fund_metadata.count_documents({})
        rated = await db.pg_mirror_mutual_fund_metadata.count_documents(
            {"morningstar_rating": {"$ne": None}}
        )
        pct = (rated / total * 100.0) if total > 0 else 0.0
        return {"total": total, "rated": rated, "pct": round(pct, 1)}
    except Exception as e:  # noqa: BLE001
        logger.warning(f"MS coverage check failed: {e}")
        return {"total": 0, "rated": 0, "pct": 0.0}


async def _mirror_age_hours() -> Optional[float]:
    """How long since pg_mirror was last refreshed?"""
    try:
        latest = None
        async for d in db.pg_mirror_meta.find({}, {"_id": 0, "mirrored_at": 1}):
            ts = d.get("mirrored_at")
            if ts and (latest is None or ts > latest):
                latest = ts
        return _hours_since(latest) if latest else None
    except Exception:  # noqa: BLE001
        return None


@router.get("/summary")
async def data_health_summary(request: Request) -> Dict[str, Any]:
    """Tiny payload for the global stale-data banner.

    Response shape:
      {
        status: "ok" | "warn" | "error",
        issues: [{job, label, severity, message, last_run_at}],
        ms_coverage: {total, rated, pct},
        mirror_age_hours: float | null,
        scrape_queue: {queued, done, failed},
        checked_at: ISO,
      }
    """
    await get_current_user(request)  # auth guard — must be logged in

    # Pull the admin pipeline status (already aggregates job runs).
    try:
        ps = await nav_analytics_sweep.pipeline_status()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"data-health pipeline_status failed: {e}")
        ps = {"jobs": {}, "scrape_queue": {"queued": 0, "done": 0, "failed": 0}}

    issues: List[Dict[str, Any]] = []
    jobs = ps.get("jobs") or {}
    for name in ("nav_cron", "analytics_sweep", "v3_rescore", "nifty100_refresh"):
        issues.extend(_classify_job(name, jobs.get(name)))

    # pg_mirror staleness
    mirror_age = await _mirror_age_hours()
    if mirror_age is not None and mirror_age > _STALE_HOURS_MIRROR:
        issues.append({
            "job": "pg_mirror",
            "label": "Postgres → Mongo mirror",
            "severity": "warn",
            "message": f"Mirror is {mirror_age / 24:.1f} days stale — restored data may be outdated.",
            "last_run_at": None,
        })

    # MS ratings coverage
    ms = await _ms_rating_coverage()
    if ms["total"] > 0 and ms["pct"] < _MS_COVERAGE_WARN_PCT:
        issues.append({
            "job": "morningstar_ratings",
            "label": "Morningstar ratings",
            "severity": "warn",
            "message": f"Only {ms['rated']}/{ms['total']} funds rated ({ms['pct']:.0f}%). Refresh on Portfolio page.",
            "last_run_at": None,
        })

    # Scrape queue failures
    sq = ps.get("scrape_queue") or {}
    if sq.get("failed", 0) > 0:
        issues.append({
            "job": "scrape_queue",
            "label": "MF holdings scrape",
            "severity": "warn",
            "message": f"{sq['failed']} fund(s) failed to scrape — Admin → Data Pipeline to retry.",
            "last_run_at": None,
        })

    # Overall severity = max of any issue
    severities = [i["severity"] for i in issues]
    if "error" in severities:
        status = "error"
    elif "warn" in severities:
        status = "warn"
    else:
        status = "ok"

    return {
        "status": status,
        "issues": issues,
        "ms_coverage": ms,
        "mirror_age_hours": round(mirror_age, 1) if mirror_age is not None else None,
        "scrape_queue": sq,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
