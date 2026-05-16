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

    # Cadence-aware staleness ceilings (in days). Beyond GAPS_max → EMPTY.
    # The check is applied for rolling / event-driven / monthly / quarterly /
    # one-shot feeds where "coverage over N trading days" is the wrong metric.
    STALENESS_CERT = {
        "rolling":       {"gold": 2,  "silver": 7,   "partial": 30,  "gaps": 90},
        "event-driven":  {"gold": 7,  "silver": 30,  "partial": 90,  "gaps": 365},
        "monthly":       {"gold": 35, "silver": 60,  "partial": 95,  "gaps": 365},
        "quarterly":     {"gold": 95, "silver": 130, "partial": 200, "gaps": 400},
        "weekly":        {"gold": 8,  "silver": 15,  "partial": 30,  "gaps": 90},
        "one-shot":      {"gold": 365,"silver": 365, "partial": 365, "gaps": 365},
    }

    def _staleness_cert(cadence: str, st: int | None, rows_n: int | None) -> str:
        """Cert tier from staleness for cadences where 90-day coverage is the wrong metric."""
        if not rows_n:
            return "EMPTY"
        if st is None:
            return "UNKNOWN"
        b = STALENESS_CERT.get(cadence, STALENESS_CERT["rolling"])
        if st <= b["gold"]:
            return "GOLD"
        if st <= b["silver"]:
            return "SILVER"
        if st <= b["partial"]:
            return "PARTIAL"
        if st <= b["gaps"]:
            return "GAPS"
        return "EMPTY"

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
        cadence     = (prov.get("cadence") or "unknown").lower()

        last_at = _parse_dt(last_at_str)
        first_at = _parse_dt(first_at_str)

        # Coverage classification — branch on cadence so monthly / rolling /
        # event-driven feeds aren't penalised against a daily-trading target.
        if date_col is None:
            # Snapshot tables — no date column. Coverage = "is there data?"
            coverage_pct = 1.0 if rows_count and rows_count > 0 else 0.0
            days_covered = None
            staleness_days = (today - last_at.date()).days if isinstance(last_at, datetime) else None
            window_first = first_at_str
            window_last = last_at_str
            cert = "GOLD" if (rows_count and rows_count > 0) else "EMPTY"
        elif not rows_count:
            # Genuinely empty table.
            coverage_pct = 0.0
            days_covered = 0
            staleness_days = None
            window_first = None
            window_last = None
            cert = "EMPTY"
        elif cadence in ("daily",):
            # Time-series — clip to window. Trading-day approximation.
            if last_at is None:
                # Rows exist but catalog couldn't determine first/last — fall back to "no info" cert.
                coverage_pct = 0.0
                days_covered = 0
                staleness_days = None
                window_first = None
                window_last = None
                cert = "UNKNOWN"
            else:
                last_d  = last_at.date() if isinstance(last_at, datetime) else last_at
                first_d = first_at.date() if isinstance(first_at, datetime) else first_at
                effective_first = max(first_d, window_start) if first_d else window_start
                effective_last  = min(last_d, today) if last_d else today
                if effective_last < effective_first:
                    days_covered = 0
                else:
                    span = (effective_last - effective_first).days + 1
                    days_covered = max(0, int(round(span * 5 / 7)))
                coverage_pct = min(1.0, days_covered / trading_target) if trading_target else 0.0
                staleness_days = (today - last_d).days if last_d else None
                window_first = effective_first.isoformat()
                window_last  = effective_last.isoformat()
                cert = certify(coverage_pct)
        else:
            # rolling / event-driven / monthly / quarterly / weekly / one-shot
            # → cert by staleness; coverage_pct is informational only.
            if last_at is None:
                # Rolling/event feed with rows but no last_at — show partial.
                coverage_pct = 0.0
                days_covered = 0
                staleness_days = None
                window_first = first_at_str
                window_last = None
                cert = "PARTIAL"  # have data, can't grade freshness
            else:
                last_d  = last_at.date() if isinstance(last_at, datetime) else last_at
                first_d = first_at.date() if isinstance(first_at, datetime) else first_at
                effective_first = max(first_d, window_start) if first_d else window_start
                effective_last  = min(last_d, today) if last_d else today
                span = max(0, (effective_last - effective_first).days + 1)
                days_covered = span if span > 0 else 0
                coverage_pct = min(1.0, days_covered / trading_target) if trading_target else 0.0
                staleness_days = (today - last_d).days if last_d else None
                window_first = effective_first.isoformat()
                window_last  = effective_last.isoformat()
                cert = _staleness_cert(cadence, staleness_days, rows_count)
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


