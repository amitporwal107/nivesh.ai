"""Public data-health summary — used by the global stale-data banner.

Aggregates the underlying admin pipeline status into a small,
non-sensitive payload that any authenticated user can consume.

Banner severity rules:
  - ERROR  : any job's last status == "failed" within 7d, OR critical job
             not run in > 36h (nav_cron / analytics_sweep / v3_rescore)
  - WARN   : pg_mirror > 7d stale, OR MS ratings coverage < 30%, OR
             scrape_queue.failed > 0
  - OK     : everything fresh and healthy

Endpoints:
  GET  /api/data-health/summary   — banner state
  POST /api/data-health/run-all   — admin-only seamless full-pipeline refresh.
                                     On success, flips system_config.data_pipeline_paused=true
                                     so cron jobs go silent until manually re-enabled.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request

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



# ── Seamless full-pipeline refresh ──────────────────────────────────────
# Run-state is persisted in `system_config["data_pipeline_run"]` so it
# survives backend hot-reload / restart. Single global slot — only one
# full pipeline can run at a time.

_RUN_STATE_KEY = "data_pipeline_run"


async def _read_run_state() -> Dict[str, Any]:
    doc = await db.system_config.find_one({"key": _RUN_STATE_KEY}) or {}
    return {
        "running": bool(doc.get("running", False)),
        "started_at": doc.get("started_at"),
        "finished_at": doc.get("finished_at"),
        "ok": doc.get("ok"),
        "current_step": doc.get("current_step"),
        "steps": doc.get("steps", []),
        "message": doc.get("message"),
    }


async def _write_run_state(patch: Dict[str, Any]) -> None:
    patch = dict(patch)
    patch["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.system_config.update_one(
        {"key": _RUN_STATE_KEY},
        {"$set": patch},
        upsert=True,
    )


async def _is_paused() -> bool:
    """Read the global pause flag. Cron jobs check this before running."""
    cfg = await db.system_config.find_one({"key": "data_pipeline"}) or {}
    return bool(cfg.get("paused", False))


async def _set_paused(paused: bool) -> None:
    """Toggle the pause flag. After a successful seamless refresh we
    flip it ON so cron jobs go silent until manually re-enabled."""
    await db.system_config.update_one(
        {"key": "data_pipeline"},
        {"$set": {"paused": paused, "updated_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )


_RUN_ALL_TIMEOUT_S = 600   # 10 min hard ceiling per step


async def _run_step(name: str, coro_fn) -> Dict[str, Any]:
    """Run a single pipeline step with structured success/failure capture."""
    start = datetime.now(timezone.utc)
    await _write_run_state({"current_step": name})
    try:
        res = await asyncio.wait_for(coro_fn(), timeout=_RUN_ALL_TIMEOUT_S)
        return {
            "step": name, "ok": True,
            "duration_s": (datetime.now(timezone.utc) - start).total_seconds(),
            "result": res if isinstance(res, dict) else {"value": str(res)[:200]},
        }
    except asyncio.TimeoutError:
        return {"step": name, "ok": False, "error": "timeout",
                "duration_s": _RUN_ALL_TIMEOUT_S}
    except Exception as e:  # noqa: BLE001
        logger.exception(f"data-health run-all step {name} failed")
        return {"step": name, "ok": False, "error": str(e)[:300],
                "duration_s": (datetime.now(timezone.utc) - start).total_seconds()}


async def _run_pipeline_in_background():
    """The actual sequential pipeline runner. Persists state to Mongo
    so restarts/hot-reloads don't orphan the run."""
    started_at = datetime.now(timezone.utc).isoformat()
    await _write_run_state({
        "running": True, "started_at": started_at,
        "finished_at": None, "ok": None,
        "current_step": None, "steps": [], "message": None,
    })

    async def _amfi():
        from scripts.fetch_amfi_navs import run as _run_amfi
        return await _run_amfi(dry_run=False)

    async def _sweep():
        return await nav_analytics_sweep.run_analytics_sweep()

    async def _rescore():
        return await nav_analytics_sweep.run_v3_rescore()

    async def _mirror():
        from scripts.mirror_pg_to_mongo import run as _run_mirror
        return await _run_mirror(dry_run=False)

    plan = [
        ("amfi_navs", _amfi),
        ("analytics_sweep", _sweep),
        ("v3_rescore", _rescore),
        ("pg_mirror", _mirror),
    ]
    accumulated_steps: List[Dict[str, Any]] = []
    for name, fn in plan:
        result = await _run_step(name, fn)
        accumulated_steps.append(result)
        # Persist after each step for live polling visibility
        await _write_run_state({"steps": accumulated_steps})

    all_ok = all(s["ok"] for s in accumulated_steps)
    if all_ok:
        await _set_paused(True)

    await _write_run_state({
        "running": False, "current_step": None,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "ok": all_ok, "steps": accumulated_steps,
        "message": (
            "All pipeline jobs completed successfully. Cron schedule is now PAUSED."
            if all_ok else
            f"{sum(1 for s in accumulated_steps if not s['ok'])} step(s) failed."
        ),
    })


@router.post("/run-all")
async def run_all_jobs(request: Request) -> Dict[str, Any]:
    """Kick off a seamless full-pipeline refresh in the background.

    Returns immediately with `{ok: True, started: true}`; the actual run
    happens in a fire-and-forget asyncio task whose state is persisted
    in Mongo (`system_config.data_pipeline_run`). Poll `/run-status` for
    progress + per-step results. On full success the cron pause flag is
    flipped automatically.

    Admin-only.
    """
    user = await get_current_user(request)
    if not user.get("is_admin"):
        raise HTTPException(403, "Admin only")

    state = await _read_run_state()
    if state["running"]:
        return {
            "ok": True, "started": False, "already_running": True,
            "current_step": state.get("current_step"),
            "started_at": state.get("started_at"),
        }

    asyncio.create_task(_run_pipeline_in_background())
    return {
        "ok": True, "started": True,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "message": "Pipeline kicked off in background. Poll /run-status for progress.",
    }


@router.get("/run-status")
async def run_status(request: Request) -> Dict[str, Any]:
    """Poll the in-flight or last-completed pipeline run state."""
    await get_current_user(request)
    return await _read_run_state()


@router.post("/resume")
async def resume_jobs(request: Request) -> Dict[str, Any]:
    """Re-enable the cron schedule (clears the pause flag)."""
    user = await get_current_user(request)
    if not user.get("is_admin"):
        raise HTTPException(403, "Admin only")
    await _set_paused(False)
    return {"ok": True, "paused": False, "message": "Cron schedule resumed."}


@router.get("/pause-status")
async def pause_status(request: Request) -> Dict[str, Any]:
    """Read-only paused flag — used by the banner to show 'Paused' state."""
    await get_current_user(request)
    cfg = await db.system_config.find_one({"key": "data_pipeline"}) or {}
    return {
        "paused": bool(cfg.get("paused", False)),
        "updated_at": cfg.get("updated_at"),
    }
