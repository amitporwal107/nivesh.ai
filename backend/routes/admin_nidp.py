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
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
import httpx

from deps import require_admin
from services import nidp_query_client as _nq

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin/nidp", tags=["admin-nidp"])

# Canonical list of NIDP ingesters — must mirror ALL_SERVICES in
# backend/nidp/deploy/gcp/build_on_gcp.sh. When you add a new Cloud Run
# job there, register it here so it shows up in the Console + so its
# /jobs/{ingester}/* routes resolve. `cadence` is informational; actual
# scheduling is done by Cloud Scheduler.
NIDP_INGESTERS: List[Dict[str, str]] = [
    # Phase 1A — core market data
    {"ingester": "bhavcopy",                    "cadence": "daily"},
    {"ingester": "delivery",                    "cadence": "daily"},
    {"ingester": "index_close",                 "cadence": "daily"},
    {"ingester": "fii_dii",                     "cadence": "daily"},
    {"ingester": "bulk_deals",                  "cadence": "daily"},
    {"ingester": "block_deals",                 "cadence": "daily"},
    {"ingester": "corporate_actions",           "cadence": "event"},
    {"ingester": "rbi_yields",                  "cadence": "daily"},
    {"ingester": "fred_macro",                  "cadence": "daily"},
    {"ingester": "nse_calendar",                "cadence": "monthly"},
    {"ingester": "index_constituents",          "cadence": "monthly"},
    {"ingester": "snapshot_builder",            "cadence": "daily"},
    {"ingester": "yfinance_backfill",           "cadence": "event"},
    # Phase 1B — fundamentals + adjusted prices + sector + F&O
    {"ingester": "nse_financials",              "cadence": "quarterly"},
    {"ingester": "nse_shareholding",            "cadence": "quarterly"},
    {"ingester": "price_adjuster",              "cadence": "event"},
    {"ingester": "nse_equity_master",           "cadence": "monthly"},
    {"ingester": "fno_bhavcopy",                "cadence": "daily"},
    # Phase 1B — corporate announcements (S4) + classifier + document parser (S5)
    {"ingester": "corporate_announcements_nse", "cadence": "high-freq"},
    {"ingester": "corporate_announcements_bse", "cadence": "high-freq"},
    {"ingester": "announcement_classifier",     "cadence": "event"},
    {"ingester": "document_parser",             "cadence": "event"},
    # Mutual fund pipeline (added in VM-cron migration)
    {"ingester": "amfi_nav",                    "cadence": "daily"},
    {"ingester": "amfi_circulars",              "cadence": "daily"},
    {"ingester": "amfi_nav_history",            "cadence": "manual"},
    {"ingester": "mf_disclosure_snapshot",      "cadence": "monthly"},
    {"ingester": "mf_holdings",                 "cadence": "monthly"},
    # Corporate event intelligence pipeline
    {"ingester": "event_calendar",              "cadence": "daily"},
    {"ingester": "event_day_poller",            "cadence": "high-freq"},
    {"ingester": "d1_prep",                     "cadence": "daily"},
    {"ingester": "intelligence",                "cadence": "daily"},
    # Post-ingestion quality pipeline
    {"ingester": "quality_gate",                "cadence": "daily"},
    # Intelligence layer (NIDP Phase 2 — security_master/dq/features/graph/events/analytics)
    {"ingester": "intelligence_layer",          "cadence": "daily"},
    {"ingester": "portfolio_intelligence_sync", "cadence": "daily"},
]

GCP_PROJECT = os.environ.get("GCP_PROJECT", "niveshdataintelligence")
GCP_REGION  = os.environ.get("GCP_REGION",  "asia-south1")

# Public URL of the NIDP Grafana dashboard running on the VM. Surfaced
# in /diag and /jobs responses so the NIDP Console can render a CTA
# link straight to the "NIDP Job Health" board.
GRAFANA_BASE_URL = (
    os.environ.get("NIDP_GRAFANA_URL")
    or "http://34.93.60.254:3000"
).rstrip("/")
# kiosk=tv hides the top nav + sidebar + theme picker → clean dashboard
# pane suitable for embedding inside the Nivesh admin console iframe or
# as a "click-to-open" tab. Anonymous-Admin SSO (configured in Grafana)
# means no login prompt either way.
GRAFANA_DASHBOARD_PATH = "/d/nidp-job-health/nidp-job-health?kiosk=tv&theme=dark"
# Embedded URL is served via the pod's HTTPS proxy below (`/api/admin/nidp/grafana/*`)
# so the iframe is same-origin HTTPS — avoids the mixed-content block
# browsers apply to HTTP iframes inside HTTPS pages.
GRAFANA_EMBED_PATH     = "/api/admin/nidp/grafana/d/nidp-job-health/nidp-job-health?kiosk=tv&theme=dark&refresh=30s"


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