class TriggerYfinanceReq(BaseModel):
    start_date:       date  = Field(default_factory=lambda: date(2006, 1, 1))
    end_date:         date  = Field(default_factory=date.today)
    symbols:          Optional[str] = Field(None, description="Comma-separated NSE symbols (default: Nifty 500)")
    concurrency:      int   = Field(default=4, ge=1, le=12)
    per_request_delay: float = Field(default=2.0, ge=0.5, le=10.0)

    @field_validator("end_date")
    @classmethod
    def _end_ge_start(cls, v: date, info: Any) -> date:
        s = info.data.get("start_date")
        if s and v < s:
            raise ValueError("end_date must be >= start_date")
        return v


class TriggerNavHistoryReq(BaseModel):
    scheme_codes:     Optional[str] = Field(None, description="Comma-separated scheme codes (default: all active)")
    from_date:        Optional[date] = None
    to_date:          Optional[date] = None
    concurrency:      int = Field(default=12, ge=1, le=20)
    only_stale_days:  int = Field(default=0, ge=0, description="0 = full backfill (recommended for initial run)")


class TriggerFinancialsReq(BaseModel):
    symbols:          Optional[str] = Field(None, description="Comma-separated NSE symbols (default: Nifty 500)")
    concurrency:      int = Field(default=5, ge=1, le=10)
    per_request_delay: float = Field(default=2.5, ge=1.0, le=10.0)
    only_missing:     bool = Field(default=False, description="Skip symbols already having ≥8 quarters")


@router.post(
    "/trigger/yfinance",
    summary="SSH → VM: launch yfinance 20-year price backfill (Priority 1a)",
)
async def trigger_yfinance(req: TriggerYfinanceReq, request: Request) -> Dict[str, Any]:
    """Triggers `python -m nidp.services.yfinance_backfill` on the NIDP VM.

    Default: 20 years of daily OHLCV for all Nifty 500 symbols.
    Populates `nidp.prices_eod` — unlocks 1Y/3Y/5Y CAGR, volatility,
    Sharpe, Beta, drawdown, stress tests, and tax cost basis.
    Runtime: ~5-6 hours at default concurrency.
    """
    user = await require_admin(request)
    init_by = _safe_initiator(user)
    log_path = f"/opt/nidp/logs/backfill/yfinance_{int(time.time())}.log"

    sym_arg = f"--symbols {shlex.quote(req.symbols)}" if req.symbols else ""
    inner = (
        f"/opt/nidp/venv/bin/python -m nidp.services.yfinance_backfill "
        f"--from {req.start_date.isoformat()} "
        f"--to {req.end_date.isoformat()} "
        f"--concurrency {req.concurrency} "
        f"--per-request-delay {req.per_request_delay} "
        f"{sym_arg}"
    ).strip()

    try:
        rc, out, err = await ssh_run_detached_as_nidp(inner, log_path=log_path)
    except SSHUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    if rc != 0:
        raise HTTPException(status_code=502, detail=f"VM SSH failed (rc={rc}): {(err or out)[:600]}")

    return {
        "ok":            True,
        "mode":          "yfinance",
        "log_path":      log_path,
        "initiated_by":  init_by,
        "estimated_runtime": "5-6 hours for Nifty 500 at default concurrency",
        "unlocks": ["1Y/3Y/5Y CAGR", "volatility", "Sharpe", "Beta", "drawdown",
                    "stress_tests (COVID/GFC)", "tax cost basis"],
        "command_echo":  inner,
        "ssh_stdout":    out.strip()[-400:],
    }


@router.post(
    "/trigger/nav-history",
    summary="SSH → VM: launch AMFI full NAV history backfill (Priority 1b)",
)
async def trigger_nav_history(req: TriggerNavHistoryReq, request: Request) -> Dict[str, Any]:
    """Triggers `python -m nidp.services.amfi_nav_history --only-stale-days 0` on VM.

    Fetches complete NAV history for all active MF schemes from MFAPI.in
    (which has data from scheme inception). Populates `nidp.mf_nav_daily`.
    Unlocks 1Y/3Y/5Y MF returns, rolling returns, MF stress tests, SIP projections.
    Runtime: ~1.5-2 hours at default concurrency (12 concurrent).
    """
    user = await require_admin(request)
    init_by = _safe_initiator(user)
    log_path = f"/opt/nidp/logs/backfill/nav_history_{int(time.time())}.log"

    codes_arg   = f"--scheme-codes {shlex.quote(req.scheme_codes)}" if req.scheme_codes else ""
    from_arg    = f"--from {req.from_date.isoformat()}" if req.from_date else ""
    to_arg      = f"--to {req.to_date.isoformat()}" if req.to_date else ""

    inner = (
        f"/opt/nidp/venv/bin/python -m nidp.services.amfi_nav_history "
        f"--only-stale-days {req.only_stale_days} "
        f"--concurrency {req.concurrency} "
        f"{codes_arg} {from_arg} {to_arg}"
    ).strip()

    try:
        rc, out, err = await ssh_run_detached_as_nidp(inner, log_path=log_path)
    except SSHUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    if rc != 0:
        raise HTTPException(status_code=502, detail=f"VM SSH failed (rc={rc}): {(err or out)[:600]}")

    return {
        "ok":            True,
        "mode":          "nav_history",
        "log_path":      log_path,
        "initiated_by":  init_by,
        "estimated_runtime": "1.5-2 hours for all active schemes",
        "unlocks": ["MF 1Y/3Y/5Y CAGR", "rolling returns", "MF volatility",
                    "MF stress tests", "SIP projections", "MF tax cost basis"],
        "command_echo":  inner,
        "ssh_stdout":    out.strip()[-400:],
    }


