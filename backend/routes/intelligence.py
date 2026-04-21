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


@router.post("/admin/ai/circuit/reset")
async def reset_llm_circuit(request: Request):
    await require_admin(request)
    ai_insights.llm_circuit_reset()
    return ai_insights.llm_circuit_status()


@router.get("/admin/ai/circuit")
async def get_llm_circuit(request: Request):
    await require_admin(request)
    return ai_insights.llm_circuit_status()


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
    if pool:
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE mutual_fund_metadata SET ai_rating = $1, ai_rating_reason = $2, "
                "ai_rated_at = NOW() WHERE instrument_id = $3",
                result["rating"], result.get("reason"), instrument_id,
            )
    return {**result, "cached": False}


# ── V3 Engine Phase 1 ────────────────────────────────────────────────────
from services import v3_scoring, nav_analytics  # noqa: E402


async def _load_fund_primitives(instrument_id: str) -> Optional[dict]:
    """Pull every V3 input field from PG into one flat dict for scoring."""
    pool = await pg_client.get_pool()
    if pool is None:
        return None
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
              im.instrument_name, im.isin,
              mfmd.category, mfmd.sub_category, mfmd.benchmark_index,
              mfmd.aum_cr::float, mfmd.fund_age_years::float,
              mfmd.expense_ratio::float, mfmd.expense_ratio_direct::float,
              mfmd.expense_ratio_regular::float, mfmd.expense_trend_delta::float,
              mfmd.manager_name, mfmd.manager_tenure_years::float,
              mfmd.turnover_ratio::float, mfmd.top10_concentration_pct::float,
              mfmd.category_avg_1y::float, mfmd.category_avg_3y::float, mfmd.category_avg_5y::float,
              mfmd.max_drawdown_pct::float, mfmd.consistency_score::float,
              mfmd.downside_capture_pct::float, mfmd.aum_trend_score::float,
              mfpr.ret_1y::float, mfpr.ret_3y::float, mfpr.ret_5y::float,
              mfpr.alpha::float, mfpr.sharpe::float, mfpr.sortino::float, mfpr.std_dev::float
            FROM mutual_fund_metadata mfmd
            JOIN instrument_master im ON im.instrument_id = mfmd.instrument_id
            LEFT JOIN LATERAL (
              SELECT * FROM mutual_fund_performance_ratios
              WHERE instrument_id = mfmd.instrument_id
              ORDER BY ratios_date DESC LIMIT 1
            ) mfpr ON TRUE
            WHERE mfmd.instrument_id = $1::uuid
            """,
            instrument_id,
        )
    if not row:
        return None
    d = dict(row)
    d["instrument_id"] = instrument_id
    return d


@router.get("/intelligence/v3-score/{instrument_id}")
async def get_v3_score(request: Request, instrument_id: str, refresh: bool = Query(False)):
    """Return V3 Engine scores for a single fund.

    Returns all 5 composite scores (Quality, Health, Exit, Add, Portfolio-Fit)
    with per-component breakdown, missing primitives, and effective weights
    after redistribution. Pass ?refresh=true to recompute NAV analytics first.
    """
    await require_admin(request)
    if refresh:
        await nav_analytics.refresh_all_analytics(instrument_id)

    f = await _load_fund_primitives(instrument_id)
    if not f:
        raise HTTPException(status_code=404, detail="Fund not found")

    # Minimal portfolio ctx with conservative defaults — callers that want
    # user-aware Exit/Add scores should use the action_plan_manager directly.
    empty_ctx: dict = {
        "overlap_pct": None, "tax_liability_rs": None, "tax_benefit_rs": None,
        "quality_score": None, "portfolio_fit_score": None,
        "gap_fit_0_10": None, "avg_overlap_pct_with_portfolio": None,
        "need_score_0_10": None,
    }

    quality = v3_scoring.compute_quality_score(f)
    health = v3_scoring.compute_health_score(f)
    # Re-run exit/add with quality_score + portfolio_fit filled in so components
    # that depend on those propagate correctly.
    portfolio_proxy = {
        "diversification_0_10": None, "avg_overlap_pct": None, "top_amc_pct": None,
        "avg_expense_ratio": f.get("expense_ratio_direct"), "asset_alloc_fit_0_10": None,
    }
    pfit = v3_scoring.compute_portfolio_fit_score(portfolio_proxy)
    ctx_exit = {**empty_ctx,
                "quality_score": quality["score"],
                "portfolio_fit_score": pfit["score"]}
    ctx_add = {**empty_ctx, "quality_score": quality["score"]}
    exit_ = v3_scoring.compute_exit_score(f, ctx_exit)
    add = v3_scoring.compute_add_score(f, ctx_add)

    return {
        "instrument_id": instrument_id,
        "scheme_name": f.get("instrument_name"),
        "isin": f.get("isin"),
        "category": f.get("category"),
        "engine_version": v3_scoring.ENGINE_VERSION,
        "scores": {
            "quality": quality, "health": health,
            "exit": exit_, "add": add,
            "portfolio_fit": pfit,
        },
        "primitives_used": {k: v for k, v in f.items() if v is not None and k != "instrument_id"},
    }


@router.post("/intelligence/v3-score/{instrument_id}/refresh-analytics")
async def refresh_nav_analytics(request: Request, instrument_id: str):
    """Recompute max_drawdown/consistency/downside_capture/aum_trend from NAV+AUM history."""
    await require_admin(request)
    return await nav_analytics.refresh_all_analytics(instrument_id)
