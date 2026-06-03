"""Portfolio Intelligence API — real stock-level overlap + AI insights."""
from fastapi import APIRouter, Request, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List

from deps import get_current_user, require_admin, db
from services import portfolio_intelligence, ai_insights, pg_writer, pg_client, dashboard_recommendations
from core.exceptions import ResourceNotFoundException

router = APIRouter(prefix="/api")


class SimulateBody(BaseModel):
    remove_mf_ids: List[str] = []


@router.get("/intelligence/portfolio")
async def get_portfolio_intelligence(request: Request, narrate: bool = Query(True)):
    """Full portfolio intelligence bundle with real stock-level overlap.

    Returns the legacy `ai_insights` array AND a richer `top_recommendations`
    array built by the dashboard orchestrator — the latter merges
    portfolio_intelligence, copilot tools (rebalance, tax harvest,
    risk suitability, MF intelligence, stock composite scores) into one
    ranked list the frontend can render in Top3Actions + Intelligence Feed.
    """
    user = await get_current_user(request)
    user_id = user["user_id"]
    metrics = await portfolio_intelligence.compute_portfolio_intelligence(user_id)
    if narrate and not metrics.get("empty"):
        # Run legacy ai_insights and the dashboard orchestrator in parallel.
        import asyncio as _asyncio
        ai_t = _asyncio.create_task(ai_insights.generate_insights(metrics))
        rec_t = _asyncio.create_task(dashboard_recommendations.build_dashboard_recommendations(user_id))
        rating_t = _asyncio.create_task(ai_insights.rate_portfolio_categories(metrics))
        ai_out, rec_out, rating_out = await _asyncio.gather(ai_t, rec_t, rating_t, return_exceptions=True)
        metrics["ai_insights"] = [] if isinstance(ai_out, Exception) else ai_out
        metrics["top_recommendations"] = [] if isinstance(rec_out, Exception) else rec_out
        metrics["category_ratings"] = [] if isinstance(rating_out, Exception) else rating_out
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
        raise ResourceNotFoundException("Fund not found", code="RES-001")
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

    Cache: reads from Redis first (24h TTL). Pass ?refresh=true to bypass
    cache AND recompute NAV analytics before scoring.
    """
    await require_admin(request)
    from services import v3_score_cache

    if refresh:
        await v3_score_cache.invalidate(instrument_id)
        await nav_analytics.refresh_all_analytics(instrument_id)
    else:
        cached = await v3_score_cache.get(instrument_id)
        if cached:
            cached["cached"] = True
            cached["instrument_id"] = instrument_id
            return cached

    f = await _load_fund_primitives(instrument_id)
    if not f:
        raise ResourceNotFoundException("Fund not found", code="RES-001")

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
    portfolio_proxy = {
        "diversification_0_10": None, "avg_overlap_pct": None, "top_amc_pct": None,
        "avg_expense_ratio": f.get("expense_ratio_direct"), "asset_alloc_fit_0_10": None,
    }
    pfit = v3_scoring.compute_portfolio_fit_score(portfolio_proxy)
    ctx_exit = {**empty_ctx, "quality_score": quality["score"], "portfolio_fit_score": pfit["score"]}
    ctx_add = {**empty_ctx, "quality_score": quality["score"]}
    exit_ = v3_scoring.compute_exit_score(f, ctx_exit)
    add = v3_scoring.compute_add_score(f, ctx_add)

    payload = {
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
    # Cache the score-only subset (primitives can be huge)
    await v3_score_cache.set(instrument_id, {
        "engine_version": v3_scoring.ENGINE_VERSION,
        "scheme_name": f.get("instrument_name"),
        "scores": payload["scores"],
    })
    payload["cached"] = False
    return payload


@router.post("/intelligence/v3-score/{instrument_id}/refresh-analytics")
async def refresh_nav_analytics(request: Request, instrument_id: str):
    """Recompute max_drawdown/consistency/downside_capture/aum_trend from NAV+AUM history."""
    await require_admin(request)
    return await nav_analytics.refresh_all_analytics(instrument_id)


@router.get("/intelligence/sector-peers/{symbol}")
async def sector_peer_comparison(request: Request, symbol: str, limit: int = Query(10)):
    """Rank same-sector peers of a stock the user holds, scored by V3.

    Powers the Quick Action "Compare My Funds" / "Sector Exposure" deep-link
    for stock investors. Returns the user's symbol + top peers sorted by
    composite quality + momentum, so the dashboard can render a side-by-side
    fundamental + technical comparison without going through the chat.
    """
    await get_current_user(request)
    from services.copilot_tools import stock_intelligence as si

    # 1. Resolve the user's symbol → its sector via the stock intelligence tool
    me = await si.get_stock_intelligence(symbol)
    sector = None
    if getattr(me, "ok", False):
        sector = (me.data or {}).get("sector") or (me.fundamentals or {}).get("sector") if hasattr(me, "fundamentals") else None
    if not sector:
        # fall back: look in DAAS reference
        from services.copilot_tools import daas_client as _dc
        try:
            ref = await _dc.daas_get(f"/v1/reference/security/{symbol}")
            sector = (ref or {}).get("data", {}).get("sector")
        except Exception:  # noqa: BLE001
            sector = None
    if not sector:
        raise ResourceNotFoundException(f"No sector mapping found for {symbol}", code="RES-001")

    # 2. Fetch top-N peers in the same sector, V3-scored
    peers = await si.get_nidp_screener(
        metric="momentum_score", sector=sector, limit=max(1, min(50, limit)),
    )
    return {
        "symbol": symbol,
        "sector": sector,
        "user_holding": {
            "symbol": symbol,
            "ok": getattr(me, "ok", False),
            "data": getattr(me, "data", None),
        } if getattr(me, "ok", False) else None,
        "peers": peers,
        "engine_version": v3_scoring.ENGINE_VERSION,
    }
