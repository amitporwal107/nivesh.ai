"""Admin → NIDP → Backfill endpoints (pod-side proxy + readiness matrix + VM triggers).

Forwards `/api/admin/nidp/backfill/*` to the DaaS API on the NIDP VM
at `${NIDP_DAAS_BASE_URL}/v1/backfill/*`. The backfill orchestrator
runs as a detached subprocess on the VM; this router gates the admin
session, proxies read-only status endpoints, computes the local
**Backfill Readiness Matrix** by joining the VM's `/v1/catalog`
coverage stats with our provenance metadata map, and exposes two
SSH-driven triggers that kick off the orchestrators on the VM.
"""
from __future__ import annotations

import logging
import os
import re
import shlex
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from deps import require_admin
from routes._nidp_feed_provenance import PROVENANCE, certify, for_feed
from services.nidp_vm_ssh import SSHUnavailable, ssh_exec, ssh_run_detached_as_nidp
from services.nidp_vm_query import fetch_job_log

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin/nidp/backfill", tags=["admin-nidp-backfill"])


def _vm_creds() -> tuple[str, str]:
    base = os.environ.get("NIDP_DAAS_BASE_URL")
    key  = os.environ.get("NIDP_DAAS_API_KEY")
    if not base or not key:
        raise HTTPException(
            status_code=503,
            detail="NIDP_DAAS_BASE_URL / NIDP_DAAS_API_KEY not configured",
        )
    return base.rstrip("/"), key


