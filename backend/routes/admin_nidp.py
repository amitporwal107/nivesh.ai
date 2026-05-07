"""Admin → NIDP diagnostics + per-job control plane.

Two surfaces:

1. Diagnostic dump  — one-button bundle of feed-health, FAILED runs,
   logs, and image tags into a private gist. Replaces screenshot
   copy-paste while debugging.

2. Job control plane  — list / trigger / inspect each of the 13 NIDP
   Cloud Run jobs (11 daily ingesters + 2 backfill). Backed by
   `gcloud run jobs` and the local `nidp.job_log` Postgres table.

Endpoints:
  POST /api/admin/nidp/dump                       — run dump_for_claude.sh
  GET  /api/admin/nidp/script                     — pre-flight (script + gh)
  GET  /api/admin/nidp/jobs                       — list all 13 jobs + status
  POST /api/admin/nidp/jobs/{ingester}/execute    — trigger Cloud Run job
  GET  /api/admin/nidp/jobs/{ingester}/runs       — last N rows from job_log
  GET  /api/admin/nidp/jobs/{ingester}/logs       — tail Cloud Run logs

All endpoints require admin auth. Cloud Run + gcloud calls shell out
the same way fetch_logs.sh and dump_for_claude.sh do — the API host
needs `gcloud` on PATH and the Cloud Run service-account perms.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request

from deps import require_admin

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin/nidp", tags=["admin-nidp"])

# Canonical list of NIDP ingesters (mirrors backend/nidp/deploy/gcp/deploy.sh).
# `cadence` is informational; the actual cadence is enforced by Cloud Scheduler.
NIDP_INGESTERS: List[Dict[str, str]] = [
    {"ingester": "bhavcopy",            "cadence": "daily"},
    {"ingester": "delivery",            "cadence": "daily"},
    {"ingester": "index_close",         "cadence": "daily"},
    {"ingester": "fii_dii",             "cadence": "daily"},
    {"ingester": "bulk_deals",          "cadence": "daily"},
    {"ingester": "block_deals",         "cadence": "daily"},
    {"ingester": "corporate_actions",   "cadence": "event"},
    {"ingester": "rbi_yields",          "cadence": "daily"},
    {"ingester": "fred_macro",          "cadence": "daily"},
    {"ingester": "nse_calendar",        "cadence": "monthly"},
    {"ingester": "index_constituents",  "cadence": "monthly"},
    {"ingester": "snapshot_builder",    "cadence": "daily"},
    {"ingester": "yfinance_backfill",   "cadence": "event"},
]

GCP_PROJECT = os.environ.get("GCP_PROJECT", "niveshdataintelligence")
GCP_REGION  = os.environ.get("GCP_REGION",  "asia-south1")


def _job_name(ingester: str) -> str:
    """Cloud Run Job name follows nidp-<ingester-with-dashes>."""
    return f"nidp-{ingester.replace('_', '-')}"


def _ingester_or_404(ingester: str) -> str:
    if ingester not in {i["ingester"] for i in NIDP_INGESTERS}:
        raise HTTPException(status_code=404, detail=f"unknown ingester: {ingester}")
    return ingester


async def _run_gcloud(*args: str, timeout: int = 60) -> tuple[int, str, str]:
    """Run `gcloud <args>` and return (rc, stdout, stderr). Returns
    (-1, '', 'gcloud not on PATH') if gcloud is missing — callers can
    surface this as a 503 instead of a generic 500."""
    if not shutil.which("gcloud"):
        return -1, "", "gcloud not on PATH on this host"
    proc = await asyncio.create_subprocess_exec(
        "gcloud", *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out_b, err_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return -1, "", f"gcloud timed out after {timeout}s"
    return proc.returncode or 0, out_b.decode("utf-8", errors="replace"), err_b.decode("utf-8", errors="replace")

# Repo root resolution: server.py lives at backend/server.py, this file
# at backend/routes/admin_nidp.py. The script is at
# backend/nidp/deploy/gcp/dump_for_claude.sh — three levels up from here.
_REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = _REPO_ROOT / "backend" / "nidp" / "deploy" / "gcp" / "dump_for_claude.sh"
DUMP_TIMEOUT_S = 180   # 3 min hard cap; script normally finishes in 30-90s

_GIST_RE = re.compile(r"https://gist\.github\.com/[A-Za-z0-9_/-]+")


@router.get("/script")
async def script_health(request: Request) -> Dict[str, Any]:
    """Pre-flight check the UI can hit before showing the Run button —
    confirms the script exists and is executable, plus whether `gh` is
    on PATH (without that, the script will print to /tmp instead of
    uploading)."""
    await require_admin(request)
    return {
        "script_path": str(SCRIPT_PATH),
        "exists":      SCRIPT_PATH.exists(),
        "executable":  SCRIPT_PATH.exists() and os.access(SCRIPT_PATH, os.X_OK),
        "gh_on_path":  shutil.which("gh") is not None,
    }


@router.post("/dump")
async def trigger_dump(request: Request) -> Dict[str, Any]:
    """Run dump_for_claude.sh and return the gist URL it printed.

    The script writes a /tmp/nidp_dump_*.md file *and* (when gh is
    available) uploads it to a private gist. We capture both stdout
    and stderr and surface the gist URL to the caller.
    """
    await require_admin(request)

    if not SCRIPT_PATH.exists():
        raise HTTPException(status_code=500, detail=f"script missing: {SCRIPT_PATH}")
    if not os.access(SCRIPT_PATH, os.X_OK):
        raise HTTPException(status_code=500, detail=f"script not executable: {SCRIPT_PATH}")

    logger.info("admin/nidp: running dump_for_claude.sh")
    try:
        proc = await asyncio.wait_for(
            asyncio.create_subprocess_exec(
                "bash", str(SCRIPT_PATH),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=str(_REPO_ROOT),
            ),
            timeout=10,   # process spawn only — actual run is below
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=500, detail="failed to spawn dump script")

    try:
        stdout_b, _ = await asyncio.wait_for(proc.communicate(), timeout=DUMP_TIMEOUT_S)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise HTTPException(
            status_code=504,
            detail=f"dump script exceeded {DUMP_TIMEOUT_S}s timeout — check VM perms (sudo docker, gcloud)",
        )

    output = stdout_b.decode("utf-8", errors="replace")
    rc = proc.returncode

    # The script prints a URL line like:  https://gist.github.com/<u>/<id>
    gist_match = _GIST_RE.search(output)
    gist_url = gist_match.group(0) if gist_match else None

    # Locate the /tmp file path the script always prints, even when gh
    # isn't installed — useful as a fallback for the admin to cat/copy.
    tmp_match = re.search(r"/tmp/nidp_dump_\d+_\d+\.md", output)
    tmp_path = tmp_match.group(0) if tmp_match else None

    if rc != 0 and not gist_url:
        # Truncate output to keep the response small but informative.
        snippet = output[-2000:] if len(output) > 2000 else output
        raise HTTPException(
            status_code=500,
            detail=f"dump script exited with {rc}.\n--- last output ---\n{snippet}",
        )

    return {
        "ok":         True,
        "gist_url":   gist_url,
        "tmp_path":   tmp_path,
        "rc":         rc,
        "stdout_tail": output[-1500:] if len(output) > 1500 else output,
    }


# ────────────────────────────────────────────────────────────────────
# Per-job control plane
# ────────────────────────────────────────────────────────────────────

@router.get("/jobs")
async def list_jobs(request: Request) -> Dict[str, Any]:
    """List all 13 NIDP ingesters with their latest run status (from
    nidp.v_feed_status) and current Cloud Run image tag.

    The DB query is one round-trip; the gcloud calls are fired in
    parallel so the whole thing returns in ~1-2s even with 13 jobs.
    """
    await require_admin(request)

    # ── DB: latest feed status, joined with last_error_message ─────
    from services import pg_client
    pool = await pg_client.get_pool()
    db_status: Dict[str, Dict[str, Any]] = {}
    if pool is not None:
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT ingester, last_run_status, consecutive_failures,
                       last_run_at, last_run_duration_ms,
                       last_rows_inserted, last_error_message
                  FROM nidp.v_feed_status
            """)
            for r in rows:
                db_status[r["ingester"]] = {
                    "last_run_status":      r["last_run_status"],
                    "consecutive_failures": r["consecutive_failures"],
                    "last_run_at":          r["last_run_at"].isoformat() if r["last_run_at"] else None,
                    "last_run_duration_ms": r["last_run_duration_ms"],
                    "last_rows_inserted":   r["last_rows_inserted"],
                    "last_error_message":   (r["last_error_message"] or "")[:200] if r["last_error_message"] else None,
                }

    # ── gcloud: image tag per Cloud Run job (parallel) ─────────────
    async def _image_for(ingester: str) -> tuple[str, Optional[str]]:
        rc, out, _ = await _run_gcloud(
            "run", "jobs", "describe", _job_name(ingester),
            "--region", GCP_REGION, "--project", GCP_PROJECT,
            "--format=value(spec.template.spec.template.spec.containers[0].image)",
            timeout=15,
        )
        return ingester, (out.strip() or None) if rc == 0 else None

    image_results = await asyncio.gather(
        *[_image_for(i["ingester"]) for i in NIDP_INGESTERS],
        return_exceptions=True,
    )
    images = {}
    for r in image_results:
        if isinstance(r, tuple):
            images[r[0]] = r[1]

    return {
        "project": GCP_PROJECT,
        "region":  GCP_REGION,
        "jobs": [
            {
                **spec,
                "job_name":   _job_name(spec["ingester"]),
                "image":      images.get(spec["ingester"]),
                **db_status.get(spec["ingester"], {}),
            }
            for spec in NIDP_INGESTERS
        ],
    }


