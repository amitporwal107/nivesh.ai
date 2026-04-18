"""MF data + Phase 2/3 admin dashboard endpoints."""
from fastapi import APIRouter, Request, HTTPException, Query
from typing import Optional

from deps import get_current_user, db, require_admin
from services import fund_data_resolver, pg_client, pg_writer, redis_client, mf_scheduler

router = APIRouter(prefix="/api")


# ── Public (authenticated user) ──────────────────────────────────────────
@router.get("/mf/holdings")
async def get_mf_holdings(
    request: Request,
    scheme_name: str = Query(...),
    scheme_code: Optional[str] = Query(None),
    isin: Optional[str] = Query(None),
    slug: Optional[str] = Query(None),
    force: bool = Query(False),
):
    await get_current_user(request)
    return await fund_data_resolver.get_fund_data(
        scheme_name=scheme_name, scheme_code=scheme_code, isin=isin,
        explicit_slug=slug, force_refresh=force,
    )


@router.get("/mf/lookup")
async def lookup_mf(
    request: Request,
    scheme_name: Optional[str] = Query(None),
    scheme_code: Optional[str] = Query(None),
    isin: Optional[str] = Query(None),
):
    await get_current_user(request)
    if not any([scheme_name, scheme_code, isin]):
        raise HTTPException(status_code=400, detail="Provide scheme_name, scheme_code, or isin")
    resolved = await fund_data_resolver.resolve_instrument(scheme_name or "", scheme_code, isin)
    nav = None
    if resolved.get("instrument_id"):
        import uuid
        try:
            nav = await pg_client.latest_nav_by_uuid(uuid.UUID(resolved["instrument_id"]))
        except Exception:
            nav = None
    return {"resolved": resolved, "latest_nav": nav}


# ── Admin dashboard reads ────────────────────────────────────────────────
@router.get("/admin/mf/db-status")
async def mf_db_status(request: Request):
    await require_admin(request)
    return {
        "postgres": await pg_client.ping(),
        "redis": await redis_client.ping(),
        "scheduler": mf_scheduler.status(),
    }


@router.get("/admin/mf/funds")
async def list_funds(request: Request, limit: int = Query(200, ge=1, le=1000)):
    """Dashboard list: all MF instruments with latest scrape metadata."""
    await require_admin(request)
    return {"funds": await pg_writer.list_scraped_funds(limit=limit)}


@router.get("/admin/mf/funds/{instrument_id}")
async def fund_detail(request: Request, instrument_id: str):
    """Dashboard drill-down: holdings + ratios history + audit trail."""
    await require_admin(request)
    detail = await pg_writer.get_fund_detail(instrument_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Fund not found")
    return detail


@router.get("/admin/mf/audit-log")
async def list_audit(request: Request, limit: int = Query(100, ge=1, le=500)):
    await require_admin(request)
    return {"audit": await pg_writer.list_audit_log(limit=limit)}


@router.get("/admin/mf/scrape-queue")
async def list_scrape_queue(request: Request):
    await require_admin(request)
    pending = await db.scrape_queue.find({}, {"_id": 0}).sort("queued_at", 1).to_list(200)
    summary = {"queued": 0, "done": 0, "failed": 0}
    for p in pending:
        s = p.get("status", "queued")
        summary[s] = summary.get(s, 0) + 1
    return {"queue": pending, "summary": summary}


# ── Admin actions ────────────────────────────────────────────────────────
@router.post("/admin/mf/drain-queue")
async def admin_drain_queue(
    request: Request,
    max_items: int = Query(20, ge=1, le=100),
    force: bool = Query(False, description="Bypass off-hours gate"),
):
    await require_admin(request)
    return await fund_data_resolver.drain_queue(max_items=max_items, force=force)


@router.post("/admin/mf/scrape-now")
async def admin_scrape_now(
    request: Request,
    scheme_name: str,
    scheme_code: Optional[str] = None,
    isin: Optional[str] = None,
    slug: Optional[str] = None,
):
    await require_admin(request)
    return await fund_data_resolver.get_fund_data(
        scheme_name=scheme_name, scheme_code=scheme_code, isin=isin,
        explicit_slug=slug, force_refresh=True, allow_scrape=True,
    )


@router.post("/admin/mf/seed-portfolio-queue")
async def seed_portfolio_queue(request: Request, user_id: Optional[str] = None):
    """Bulk-queue all MF schemes from portfolios into the scrape queue."""
    await require_admin(request)
    return await fund_data_resolver.seed_portfolio_queue(user_id=user_id)


# ── Scheduler controls ───────────────────────────────────────────────────
@router.post("/admin/mf/scheduler/start")
async def scheduler_start(request: Request):
    await require_admin(request)
    mf_scheduler.start()
    return mf_scheduler.status()


@router.post("/admin/mf/scheduler/stop")
async def scheduler_stop(request: Request):
    await require_admin(request)
    mf_scheduler.stop()
    return mf_scheduler.status()