# ──────────────────────────────────────────────────────────────────────
# /readiness — Backfill Readiness Matrix
#
# Pulls coverage stats from VM `/v1/catalog`, joins with our static
# provenance metadata, and computes per-feed certification.
#
# Query params:
#   target_days     — backfill window in calendar days (default 90)
#   only_mandatory  — filter to MANDATORY criticality (default false)
# ──────────────────────────────────────────────────────────────────────
@router.get("/readiness")
async def readiness(
    request: Request,
    target_days: int = Query(90, ge=1, le=3650),
    only_mandatory: bool = Query(False),
) -> Dict[str, Any]:
    await require_admin(request)
    base, key = _vm_creds()

    # 1. Pull live catalog (with row counts + first/last dates) from VM
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(
                f"{base}/v1/catalog",
                headers={"X-API-Key": key, "Accept": "application/json"},
            )
        if r.status_code != 200:
            raise HTTPException(status_code=502, detail=f"VM catalog HTTP {r.status_code}")
        catalog = r.json()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"readiness: VM unreachable — {e}") from e

    today = date.today()
    window_start = today - timedelta(days=target_days)
    # Rough trading-day target (~5/7 of calendar days)
    trading_target = max(1, int(round(target_days * 5 / 7)))

    # 2. Build the matrix row-by-row
    rows: List[Dict[str, Any]] = []
    cert_counts: Dict[str, int] = {}
    crit_counts: Dict[str, Dict[str, int]] = {}  # criticality → cert tier → n

    for ds in catalog.get("datasets", []):
        name        = ds["name"]
        prov        = for_feed(name)
        last_at_str = ds.get("last_at")
        first_at_str = ds.get("first_at")
        rows_count  = ds.get("rows")
        date_col    = ds.get("date_col")

        last_at = _parse_dt(last_at_str)
        first_at = _parse_dt(first_at_str)

        # Coverage classification
        if date_col is None:
            # Snapshot tables — no date column. Coverage = "is there data?"
            coverage_pct = 1.0 if rows_count and rows_count > 0 else 0.0
            days_covered = None
            staleness_days = (today - last_at.date()).days if isinstance(last_at, datetime) else None
            window_first = first_at_str
            window_last = last_at_str
        elif rows_count == 0 or rows_count is None or last_at is None:
            coverage_pct = 0.0
            days_covered = 0
            staleness_days = None
            window_first = None
            window_last = None
        else:
            # Time-series — clip to window and assume distinct dates ≈ trading days seen.
            # The catalog endpoint gives us first/last only; we approximate
            # days_covered = min(trading_target, span_days * 5/7).
            last_d  = last_at.date() if isinstance(last_at, datetime) else last_at
            first_d = first_at.date() if isinstance(first_at, datetime) else first_at
            effective_first = max(first_d, window_start) if first_d else window_start
            effective_last  = min(last_d, today) if last_d else today
            if effective_last < effective_first:
                days_covered = 0
            else:
                span = (effective_last - effective_first).days + 1
                # Use trading-day approximation for daily/event feeds
                if prov.get("cadence") in ("daily",):
                    days_covered = max(0, int(round(span * 5 / 7)))
                else:
                    days_covered = span
            coverage_pct = min(1.0, days_covered / trading_target) if trading_target else 0.0
            staleness_days = (today - last_d).days if last_d else None
            window_first = effective_first.isoformat()
            window_last  = effective_last.isoformat()

        cert = certify(coverage_pct)
        cert_counts[cert] = cert_counts.get(cert, 0) + 1
        crit = prov.get("criticality", "OPTIONAL")
        crit_counts.setdefault(crit, {}).setdefault(cert, 0)
        crit_counts[crit][cert] += 1

        if only_mandatory and crit != "MANDATORY":
            continue

        rows.append({
            # Identity
            "name":          name,
            "table":         ds.get("table"),
            "domain":        ds.get("domain"),
            "description":   ds.get("description"),
            # Provenance
            "source":        prov.get("source"),
            "source_url":    prov.get("source_url"),
            "retrieval":     prov.get("retrieval"),
            "ingester":      prov.get("ingester"),
            "cadence":       prov.get("cadence"),
            "depth":         prov.get("depth"),
            "criticality":   crit,
            "validation":    prov.get("validation", []),
            "prov_notes":    prov.get("notes"),
            # Live stats
            "rows":          rows_count,
            "first_at":      first_at_str,
            "last_at":       last_at_str,
            "window_first":  window_first,
            "window_last":   window_last,
            "days_covered":  days_covered,
            "days_target":   trading_target if (date_col and prov.get("cadence") == "daily") else None,
            "coverage_pct":  round(coverage_pct, 4),
            "staleness_days": staleness_days,
            "cert":          cert,
        })

    # 3. Overall readiness verdict
    mandatory_rows = [r for r in rows if r["criticality"] == "MANDATORY"]
    mand_gold = sum(1 for r in mandatory_rows if r["cert"] == "GOLD")
    mand_total = len(mandatory_rows) or 1
    mand_pct = mand_gold / mand_total

    if mand_pct >= 1.0:
        verdict = "READY"
        verdict_msg = "All MANDATORY feeds at GOLD coverage. Replay will run on real, robust data."
    elif mand_pct >= 0.80:
        verdict = "NEAR_READY"
        verdict_msg = (
            f"{mand_gold}/{mand_total} MANDATORY feeds at GOLD. "
            "Replay will partially use real data; run a backfill to close the gap."
        )
    else:
        verdict = "NOT_READY"
        verdict_msg = (
            f"Only {mand_gold}/{mand_total} MANDATORY feeds at GOLD. "
            "Do not run a 90-day replay yet — kick off a backfill first."
        )

    return {
        "as_of":            datetime.now(timezone.utc).isoformat(),
        "target_days":      target_days,
        "trading_target":   trading_target,
        "window_start":     window_start.isoformat(),
        "today":            today.isoformat(),
        "verdict":          verdict,
        "verdict_msg":      verdict_msg,
        "cert_counts":      cert_counts,
        "criticality_breakdown": crit_counts,
        "totals": {
            "datasets":         len(rows),
            "mandatory_total":  len(mandatory_rows),
            "mandatory_gold":   mand_gold,
            "mandatory_pct":    round(mand_pct, 4),
        },
        "rows":             rows,
    }


def _parse_dt(s: Optional[str]) -> Optional[datetime]:
    """Best-effort ISO parse — catalog can return either date or timestamp strings."""
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        try:
            return datetime.combine(date.fromisoformat(s), datetime.min.time())
        except ValueError:
            return None