@router.get("/diag")
async def diag(request: Request) -> Dict[str, Any]:
    """Connection diagnostics — what URL admin_nidp is trying, whether
    NIDP Query API is reachable + authenticated, plus whether the local
    app Postgres pool connects. The first row tells you whether the
    admin console can talk to the GCP-side warehouse at all."""
    await require_admin(request)

    cfg = _nq.config_summary()

    # ── NIDP Query API reachability ─────────────────────────────────
    nidp_health, nidp_err = None, None
    try:
        nidp_health = await _nq.get_health()
    except _nq.NidpQueryClientError as e:
        nidp_err = e.detail
    except Exception as e:                                            # noqa: BLE001
        nidp_err = f"{type(e).__name__}: {str(e)[:300]}"

    # Gate the auth check on health succeeding — running /catalog on a
    # broken /health is just noise.
    nidp_auth_ok, nidp_auth_err = False, None
    if nidp_health is not None:
        try:
            await _nq.get_feeds()
            nidp_auth_ok = True
        except _nq.NidpQueryClientError as e:
            nidp_auth_err = e.detail

    # ── App Postgres pool (unchanged probe) ─────────────────────────
    app_url  = os.environ.get("POSTGRES_URL")
    app_ok, app_err = False, None
    try:
        from services import pg_client as _appc
        pool = await _appc.get_pool()
        if pool is None:
            app_err = "pg_client returned None (POSTGRES_URL missing or connect failed)"
        else:
            async with pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            app_ok = True
    except Exception as e:                                            # noqa: BLE001
        app_err = f"{type(e).__name__}: {str(e)[:300]}"

    return {
        "env": {
            "NIDP_QUERY_API_URL_set":   cfg["url_set"],
            "NIDP_QUERY_API_TOKEN_set": cfg["token_set"],
            "NIDP_QUERY_API_URL":       cfg["url"],
            "POSTGRES_URL_set":         bool(app_url),
        },
        "nidp_query_api": {
            "reachable":    nidp_health is not None,
            "health":       nidp_health,
            "reach_error":  nidp_err,
            "auth_ok":      nidp_auth_ok,
            "auth_error":   nidp_auth_err,
        },
        "app_pool":  {"ok": app_ok, "error": app_err},
        "hint": (
            "Set NIDP_QUERY_API_URL + NIDP_QUERY_API_TOKEN secrets if "
            "url_set/token_set are false. If reachable=false, the API "
            "service can't egress to Cloud Run — check Emergent platform "
            "egress / firewall. If auth_ok=false, the token doesn't "
            "match the one stored in GCP Secret Manager."
        ),
    }


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

    # ── Feed status from the NIDP Query API ─────────────────────────
    # Was an in-process v_feed_status query; now proxied because the
    # API service can't reach the GCP-private NIDP Postgres directly.
    db_status: Dict[str, Dict[str, Any]] = {}
    db_error: Optional[str] = None
    try:
        feeds_resp = await _nq.get_feeds()
        # Pass-through every field the query API returns so the React
        # panel sees last_success_at, schedule_cron, last_7_days,
        # cloud_logs_url, etc. Strip 'ingester' since it's the dict key.
        for f in feeds_resp.get("feeds", []):
            ing = f["ingester"]
            db_status[ing] = {k: v for k, v in f.items() if k != "ingester"}
        # Surface server-side error (e.g. v_feed_status missing on the
        # remote DB) rather than silently returning empty status.
        if feeds_resp.get("error"):
            db_error = feeds_resp["error"]
    except _nq.NidpQueryClientError as e:
        db_error = e.detail
        logger.warning("admin/nidp/jobs: query api unavailable: %s", db_error)

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

    # Drift detection: ingesters listed in v_feed_status but NOT in
    # NIDP_INGESTERS (= newly deployed services this code doesn't know
    # about) and the inverse (registered here but no rows in
    # source_registry, = job exists but has never run / source_registry
    # never seeded).
    canonical = {i["ingester"] for i in NIDP_INGESTERS}
    in_db     = set(db_status.keys())
    drift = {
        "missing_from_db":          sorted(canonical - in_db),     # known but unregistered
        "unregistered_in_canonical": sorted(in_db - canonical),    # in DB but UI doesn't know
    }

    # Surface the most-recent trading day so the frontend can default
    # the date picker without making a second call. Picks the most
    # recent weekday <= today (in IST). Real holiday-aware logic lives
    # in `nidp_calendar` — this is a sane MVP default.
    from datetime import date, timedelta, timezone, datetime as _dt
    ist = timezone(timedelta(hours=5, minutes=30))
    today_ist = _dt.now(ist).date()
    last_trading_day = today_ist
    while last_trading_day.weekday() >= 5:   # 5=Sat, 6=Sun
        last_trading_day -= timedelta(days=1)

    return {
        "project":   GCP_PROJECT,
        "region":    GCP_REGION,
        "db_error":  db_error,
        "drift":     drift,
        "grafana_url": f"{GRAFANA_BASE_URL}{GRAFANA_DASHBOARD_PATH}",
        "grafana_embed_url": GRAFANA_EMBED_PATH,
        "last_trading_day":  last_trading_day.isoformat(),
        "jobs": [
            {
                **spec,
                "job_name":   _job_name(spec["ingester"]),
                "image":      images.get(spec["ingester"]),
                "registered_in_db": spec["ingester"] in in_db,
                **db_status.get(spec["ingester"], {}),
            }
            for spec in NIDP_INGESTERS
        ],
    }