@router.post("/jobs/{ingester}/execute")
async def execute_job(ingester: str, request: Request) -> Dict[str, Any]:
    """Trigger a Cloud Run job execution. Returns immediately with the
    execution name — does NOT wait for the job to finish (jobs run
    minutes; UI polls /runs to surface completion)."""
    await require_admin(request)
    _ingester_or_404(ingester)
    job = _job_name(ingester)

    rc, out, err = await _run_gcloud(
        "run", "jobs", "execute", job,
        "--region", GCP_REGION, "--project", GCP_PROJECT,
        "--format=value(metadata.name)",
        timeout=30,
    )
    if rc != 0:
        raise HTTPException(
            status_code=502 if "PERMISSION_DENIED" in err else 500,
            detail=f"gcloud run jobs execute failed (rc={rc}): {err.strip() or out.strip()}",
        )
    execution_name = out.strip() or None
    logger.info("admin/nidp: triggered %s (execution=%s)", job, execution_name)
    return {
        "ok":             True,
        "ingester":       ingester,
        "job_name":       job,
        "execution_name": execution_name,
    }


@router.get("/jobs/{ingester}/runs")
async def job_runs(
    ingester: str,
    request: Request,
    limit: int = Query(20, ge=1, le=100),
) -> Dict[str, Any]:
    """Last N rows from nidp.job_log for this ingester."""
    await require_admin(request)
    _ingester_or_404(ingester)

    from services import pg_client
    pool = await pg_client.get_pool()
    if pool is None:
        return {"ingester": ingester, "runs": []}

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