# ──────────────────────────────────────────────────────────────────────
# VM trigger endpoints — SSH into the VM and start the orchestrator
# detached. The pod returns within seconds; UI polls /runs for progress.
# ──────────────────────────────────────────────────────────────────────
_DAILY_INGESTERS_ALLOWED = {"bhavcopy", "delivery", "index_close", "fno_bhavcopy"}
_ROLLING_SERVICES_ALLOWED = {
    "nse_calendar", "index_constituents",
    "bulk_deals", "block_deals", "corporate_actions",
    "rbi_yields", "fii_dii",
}
_SHELL_TOKEN = re.compile(r"^[A-Za-z0-9_,-]+$")


class TriggerDailyReq(BaseModel):
    start_date:    date
    end_date:      date
    ingesters:     List[str] = Field(min_length=1)
    wipe_first:    bool      = False
    politeness_ms: int       = Field(default=4000, ge=500, le=30000)
    parallel:      int       = Field(default=1, ge=1, le=8)

    @field_validator("ingesters")
    @classmethod
    def _validate(cls, v: List[str]) -> List[str]:
        bad = [i for i in v if i not in _DAILY_INGESTERS_ALLOWED]
        if bad:
            raise ValueError(
                f"unknown daily ingesters: {bad}. allowed={sorted(_DAILY_INGESTERS_ALLOWED)}"
            )
        return v


class TriggerRollingReq(BaseModel):
    start_date: date
    end_date:   date
    services:   List[str] = Field(min_length=1)
    skip_existing: bool   = True

    @field_validator("services")
    @classmethod
    def _validate(cls, v: List[str]) -> List[str]:
        bad = [s for s in v if s not in _ROLLING_SERVICES_ALLOWED]
        if bad:
            raise ValueError(
                f"unknown rolling services: {bad}. allowed={sorted(_ROLLING_SERVICES_ALLOWED)}"
            )
        return v


@router.post("/trigger/daily", summary="SSH into VM and launch nidp.services.backfill (daily NSE ingesters)")
async def trigger_daily(req: TriggerDailyReq, request: Request) -> Dict[str, Any]:
    user = await require_admin(request)
    if req.end_date < req.start_date:
        raise HTTPException(status_code=422, detail="end_date < start_date")
    ingesters_arg = ",".join(req.ingesters)
    if not _SHELL_TOKEN.match(ingesters_arg):
        raise HTTPException(status_code=422, detail="ingesters contain invalid characters")

    init_by = _safe_initiator(user)
    log_path = f"/opt/nidp/logs/backfill/daily_{int(time.time())}.log"

    inner = (
        f"/opt/nidp/venv/bin/python -m nidp.services.backfill "
        f"--start-date {req.start_date.isoformat()} "
        f"--end-date {req.end_date.isoformat()} "
        f"--ingesters {shlex.quote(ingesters_arg)} "
        f"--wipe-first {'true' if req.wipe_first else 'false'} "
        f"--politeness-ms {int(req.politeness_ms)} "
        f"--parallel {int(req.parallel)} "
        f"--auto-replay false "
        f"--initiated-by {shlex.quote(init_by)}"
    )

    try:
        rc, out, err = await ssh_run_detached_as_nidp(inner, log_path=log_path)
    except SSHUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    if rc != 0:
        raise HTTPException(
            status_code=502,
            detail=f"VM SSH failed (rc={rc}): {(err or out)[:600]}",
        )
    return {
        "ok":           True,
        "mode":         "daily",
        "log_path":     log_path,
        "initiated_by": init_by,
        "command_echo": inner,
        "ssh_stdout":   out.strip()[-400:],
    }