@router.post("/jobs/{ingester}/execute")
async def execute_job(
    ingester: str,
    request: Request,
    target_date: Optional[str] = Query(
        None,
        description="ISO date (YYYY-MM-DD) for the run; defaults to last trading day on the VM.",
        regex=r"^\d{4}-\d{2}-\d{2}$",
    ),
) -> Dict[str, Any]:
    """Trigger an ingester run for the given target date. Routes through
    the NIDP Query API on the VM (which spawns run_service.sh detached).
    Returns immediately — UI polls /jobs/{ingester}/runs to see the
    job_log row land."""
    await require_admin(request)
    _ingester_or_404(ingester)

    # ── Primary path: VM via query_api ──────────────────────────────
    if _nq.is_configured():
        try:
            resp = await _nq.execute_feed(ingester, target_date=target_date)
            logger.info(
                "admin/nidp: spawned %s on VM via query_api (date=%s)",
                ingester, target_date or "default",
            )
            return {
                "ok":          True,
                "ingester":    ingester,
                "job_name":    _job_name(ingester),
                "target_date": target_date,
                "via":         "vm",
                "status":      resp.get("status", "spawned"),
                "hint":        resp.get("hint"),
            }
        except _nq.NidpQueryClientError as e:
            logger.warning("admin/nidp: VM execute failed for %s: %s — falling back to gcloud", ingester, e.detail)

    # ── Legacy path: gcloud Cloud Run jobs (deprecated) ─────────────
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
    logger.info("admin/nidp: triggered %s via gcloud (execution=%s)", job, execution_name)
    return {
        "ok":             True,
        "ingester":       ingester,
        "job_name":       job,
        "via":            "gcloud",
        "execution_name": execution_name,
    }


@router.get("/jobs/{ingester}/calendar")
async def job_calendar(
    ingester: str,
    request: Request,
    days: int = Query(7, ge=1, le=30),
) -> Dict[str, Any]:
    """Per-day status strip for the last N days (default 7). Used by the
    Console's week-view widget. Pass-through to the NIDP Query API."""
    await require_admin(request)
    _ingester_or_404(ingester)

    try:
        return await _nq.get_feed_calendar(ingester, days=days)
    except _nq.NidpQueryClientError as e:
        logger.warning("admin/nidp/jobs/%s/calendar: query api error: %s", ingester, e.detail)
        return {"ingester": ingester, "days": days, "calendar": [], "error": e.detail}


