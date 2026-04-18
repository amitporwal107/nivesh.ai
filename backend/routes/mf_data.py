"""Fund data API — serve holdings/sectors/split for AI Copilot look-through."""
from fastapi import APIRouter, Request, HTTPException, Query
from typing import Optional

from deps import get_current_user, db, require_admin
from services import fund_data_resolver, pg_client, redis_client

router = APIRouter(prefix="/api")


@router.get("/mf/holdings")
async def get_mf_holdings(
    request: Request,
    scheme_name: str = Query(..., description="Full scheme name from portfolio"),
    scheme_code: Optional[str] = Query(None, description="AMFI scheme code"),
    isin: Optional[str] = Query(None, description="ISIN (growth option preferred)"),
    slug: Optional[str] = Query(None, description="Groww slug override"),
    force: bool = Query(False, description="Force fresh scrape"),
):
    """Return fund holdings/sectors/split with Redis→Mongo cache + off-hours scrape.

    Resolves the instrument in Postgres `instrument_master` for a canonical
    ISIN-based cache key; falls back to scheme_code/name when pg unavailable.
    """
    await get_current_user(request)
    data = await fund_data_resolver.get_fund_data(
        scheme_name=scheme_name,
        scheme_code=scheme_code,
        isin=isin,
        explicit_slug=slug,
        force_refresh=force,
    )
    return data


@router.get("/mf/lookup")
async def lookup_mf(
    request: Request,
    scheme_name: Optional[str] = Query(None),
    scheme_code: Optional[str] = Query(None),
    isin: Optional[str] = Query(None),
):
    """Debug/utility: resolve scheme → instrument_master row + latest NAV."""
    await get_current_user(request)
    if not any([scheme_name, scheme_code, isin]):
        raise HTTPException(status_code=400, detail="Provide scheme_name, scheme_code, or isin")
    resolved = await fund_data_resolver.resolve_instrument(
        scheme_name or "", scheme_code, isin
    )
    nav = None
    if resolved.get("instrument_id"):
        nav = await pg_client.latest_nav(resolved["instrument_id"])
    return {"resolved": resolved, "latest_nav": nav}


# ── Admin endpoints ───────────────────────────────────────────────────────
@router.get("/admin/mf/db-status")
async def mf_db_status(request: Request):
    """Admin-only: probe Postgres and Redis connectivity."""
    await require_admin(request)
    return {
        "postgres": await pg_client.ping(),
        "redis": await redis_client.ping(),
    }


@router.get("/admin/mf/scrape-queue")
async def list_scrape_queue(request: Request):
    await require_admin(request)
    pending = await db.scrape_queue.find({}, {"_id": 0}).sort("queued_at", 1).to_list(200)
    grouped = {"queued": 0, "done": 0, "failed": 0}
    for p in pending:
        status = p.get("status", "queued")
        grouped[status] = grouped.get(status, 0) + 1
    return {"queue": pending, "summary": grouped}


@router.post("/admin/mf/drain-queue")
async def admin_drain_queue(request: Request, max_items: int = 20):
    await require_admin(request)
    return await fund_data_resolver.drain_queue(max_items=max_items)


@router.post("/admin/mf/scrape-now")
async def admin_scrape_now(
    request: Request,
    scheme_name: str,
    scheme_code: Optional[str] = None,
    isin: Optional[str] = None,
    slug: Optional[str] = None,
):
    """Admin-only: bypass off-hours gate and scrape immediately."""
    await require_admin(request)
    return await fund_data_resolver.get_fund_data(
        scheme_name=scheme_name,
        scheme_code=scheme_code,
        isin=isin,
        explicit_slug=slug,
        force_refresh=True,
        allow_scrape=True,
    )
