"""MF performance analytics endpoints — returns, risk, category rankings.

Served from analytics.fund_category_rank (populated by the MF analytics engine).
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from nidp.shared.storage.pg import get_pool
from nidp.services.daas_api.auth import require_api_key
from nidp.services.daas_api.responses import envelope, page_params, row_to_dict

router = APIRouter(
    prefix="/mf/performance",
    tags=["mf-performance"],
    dependencies=[Depends(require_api_key)],
)

_PERF_COLS = """
    scheme_code, rank_date,
    scheme_name, category, sub_category, amc_code,
    return_1m, return_3m, return_6m,
    return_1y, return_2y, return_3y, return_5y, return_ytd,
    return_since_launch_cagr,
    volatility_1y, sharpe_1y, sortino_1y, max_drawdown_1y,
    alpha_1y, beta_1y,
    ter,
    return_1y_rank, return_3y_rank, sharpe_rank, sortino_rank,
    composite_rank,
    scheme_launch_date, data_since_date, nav_count,
    built_at
"""


@router.get("/{scheme_code}", summary="Performance metrics for a single scheme")
async def scheme_performance(scheme_code: str = Path(...)) -> Dict[str, Any]:
    """Returns the latest computed return + risk metrics for a scheme."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"""
            SELECT {_PERF_COLS}
              FROM analytics.fund_category_rank
             WHERE scheme_code = $1
             ORDER BY rank_date DESC
             LIMIT 1
            """,
            scheme_code,
        )
    if row is None:
        raise HTTPException(status_code=404, detail=f"no performance data for {scheme_code!r}")
    return {"data": row_to_dict(row)}


@router.get("/category/{category}", summary="Top-N schemes within a category")
async def category_leaderboard(
    category: str = Path(..., description="e.g. 'Equity', 'Debt', 'Hybrid'"),
    metric: str = Query("composite_rank", description="Sort metric: composite_rank | return_1y | return_3y | sharpe_1y | sortino_1y"),
    page: Dict[str, int] = Depends(page_params),
) -> Dict[str, Any]:
    """Category leaderboard sorted by selected metric."""
    _ALLOWED_METRICS = {
        "composite_rank", "return_1y", "return_3y", "return_5y",
        "sharpe_1y", "sortino_1y", "return_1m", "return_3m",
    }
    if metric not in _ALLOWED_METRICS:
        raise HTTPException(status_code=400, detail=f"metric must be one of {sorted(_ALLOWED_METRICS)}")

    order = "ASC" if metric.endswith("_rank") else "DESC"

    pool = await get_pool()
    async with pool.acquire() as conn:
        latest_date = await conn.fetchval(
            "SELECT MAX(rank_date) FROM analytics.fund_category_rank WHERE category ILIKE $1",
            f"%{category}%",
        )
        if latest_date is None:
            raise HTTPException(status_code=404, detail=f"no data for category {category!r}")

        rows = await conn.fetch(
            f"""
            SELECT {_PERF_COLS}
              FROM analytics.fund_category_rank
             WHERE category ILIKE $1
               AND rank_date = $2
             ORDER BY {metric} {order} NULLS LAST
             LIMIT $3 OFFSET $4
            """,
            f"%{category}%", latest_date, page["limit"], page["offset"],
        )
        total = await conn.fetchval(
            "SELECT COUNT(*) FROM analytics.fund_category_rank WHERE category ILIKE $1 AND rank_date = $2",
            f"%{category}%", latest_date,
        )
    return envelope(
        [row_to_dict(r) for r in rows],
        total=total, **page,
        extra={"category": category, "rank_date": str(latest_date), "sorted_by": metric},
    )


@router.get("/screener/top", summary="Top funds across all categories by a single metric")
async def top_funds_screener(
    metric: str = Query("composite_rank", description="return_1y | sharpe_1y | sortino_1y | composite_rank"),
    category_filter: Optional[str] = Query(None, description="Optional category substring filter"),
    page: Dict[str, int] = Depends(page_params),
) -> Dict[str, Any]:
    """Cross-category top-fund screener."""
    _ALLOWED = {"composite_rank", "return_1y", "return_3y", "sharpe_1y", "sortino_1y", "return_1m"}
    if metric not in _ALLOWED:
        raise HTTPException(status_code=400, detail=f"metric must be one of {sorted(_ALLOWED)}")

    order = "ASC" if metric.endswith("_rank") else "DESC"

    pool = await get_pool()
    async with pool.acquire() as conn:
        latest_date = await conn.fetchval("SELECT MAX(rank_date) FROM analytics.fund_category_rank")
        if latest_date is None:
            raise HTTPException(status_code=404, detail="no performance data computed yet")

        cat_filter = f"%{category_filter}%" if category_filter else "%"
        rows = await conn.fetch(
            f"""
            SELECT {_PERF_COLS}
              FROM analytics.fund_category_rank
             WHERE rank_date = $1
               AND category ILIKE $2
             ORDER BY {metric} {order} NULLS LAST
             LIMIT $3 OFFSET $4
            """,
            latest_date, cat_filter, page["limit"], page["offset"],
        )
        total = await conn.fetchval(
            "SELECT COUNT(*) FROM analytics.fund_category_rank WHERE rank_date=$1 AND category ILIKE $2",
            latest_date, cat_filter,
        )
    return envelope(
        [row_to_dict(r) for r in rows],
        total=total, **page,
        extra={"rank_date": str(latest_date), "sorted_by": metric},
    )