@router.get("/jobs/{ingester}/runs")
async def job_runs(
    ingester: str,
    request: Request,
    limit: int = Query(20, ge=1, le=100),
) -> Dict[str, Any]:
    """Last N rows from nidp.job_log for this ingester (proxied through
    the NIDP Query API, which already shapes the response)."""
    await require_admin(request)
    _ingester_or_404(ingester)

    try:
        return await _nq.get_feed_runs(ingester, limit=limit)
    except _nq.NidpQueryClientError as e:
        logger.warning("admin/nidp/jobs/%s/runs: query api error: %s", ingester, e.detail)
        return {"ingester": ingester, "runs": [], "error": e.detail}


@router.get("/jobs/{ingester}/logs")
async def job_logs(
    ingester: str,
    request: Request,
    window: str = Query("4h", description="Legacy gcloud freshness window (only used in fallback)."),
    limit: int = Query(200, ge=1, le=2000),
) -> Dict[str, Any]:
    """Tail logs for this ingester. VM-mode reads
    /opt/nidp/logs/<ingester>/<ingester>.log via the query_api;
    falls back to `gcloud logging read` against Cloud Run if the
    query_api isn't configured."""
    await require_admin(request)
    _ingester_or_404(ingester)
    job = _job_name(ingester)

    # ── Primary path: VM logs via query_api ─────────────────────────
    if _nq.is_configured():
        try:
            resp = await _nq.get_feed_logs(ingester, lines=limit)
            return {
                "ingester": ingester,
                "job_name": job,
                "via":      "vm",
                "log_path": resp.get("log_path"),
                "lines":    resp.get("lines") or [],
                "error":    resp.get("error"),
            }
        except _nq.NidpQueryClientError as e:
            logger.warning("admin/nidp: VM logs unavailable for %s: %s — falling back to gcloud", ingester, e.detail)

    # ── Legacy path: gcloud Cloud Run logs (deprecated) ─────────────
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
        "via":      "gcloud",
        "window":   window,
        "lines":    [l for l in out.splitlines() if l.strip()],
    }


# ────────────────────────────────────────────────────────────────────
# Catalog — proxied through the NIDP Query API. The canonical
# _CATALOG_TABLES list now lives in
# backend/nidp/services/query_api/routers/catalog.py.
# ────────────────────────────────────────────────────────────────────


@router.get("/catalog")
async def catalog(request: Request) -> Dict[str, Any]:
    """Holistic NIDP data catalog — proxies three NIDP Query API calls
    in parallel and merges into the single payload the React panel binds
    to. Tables/by_domain come from /catalog, feeds from /feeds, and
    validation runs from /validation. Each is independent: a failure in
    one section returns a partial catalog rather than a 500."""
    await require_admin(request)

    if not _nq.is_configured():
        raise HTTPException(
            status_code=503,
            detail=(
                "NIDP Query API not configured — set NIDP_QUERY_API_URL "
                "and NIDP_QUERY_API_TOKEN secrets. Hit "
                "/api/admin/nidp/diag for full env state."
            ),
        )

    catalog_r, feeds_r, val_r = await asyncio.gather(
        _nq.get_catalog(),
        _nq.get_feeds(),
        _nq.get_validation(limit=50),
        return_exceptions=True,
    )

    # Catalog is the load-bearing call — if it failed, no point rendering
    # the page; surface the error as 502 so the panel's red error card
    # shows a precise reason.
    if isinstance(catalog_r, Exception):
        detail = (catalog_r.detail
                  if isinstance(catalog_r, _nq.NidpQueryClientError)
                  else f"{type(catalog_r).__name__}: {catalog_r}")
        raise HTTPException(status_code=502,
                            detail=f"NIDP Query API /catalog failed: {detail}")

    feeds = feeds_r.get("feeds", []) if isinstance(feeds_r, dict) else []
    if isinstance(feeds_r, Exception):
        logger.warning("catalog: feeds proxy failed: %s", feeds_r)

    validation = val_r.get("validation", []) if isinstance(val_r, dict) else []
    if isinstance(val_r, Exception):
        logger.warning("catalog: validation proxy failed: %s", val_r)

    # /catalog reports its own table count; we add feed count locally.
    totals = dict(catalog_r.get("totals") or {})
    totals["feeds"] = len(feeds)

    return {
        "as_of":      catalog_r.get("as_of") or (datetime.utcnow().isoformat() + "Z"),
        "totals":     totals,
        "by_domain":  catalog_r.get("by_domain", []),
        "tables":     catalog_r.get("tables", []),
        "feeds":      feeds,
        "validation": validation,
    }


