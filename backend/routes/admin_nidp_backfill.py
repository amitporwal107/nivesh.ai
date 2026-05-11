"""Admin → NIDP → Backfill endpoints (pod-side proxy + readiness matrix).

Forwards `/api/admin/nidp/backfill/*` to the DaaS API on the NIDP VM
at `${NIDP_DAAS_BASE_URL}/v1/backfill/*`. The backfill orchestrator
runs as a detached subprocess on the VM (kicked off via SSH); this
router gates the admin session, proxies read-only status endpoints,
and computes the local **Backfill Readiness Matrix** by joining the
VM's `/v1/catalog` coverage stats with our provenance metadata map.
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from deps import require_admin
from routes._nidp_feed_provenance import PROVENANCE, certify, for_feed

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
        if rows_count == 0 or rows_count is None or last_at is None:
            coverage_pct = 0.0
            days_covered = 0
            staleness_days = None
            window_first = None
            window_last = None
        elif date_col is None:
            # Snapshot tables — no date column, coverage based on "is there data"
            coverage_pct = 1.0 if rows_count and rows_count > 0 else 0.0
            days_covered = None
            staleness_days = (today - last_at.date()).days if isinstance(last_at, datetime) else None
            window_first = first_at_str
            window_last = last_at_str
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
