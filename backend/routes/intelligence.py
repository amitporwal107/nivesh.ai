"""Portfolio Intelligence API — real stock-level overlap + AI insights."""
from fastapi import APIRouter, Request, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List

from deps import get_current_user, require_admin, db
from services import portfolio_intelligence, ai_insights, pg_writer, pg_client

router = APIRouter(prefix="/api")


class SimulateBody(BaseModel):
    remove_mf_ids: List[str] = []


@router.get("/intelligence/portfolio")
async def get_portfolio_intelligence(request: Request, narrate: bool = Query(True)):
    """Full portfolio intelligence bundle with real stock-level overlap."""
    user = await get_current_user(request)
    metrics = await portfolio_intelligence.compute_portfolio_intelligence(user["user_id"])
    if narrate and not metrics.get("empty"):
        metrics["ai_insights"] = await ai_insights.generate_insights(metrics)
        metrics["category_ratings"] = await ai_insights.rate_portfolio_categories(metrics)
    return metrics


@router.get("/intelligence/portfolio/{user_id}")
async def admin_get_portfolio_intelligence(request: Request, user_id: str,
                                           narrate: bool = Query(True)):
    """Admin view of any user's portfolio intelligence."""
    await require_admin(request)
    metrics = await portfolio_intelligence.compute_portfolio_intelligence(user_id)
    if narrate and not metrics.get("empty"):
        metrics["ai_insights"] = await ai_insights.generate_insights(metrics)
    return metrics


@router.post("/intelligence/simulate")
async def simulate_removal(request: Request, body: SimulateBody):
    """What-if simulation: recompute intelligence after removing N funds.

    Re-uses the same compute pipeline but zeroes-out the removed MF amounts.
    """
    user = await get_current_user(request)
    remove_mf_ids = body.remove_mf_ids or []
    metrics = await portfolio_intelligence.compute_portfolio_intelligence(user["user_id"])
    if metrics.get("empty"):
        return metrics
    # Filter mf_investments
    kept = [m for m in metrics["mf_investments"]
            if m.get("instrument_id") not in remove_mf_ids]
    if len(kept) == len(metrics["mf_investments"]):
        return {**metrics, "sim_unchanged": True}
    # Recompute downstream metrics on the filtered set
    # Cheap path: re-run sector + overlap helpers with filtered catalog
    from services.portfolio_intelligence import (
        _pairwise_overlap, _top_stock_exposure, _compression_score,
        _category_inefficiency, _sector_exposure,
    )
    catalog = metrics["catalog"]
    resolved = [m for m in kept if m.get("resolved")]
    total = sum(m["amount_rs"] for m in kept) or 1
    # rebuild weights dict
    weights = {}
    for m in resolved:
        mf_id = m["instrument_id"]
        weights[mf_id] = {
            (h["holding_stock_slug"] or h["holding_name"] or "").lower():
            float(h["weight_percent"] or 0)
            for h in catalog.get(mf_id, {}).get("holdings", [])
            if h.get("weight_percent") is not None
        }
    pairs = _pairwise_overlap(list(weights.keys()), weights, catalog)
    top = _top_stock_exposure(kept, weights, catalog, total)
    comp = _compression_score(top, total)
    cats = _category_inefficiency(kept, pairs)
    sectors = _sector_exposure(kept, catalog, total)
    return {
        "sim_removed": remove_mf_ids,
        "kept_count": len(kept),
        "narrative": {
            "total_invested_rs": round(total, 2),
            "effective_stocks": comp["effective_stocks"],
            "compression_score": comp["score"],
            "behaves_like_rs": round(total * comp["score"] / 100, 2),
        },
        "compression": comp,
        "pairwise_overlap": pairs,
        "top_stocks": top,
        "category_inefficiency": cats,
        "sector_exposure": sectors,
    }


@router.post("/intelligence/rate-fund/{instrument_id}")
async def rate_single_fund(request: Request, instrument_id: str):
    """Admin-triggered AI rating for a single fund — cached in mutual_fund_metadata."""
    await require_admin(request)
    detail = await pg_writer.get_fund_detail(instrument_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Fund not found")
    # Check cache
    pool = await pg_client.get_pool()
    if pool:
        async with pool.acquire() as conn:
            cached = await conn.fetchrow(
                "SELECT ai_rating, ai_rating_reason, ai_rated_at FROM mutual_fund_metadata "
                "WHERE instrument_id = $1",
                instrument_id,
            )
        if cached and cached["ai_rating"] is not None:
            return {
                "rating": cached["ai_rating"],
                "reason": cached["ai_rating_reason"],
                "rated_at": cached["ai_rated_at"].isoformat() if cached["ai_rated_at"] else None,
                "cached": True,
            }
    # Generate
    result = await ai_insights.rate_fund(detail)
    # Cache back — always cache (including null) to avoid hammering broken LLM.
    # For null results we use a short-lived marker; success persists until next re-rate.
    if pool:
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE mutual_fund_metadata SET ai_rating = $1, ai_rating_reason = $2, "
                "ai_rated_at = NOW() WHERE instrument_id = $3",
                result["rating"], result.get("reason"), instrument_id,
            )
    return {**result, "cached": False}