@router.get("/jobs/{ingester}/logs")
async def job_logs(
    ingester: str,
    request: Request,
    window: str = Query("4h", description="gcloud --freshness window: 30m, 4h, 24h, etc."),
    limit: int = Query(100, ge=1, le=500),
) -> Dict[str, Any]:
    """Tail Cloud Run logs for this ingester. Pulls both jsonPayload
    (structured logger output) and textPayload (raw stdout)."""
    await require_admin(request)
    _ingester_or_404(ingester)
    job = _job_name(ingester)

    rc, out, err = await _run_gcloud(
        "logging", "read",
        f'resource.type=cloud_run_job AND resource.labels.job_name="{job}"',
        f"--freshness={window}",
        f"--limit={limit}",
        "--format=value(timestamp,severity,jsonPayload.msg,jsonPayload.exc,textPayload)",
        "--project", GCP_PROJECT,
        "--order=desc",
        timeout=30,
    )
    if rc != 0:
        raise HTTPException(
            status_code=502 if "PERMISSION_DENIED" in err else 500,
            detail=f"gcloud logging read failed (rc={rc}): {err.strip() or out.strip()}",
        )
    return {
        "ingester": ingester,
        "job_name": job,
        "window":   window,
        "lines":    [l for l in out.splitlines() if l.strip()],
    }