# ────────────────────────────────────────────────────────────────────
# Quality Dashboard — proxied to the NIDP Query API quality endpoints
# ────────────────────────────────────────────────────────────────────


def _quality_503():
    raise HTTPException(
        status_code=503,
        detail=(
            "NIDP Query API not configured — set NIDP_QUERY_API_URL "
            "and NIDP_QUERY_API_TOKEN secrets."
        ),
    )


@router.get("/quality/expectations")
async def quality_expectations(request: Request) -> Dict[str, Any]:
    """Documentation endpoint: every Great-Expectations suite the
    NIDP `quality_gate` runs, with the column, kwargs and rule type
    for each expectation. Surfaced as the 'Expectations' tab in the
    admin console's Data Quality page."""
    await require_admin(request)
    # Lazy-import so the pod doesn't hard-depend on the GE engine
    # if the VM-side code path is ever refactored.
    try:
        from nidp.services.quality_gate.great_expectations_suites import documentation
        spec = documentation()
    except Exception as e:                                               # noqa: BLE001
        logger.exception("ge documentation failed")
        raise HTTPException(status_code=500, detail=f"ge_docs: {e}") from e

    # Friendly metadata so the UI can render a nice header.
    feeds = sorted(spec.keys())
    total_expectations = sum(len(s["expectations"]) for s in spec.values())
    return {
        "feeds_total":         len(feeds),
        "expectations_total":  total_expectations,
        "feeds":               spec,
        "doc_url":             "/api/admin/nidp/quality/expectations",
        "spec_source":         "NIDP_Sample_Feed_Expectation_Rules.docx + domain defaults",
    }


# ─────────────────────────────────────────────────────────────────
# AI-assisted DQ — pod-side proxy to NIDP DaaS /v1/dq/*
# ─────────────────────────────────────────────────────────────────
# Internal token injection happens here so the React UI only needs
# the user's session cookie (the standard admin auth). Frontend never
# sees NIDP_DAAS_API_KEY.

@router.api_route(
    "/dq/{tail:path}",
    methods=["GET", "POST", "PATCH", "DELETE"],
    summary="Authenticated proxy to NIDP DaaS /v1/dq/*",
)
async def dq_proxy(tail: str, request: Request) -> StreamingResponse:
    await require_admin(request)

    base = os.environ.get("NIDP_DAAS_BASE_URL") or _secrets.get("NIDP_DAAS_BASE_URL")
    key  = os.environ.get("NIDP_DAAS_API_KEY")  or _secrets.get("NIDP_DAAS_API_KEY")
    if not base or not key:
        raise HTTPException(
            status_code=503,
            detail="NIDP_DAAS_BASE_URL / NIDP_DAAS_API_KEY not configured",
        )

    upstream = f"{base.rstrip('/')}/v1/dq/{tail}"
    if request.url.query:
        upstream += f"?{request.url.query}"

    body = await request.body() if request.method in ("POST", "PUT", "PATCH") else None
    headers = {"X-API-Key": key, "Content-Type": "application/json", "Accept": "application/json"}

    try:
        # generate-all may take a while (LLM × N feeds); allow up to 8 min
        timeout = 480 if "generate-all" in tail else 90
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.request(request.method, upstream, headers=headers, content=body)
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"dq proxy: {e}") from e

    return StreamingResponse(
        iter([r.content]),
        status_code=r.status_code,
        media_type=r.headers.get("content-type", "application/json"),
    )