@router.post("/trigger/rolling", summary="SSH into VM and launch nidp.cli backfill (rolling + reference)")
async def trigger_rolling(req: TriggerRollingReq, request: Request) -> Dict[str, Any]:
    user = await require_admin(request)
    if req.end_date < req.start_date:
        raise HTTPException(status_code=422, detail="end_date < start_date")
    services_arg = ",".join(req.services)
    if not _SHELL_TOKEN.match(services_arg):
        raise HTTPException(status_code=422, detail="services contain invalid characters")

    init_by = _safe_initiator(user)
    log_path = f"/opt/nidp/logs/backfill/rolling_{int(time.time())}.log"

    skip_flag = "" if req.skip_existing else "--no-skip-existing"
    inner = (
        f"/opt/nidp/venv/bin/python -m nidp.cli backfill "
        f"--from {req.start_date.isoformat()} "
        f"--to {req.end_date.isoformat()} "
        f"--services {shlex.quote(services_arg)} {skip_flag}"
    ).strip()

    try:
        rc, out, err = await ssh_run_detached_as_nidp(inner, log_path=log_path)
    except SSHUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    if rc != 0:
        raise HTTPException(
            status_code=502,
            detail=f"VM SSH failed (rc={rc}): {(err or out)[:600]}",
        )
    return {
        "ok":           True,
        "mode":         "rolling",
        "log_path":     log_path,
        "initiated_by": init_by,
        "command_echo": inner,
        "ssh_stdout":   out.strip()[-400:],
    }


@router.get("/trigger/health", summary="Whether the pod can SSH into the NIDP VM")
async def trigger_health(request: Request) -> Dict[str, Any]:
    await require_admin(request)
    try:
        rc, out, err = await ssh_exec("whoami; hostname; uptime", timeout=20.0)
    except SSHUnavailable as e:
        return {"ok": False, "reason": str(e)}
    if rc != 0:
        return {"ok": False, "reason": f"rc={rc} stderr={err[:300]}"}
    return {"ok": True, "vm_echo": out.strip()[:400]}


@router.get(
    "/job_log",
    summary="Recent rows of nidp.job_log — covers rolling/reference ingesters not tracked in audit.backfill_runs",
)
async def job_log(
    request: Request,
    limit:       int = Query(50, ge=1, le=500),
    ingester:    Optional[str] = Query(None, max_length=64),
    status:      Optional[str] = Query(None, pattern="^(RUNNING|OK|FAILED|PARTIAL|SKIPPED)$"),
    since_hours: int = Query(24, ge=1, le=720),
) -> Dict[str, Any]:
    await require_admin(request)
    try:
        rows = await fetch_job_log(
            limit=limit, ingester=ingester, status=status, since_hours=since_hours,
        )
    except SSHUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    # Light per-row enrichment (re-use provenance metadata for the ingester chip)
    for r in rows:
        prov = for_feed(r.get("ingester") or "")
        r["source"]      = prov.get("source")
        r["criticality"] = prov.get("criticality")
    return {"rows": rows, "total": len(rows)}


def _safe_initiator(user: Any) -> str:
    """Best-effort short, shell-safe initiated_by tag (email or user_id)."""
    if isinstance(user, dict):
        ident = user.get("email") or user.get("user_id") or "ui"
    else:
        ident = getattr(user, "email", None) or getattr(user, "user_id", None) or "ui"
    ident = str(ident)[:64]
    return re.sub(r"[^A-Za-z0-9._@-]", "_", ident)


# ──────────────────────────────────────────────────────────────────────
# Generic proxy for /runs, /status/{id}, etc.
# ──────────────────────────────────────────────────────────────────────
@router.api_route(
    "/{tail:path}",
    methods=["GET", "POST", "DELETE"],
    summary="Authenticated proxy to NIDP DaaS /v1/backfill/*",
)
async def backfill_proxy(tail: str, request: Request) -> StreamingResponse:
    await require_admin(request)
    base, key = _vm_creds()

    upstream = f"{base}/v1/backfill/{tail}"
    if request.url.query:
        upstream += f"?{request.url.query}"

    body = await request.body() if request.method in ("POST", "PUT", "PATCH") else None
    headers = {"X-API-Key": key, "Accept": "application/json"}
    if body:
        headers["Content-Type"] = "application/json"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.request(request.method, upstream, headers=headers, content=body)
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"backfill proxy: {e}") from e

    return StreamingResponse(
        iter([r.content]),
        status_code=r.status_code,
        media_type=r.headers.get("content-type", "application/json"),
    )
