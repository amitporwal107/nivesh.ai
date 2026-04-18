"""Fund data API — serve holdings/sectors/split for AI Copilot look-through."""
from fastapi import APIRouter, Request, HTTPException, Query
from typing import Optional

from deps import get_current_user, db
from services import fund_data_resolver

router = APIRouter(prefix="/api")


@router.get("/mf/holdings")
async def get_mf_holdings(
    request: Request,
    scheme_name: str = Query(..., description="Full scheme name from portfolio"),
    instrument_id: Optional[str] = Query(None, description="UUID from instrument_master"),
    slug: Optional[str] = Query(None, description="Groww slug override"),
    force: bool = Query(False, description="Force fresh scrape"),
):
    await get_current_user(request)
    key = instrument_id or scheme_name.lower().strip()
    data = await fund_data_resolver.get_fund_data(
        instrument_key=key,
        scheme_name=scheme_name,
        explicit_slug=slug,
        force_refresh=force,
    )
    return data


@router.get("/admin/mf/scrape-queue")
async def list_scrape_queue(request: Request):
    """Admin-only: pending scrape queue."""
    from routes.admin import require_admin
    await require_admin(request)
    pending = await db.scrape_queue.find({}, {"_id": 0}).sort("queued_at", 1).to_list(200)
    grouped = {"queued": 0, "done": 0, "failed": 0}
    for p in pending:
        grouped[p.get("status", "queued")] = grouped.get(p.get("status", "queued"), 0) + 1
    return {"queue": pending, "summary": grouped}


@router.post("/admin/mf/drain-queue")
async def admin_drain_queue(request: Request, max_items: int = 20):
    """Admin-only: manually trigger off-hours queue drain."""
    from routes.admin import require_admin
    await require_admin(request)
    result = await fund_data_resolver.drain_queue(max_items=max_items)
    return result


@router.post("/admin/mf/scrape-now")
async def admin_scrape_now(request: Request, scheme_name: str, slug: Optional[str] = None):
    """Admin-only: bypass off-hours gate and scrape immediately."""
    from routes.admin import require_admin
    await require_admin(request)
    key = scheme_name.lower().strip()
    data = await fund_data_resolver.get_fund_data(
        instrument_key=key,
        scheme_name=scheme_name,
        explicit_slug=slug,
        force_refresh=True,
        allow_scrape=True,
    )
    return data