@router.get("/quality/summary")
async def quality_summary(
    request: Request,
    domain: Optional[str] = Query(None),
) -> Dict[str, Any]:
    """Aggregated quality snapshot — quality scores + certification + gate per domain."""
    await require_admin(request)
    if not _nq.is_configured():
        _quality_503()

    quality_r, cert_r, gate_r, exc_r = await asyncio.gather(
        _nq.get_quality(domain=domain, limit=90),
        _nq.get_certification(domain=domain, limit=90),
        _nq.get_publish_gate(domain=domain, limit=30),
        _nq.get_exception_queue(resolved=False, limit=50),
        return_exceptions=True,
    )

    def _safe(r, key):
        return r.get(key, []) if isinstance(r, dict) else []

    return {
        "quality":     _safe(quality_r,  "quality"),
        "certified":   _safe(cert_r,     "certified"),
        "gate":        _safe(gate_r,     "gate"),
        "exceptions":  _safe(exc_r,      "exceptions"),
        "errors": {
            "quality":    str(quality_r) if isinstance(quality_r, Exception) else None,
            "certified":  str(cert_r)    if isinstance(cert_r,    Exception) else None,
            "gate":       str(gate_r)    if isinstance(gate_r,    Exception) else None,
            "exceptions": str(exc_r)     if isinstance(exc_r,     Exception) else None,
        },
    }


@router.get("/quality/consistency")
async def quality_consistency(
    request: Request,
    domain: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=500),
) -> Dict[str, Any]:
    """Consistency runs + findings in one call."""
    await require_admin(request)
    if not _nq.is_configured():
        _quality_503()

    runs_r, findings_r = await asyncio.gather(
        _nq.get_consistency(domain=domain, limit=30),
        _nq.get_consistency_findings(domain=domain, severity=severity, limit=limit),
        return_exceptions=True,
    )

    return {
        "runs":     runs_r.get("consistency", [])  if isinstance(runs_r,     dict) else [],
        "findings": findings_r.get("findings", []) if isinstance(findings_r, dict) else [],
        "errors": {
            "runs":     str(runs_r)     if isinstance(runs_r,     Exception) else None,
            "findings": str(findings_r) if isinstance(findings_r, Exception) else None,
        },
    }


@router.get("/quality/exceptions")
async def quality_exceptions(
    request: Request,
    resolved: bool = Query(False),
    limit: int = Query(100, ge=1, le=200),
) -> Dict[str, Any]:
    """Exception queue — unresolved REVIEW items awaiting ops action."""
    await require_admin(request)
    if not _nq.is_configured():
        _quality_503()
    try:
        return await _nq.get_exception_queue(resolved=resolved, limit=limit)
    except _nq.NidpQueryClientError as e:
        raise HTTPException(status_code=502, detail=e.detail) from e


@router.patch("/quality/exceptions/{queue_id}")
async def resolve_exception(
    queue_id: str,
    request:  Request,
    action:          str = Query(..., description="APPROVE | REJECT | OVERRIDE | ESCALATE"),
    resolution_note: str = Query(""),
) -> Dict[str, Any]:
    """Resolve or override an exception queue item (ops action)."""
    await require_admin(request)
    if not _nq.is_configured():
        _quality_503()
    try:
        return await _nq.resolve_exception(
            queue_id=queue_id,
            action=action,
            resolution_note=resolution_note,
            resolved_by=getattr(request.state, "user_email", "ops"),
        )
    except _nq.NidpQueryClientError as e:
        raise HTTPException(status_code=502, detail=e.detail) from e


@router.get("/quality/quarantine")
async def quality_quarantine(
    request: Request,
    domain:  Optional[str] = Query(None),
    limit:   int           = Query(50, ge=1, le=200),
) -> Dict[str, Any]:
    """Dates condemned by the quality gate (FAIL → quarantine_log).
    Returns empty list gracefully if the Query API hasn't been redeployed
    with the /quarantine endpoint yet (404 from upstream → empty response).
    """
    await require_admin(request)
    if not _nq.is_configured():
        _quality_503()
    try:
        return await _nq.get_quarantine(domain=domain, limit=limit)
    except _nq.NidpQueryClientError as e:
        if e.status == 404:
            # Query API not yet redeployed — return empty rather than error
            return {"quarantine": [], "error": "endpoint not yet available on Query API"}
        raise HTTPException(status_code=502, detail=e.detail) from e


