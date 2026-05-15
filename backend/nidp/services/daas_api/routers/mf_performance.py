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


@router.get("/scorecard/{scheme_code}", summary="Full category scorecard for a scheme")
async def scheme_scorecard(scheme_code: str = Path(...)) -> Dict[str, Any]:
    """Returns composite score, quality label, per-metric ranks and quartiles
    within the fund's sub-category peer group.

    Consumes nidp.v_mf_category_scorecard (migration 052), which joins
    analytics.fund_category_rank + mf_derived_analytics + disclosure snapshots
    + holdings to produce 73 columns including:
      - composite_score (0–100), quality_label (Elite … Underperformer)
      - composite_rank, total_in_category, top_position_pct
      - rank_ret1y / rank_ret3y / rank_ret5y / rank_sharpe / rank_ter / …
      - qtile_ret1y / qtile_sharpe / qtile_maxdd / qtile_ter / … (1=Q1 best)
      - pct_ret1y / pct_sharpe / … (0–1 PERCENT_RANK for radar charts)
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM nidp.v_mf_category_scorecard WHERE scheme_code = $1",
            scheme_code,
        )
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"no scorecard data for {scheme_code!r} — analytics may not have run yet",
        )
    return {"data": row_to_dict(row)}


@router.get("/scorecard/category/{sub_category}", summary="Category leaderboard with composite scores")
async def category_scorecard_leaderboard(
    sub_category: str = Path(..., description="e.g. 'Large Cap', 'Mid Cap', 'Flexi Cap'"),
    sort_by: str = Query("composite_score", description="composite_score | ret_1y | ret_3y | sharpe | ter"),
    page: Dict[str, int] = Depends(page_params),
) -> Dict[str, Any]:
    """Full scorecard leaderboard for a sub-category, sorted by composite score
    or any individual metric.  Includes quality labels and quartile flags.
    """
    _SORT_MAP = {
        "composite_score": ("composite_score", "DESC"),
        "ret_1y":   ("return_1y",  "DESC"),
        "ret_3y":   ("return_3y",  "DESC"),
        "ret_5y":   ("return_5y",  "DESC"),
        "sharpe":   ("sharpe_1y",  "DESC"),
        "sortino":  ("sortino_1y", "DESC"),
        "alpha":    ("alpha_1y",   "DESC"),
        "maxdd":    ("max_drawdown_1y", "ASC"),
        "ter":      ("ter",        "ASC"),
        "aum":      ("aum_cr",     "DESC"),
    }
    if sort_by not in _SORT_MAP:
        raise HTTPException(status_code=400, detail=f"sort_by must be one of {sorted(_SORT_MAP)}")
    col, direction = _SORT_MAP[sort_by]

    pool = await get_pool()
    async with pool.acquire() as conn:
        total = await conn.fetchval(
            "SELECT COUNT(*) FROM nidp.v_mf_category_scorecard WHERE sub_category ILIKE $1",
            f"%{sub_category}%",
        )
        if not total:
            raise HTTPException(status_code=404, detail=f"no scorecard data for sub_category {sub_category!r}")
        rows = await conn.fetch(
            f"""
            SELECT *
              FROM nidp.v_mf_category_scorecard
             WHERE sub_category ILIKE $1
             ORDER BY {col} {direction} NULLS LAST
             LIMIT $2 OFFSET $3
            """,
            f"%{sub_category}%", page["limit"], page["offset"],
        )
    return envelope(
        [row_to_dict(r) for r in rows],
        total=total, **page,
        extra={"sub_category": sub_category, "sorted_by": sort_by},
    )