@router.post(
    "/trigger/financials",
    summary="SSH → VM: launch NSE quarterly financials batch backfill (Priority 2)",
)
async def trigger_financials(req: TriggerFinancialsReq, request: Request) -> Dict[str, Any]:
    """Triggers `python -m nidp.services.nse_financials_backfill` on the NIDP VM.

    Batch-scrapes NSE XBRL comparator for all Nifty 500 symbols (up to 8 quarters),
    then falls back to Screener.in for older quarters (up to 20 total).
    Populates `nidp.nse_financials_quarterly` — the single most critical missing dataset.

    Unlocks: EPS CAGR, Revenue CAGR, earnings consistency, debt trend,
    margin trend, ROE/ROCE, Piotroski F-Score, V3 quality score.
    Runtime: ~3-4 hours at default concurrency (NSE rate-limited).
    """
    user = await require_admin(request)
    init_by = _safe_initiator(user)
    log_path = f"/opt/nidp/logs/backfill/financials_{int(time.time())}.log"

    sym_arg     = f"--symbols {shlex.quote(req.symbols)}" if req.symbols else ""
    missing_arg = "--only-missing" if req.only_missing else ""

    inner = (
        f"/opt/nidp/venv/bin/python -m nidp.services.nse_financials_backfill "
        f"--concurrency {req.concurrency} "
        f"--delay {req.per_request_delay} "
        f"{sym_arg} {missing_arg}"
    ).strip()

    try:
        rc, out, err = await ssh_run_detached_as_nidp(inner, log_path=log_path)
    except SSHUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    if rc != 0:
        raise HTTPException(status_code=502, detail=f"VM SSH failed (rc={rc}): {(err or out)[:600]}")

    return {
        "ok":            True,
        "mode":          "financials",
        "log_path":      log_path,
        "initiated_by":  init_by,
        "estimated_runtime": "3-4 hours for Nifty 500 (NSE rate-limited)",
        "coverage": {
            "nse_xbrl":   "up to 8 quarters per symbol",
            "screener_in": "up to 20 quarters (fallback when NSE < 8 quarters)",
        },
        "unlocks": ["EPS_CAGR_3Y", "Revenue_CAGR_3Y", "earnings_consistency",
                    "debt_trend", "profit_margin_trend", "Piotroski_F_Score",
                    "V3_quality_score", "V3_health_score"],
        "command_echo":  inner,
        "ssh_stdout":    out.strip()[-400:],
    }


@router.post(
    "/trigger/price-adjuster",
    summary="SSH → VM: run price_adjuster to compute split/bonus-adjusted prices (run after yfinance)",
)
async def trigger_price_adjuster(
    request: Request,
    start_date: date = Query(default_factory=lambda: date(2006, 1, 1)),
    end_date:   date = Query(default_factory=date.today),
) -> Dict[str, Any]:
    """Triggers the price_adjuster ingester over the backfill window.

    Must be run AFTER yfinance_backfill completes. Computes split/bonus/dividend
    adjusted prices into `nidp.prices_eod_adjusted` — required for accurate
    multi-year return calculations.
    """
    user = await require_admin(request)
    init_by = _safe_initiator(user)
    log_path = f"/opt/nidp/logs/backfill/price_adj_{int(time.time())}.log"

    inner = (
        f"/opt/nidp/venv/bin/python -m nidp.services.backfill "
        f"--start-date {start_date.isoformat()} "
        f"--end-date {end_date.isoformat()} "
        f"--ingesters price_adjuster "
        f"--wipe-first false"
    )

    try:
        rc, out, err = await ssh_run_detached_as_nidp(inner, log_path=log_path)
    except SSHUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    if rc != 0:
        raise HTTPException(status_code=502, detail=f"VM SSH failed (rc={rc}): {(err or out)[:600]}")

    return {
        "ok":           True,
        "mode":         "price_adjuster",
        "log_path":     log_path,
        "initiated_by": init_by,
        "note":         "Run this AFTER yfinance backfill completes.",
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