# ─────────────────────────────────────────────────────────────────
# Grafana HTTPS reverse-proxy
# ─────────────────────────────────────────────────────────────────
# Modern browsers block HTTP iframes inside HTTPS pages (mixed-content).
# The pod admin console is served over HTTPS but Grafana on the VM is
# plain HTTP on :3000 — without TLS termination there, the iframe
# silently renders a blank body. Solution: same-origin HTTPS proxy.
#
# We forward the full HTTP request (path + query + body) to the VM's
# Grafana, strip frame-blocking headers from the response, and stream
# the body back. Anonymous-Admin SSO on Grafana means we don't need
# to inject any auth — Grafana treats every request as Admin already.
# Access to this proxy is gated by `require_admin` like every other
# endpoint in this router.

_GRAFANA_BLOCKED_REQ_HEADERS = {
    "host", "content-length", "connection", "accept-encoding",
}
_GRAFANA_BLOCKED_RESP_HEADERS = {
    # Frame-blockers (the whole point of proxying):
    "x-frame-options", "content-security-policy",
    # Hop-by-hop:
    "transfer-encoding", "connection", "keep-alive",
    "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "upgrade",
    # Response-encoding (we stream raw so let httpx decompress upstream
    # then we re-emit without compression):
    "content-encoding", "content-length",
}


@router.api_route(
    "/grafana/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    include_in_schema=False,
)
async def grafana_proxy(path: str, request: Request):
    await require_admin(request)
    upstream = f"{GRAFANA_BASE_URL}/{path}"
    if request.url.query:
        upstream += f"?{request.url.query}"

    # Forward request headers (minus the ones that would confuse the
    # upstream or that httpx will set itself).
    fwd_headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in _GRAFANA_BLOCKED_REQ_HEADERS
    }
    body = await request.body() if request.method in ("POST", "PUT", "PATCH") else None

    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            r = await client.request(
                request.method,
                upstream,
                headers=fwd_headers,
                content=body,
            )
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"grafana proxy: {e}") from e

    resp_headers = {
        k: v for k, v in r.headers.items()
        if k.lower() not in _GRAFANA_BLOCKED_RESP_HEADERS
    }
    return StreamingResponse(
        iter([r.content]),
        status_code=r.status_code,
        headers=resp_headers,
        media_type=r.headers.get("content-type"),
    )


# ─────────────────────────────────────────────────────────────────
# Raw feed-file archive
# ─────────────────────────────────────────────────────────────────
# The VM keeps every raw download under /opt/nidp/archive/<ingester>/
# <YYYY-MM-DD>/<filename>. These endpoints expose listing + download
# through the same admin auth as the rest of the console.

@router.get("/archive/{ingester}")
async def list_archive(
    ingester: str,
    request: Request,
    target_date: Optional[str] = Query(
        None, regex=r"^\d{4}-\d{2}-\d{2}$",
        description="If set, list files only for this date.",
    ),
    limit_dates: int = Query(30, ge=1, le=365),
) -> Dict[str, Any]:
    await require_admin(request)
    _ingester_or_404(ingester)
    if not _nq.is_configured():
        raise HTTPException(status_code=503, detail="NIDP_QUERY_API not configured")
    try:
        return await _nq.list_archive(ingester, target_date=target_date, limit_dates=limit_dates)
    except _nq.NidpQueryClientError as e:
        raise HTTPException(status_code=502, detail=e.detail) from e


@router.get("/archive/{ingester}/{target_date}/{filename:path}")
async def download_archive(
    ingester: str,
    target_date: str,
    filename: str,
    request: Request,
):
    await require_admin(request)
    _ingester_or_404(ingester)
    if not _nq.is_configured():
        raise HTTPException(status_code=503, detail="NIDP_QUERY_API not configured")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", target_date):
        raise HTTPException(status_code=400, detail="invalid target_date")
    # Disallow path traversal: filename may have one slash for sub-prefix
    # but no `..` or absolute paths.
    if ".." in filename or filename.startswith("/"):
        raise HTTPException(status_code=400, detail="invalid filename")

    upstream = f"{_nq.base_url()}/archive/{ingester}/{target_date}/{filename}"
    headers = {"Authorization": f"Bearer {_nq.token()}"}
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.get(upstream, headers=headers)
            r.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text[:500]) from e
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    return StreamingResponse(
        iter([r.content]),
        media_type=r.headers.get("content-type", "application/octet-stream"),
        headers={
            "Content-Disposition": f'attachment; filename="{Path(filename).name}"',
        },
    )
