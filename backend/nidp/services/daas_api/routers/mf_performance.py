"""MF performance analytics endpoints — returns, risk, category rankings.

Served from analytics.fund_category_rank (populated by the MF analytics engine).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query

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


@router.get("/screener/advanced", summary="Composite-score-filtered MF screener")
async def advanced_mf_screener(
    category: Optional[str] = Query(None, description="sub_category filter e.g. 'Large Cap'"),
    sort_by: str = Query("composite_score", description="composite_score | return_3y | sharpe | ter"),
    min_composite: Optional[float] = Query(None, ge=0, le=100, description="Minimum composite_score"),
    max_ter: Optional[float] = Query(None, ge=0, description="Maximum TER %"),
    min_return_3y: Optional[float] = Query(None, description="Minimum 3-year return %"),
    min_sharpe: Optional[float] = Query(None, description="Minimum Sharpe ratio"),
    page: Dict[str, int] = Depends(page_params),
) -> Dict[str, Any]:
    """Advanced MF screener driven by nidp.v_mf_category_scorecard (migration 052).

    Every returned scheme has composite_score, quality_label, and quartile ranks.
    Combines well with the MF intelligence tool in the copilot.
    """
    _SORT_MAP = {
        "composite_score": ("composite_score", "DESC"),
        "return_3y":       ("return_3y",        "DESC"),
        "return_1y":       ("return_1y",         "DESC"),
        "return_5y":       ("return_5y",         "DESC"),
        "sharpe":          ("sharpe_1y",         "DESC"),
        "ter":             ("ter",               "ASC"),
        "aum":             ("aum_cr",            "DESC"),
    }
    if sort_by not in _SORT_MAP:
        raise HTTPException(status_code=400, detail=f"sort_by must be one of {sorted(_SORT_MAP)}")
    col, direction = _SORT_MAP[sort_by]

    conditions = ["1=1"]
    args: list = []
    idx = 1

    if category:
        conditions.append(f"sub_category ILIKE ${idx}")
        args.append(f"%{category}%")
        idx += 1
    if min_composite is not None:
        conditions.append(f"composite_score >= ${idx}")
        args.append(min_composite)
        idx += 1
    if max_ter is not None:
        conditions.append(f"(ter IS NULL OR ter <= ${idx})")
        args.append(max_ter)
        idx += 1
    if min_return_3y is not None:
        conditions.append(f"return_3y >= ${idx}")
        args.append(min_return_3y)
        idx += 1
    if min_sharpe is not None:
        conditions.append(f"sharpe_1y >= ${idx}")
        args.append(min_sharpe)
        idx += 1

    where = " AND ".join(conditions)
    args_limit   = args + [page["limit"], page["offset"]]
    args_count   = args[:]

    pool = await get_pool()
    async with pool.acquire() as conn:
        total = await conn.fetchval(
            f"SELECT COUNT(*) FROM nidp.v_mf_category_scorecard WHERE {where}",
            *args_count,
        )
        rows = await conn.fetch(
            f"""
            SELECT *
              FROM nidp.v_mf_category_scorecard
             WHERE {where}
             ORDER BY {col} {direction} NULLS LAST
             LIMIT ${idx} OFFSET ${idx+1}
            """,
            *args_limit,
        )
    return envelope(
        [row_to_dict(r) for r in rows],
        total=total, **page,
        extra={
            "filters": {
                "category":       category,
                "min_composite":  min_composite,
                "max_ter":        max_ter,
                "min_return_3y":  min_return_3y,
                "min_sharpe":     min_sharpe,
            },
            "sorted_by": sort_by,
        },
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


# ── V3 primitives (bulk) ─────────────────────────────────────────────
#
# Queries nidp.v_v3_mf_primitives by ISIN (migration 058 keys the view
# on ISIN — the natural cross-system MF identifier from CAS imports).

_V3_MF_PRIMITIVE_COLS = """
    v.isin                                 AS isin,
    v.scheme_code,
    v.scheme_name,
    v.category,
    v.sub_category,
    v.aum_cr::float                        AS aum_cr,
    v.fund_age_years::float                AS fund_age_years,
    v.expense_ratio::float                 AS expense_ratio,
    v.expense_ratio_direct::float          AS expense_ratio_direct,
    v.expense_ratio_regular::float         AS expense_ratio_regular,
    v.expense_trend_delta::float           AS expense_trend_delta,
    v.manager_tenure_years::float          AS manager_tenure_years,
    v.top10_concentration_pct::float       AS top10_concentration_pct,
    v.category_avg_1y::float               AS category_avg_1y,
    v.category_avg_3y::float               AS category_avg_3y,
    v.category_avg_5y::float               AS category_avg_5y,
    v.max_drawdown_pct::float              AS max_drawdown_pct,
    v.ret_1y::float                        AS ret_1y,
    v.ret_3y::float                        AS ret_3y,
    v.ret_5y::float                        AS ret_5y,
    v.sharpe::float                        AS sharpe,
    v.sortino::float                       AS sortino,
    v.return_1m::float                     AS return_1m,
    v.return_3m::float                     AS return_3m,
    v.return_6m::float                     AS return_6m,
    v.return_2y::float                     AS return_2y,
    v.return_since_launch_cagr::float      AS return_since_launch_cagr,
    v.alpha_1y::float                      AS alpha_1y,
    v.beta_1y::float                       AS beta_1y,
    v.volatility_1y::float                 AS volatility_1y,
    v.category_rank,
    v.category_rank_pct::float                 AS category_rank_pct,
    v.category_size,
    v.return_1y_rank,
    v.nidp_returns_available,
    v.nidp_snapshot_available,
    v.nidp_holdings_available,
    v.primary_manager,
    v.risk_o_meter
"""


@router.post(
    "/v3-primitives/bulk",
    summary="Bulk V3 MF primitives by ISIN",
)
async def v3_mf_primitives_bulk(
    body: Dict[str, Any] = Body(
        ...,
        example={"isins": ["INF179K01608", "INF179K01VL5"]},
    ),
) -> Dict[str, Any]:
    """Return the V3 primitive row for each requested ISIN, keyed by
    ISIN in the response.

    The natural cross-system identifier for Indian mutual funds. CAS
    imports populate ISIN per holding by construction, and the NIDP
    side stores both Growth and IDCW ISIN variants. The view (migration
    058) emits one row per (scheme_code, ISIN) so each variant has its
    own primitive bundle.

    Missing ISINs are simply absent from the response — callers should
    degrade gracefully when a fund has no V3 primitives.
    """
    raw_isins: List[str] = body.get("isins") or []
    if not isinstance(raw_isins, list):
        raise HTTPException(status_code=400, detail="isins must be a list")
    isins = [s.strip().upper() for s in raw_isins if isinstance(s, str) and s.strip()]
    if not isins:
        return {"data": {}, "count": 0, "requested": len(raw_isins)}

    pool = await get_pool()
    async with pool.acquire() as conn:
        # Migration 098 converted v_v3_mf_primitives from a plain view into a
        # MATERIALIZED view for fast reads. information_schema.views does NOT
        # list materialized views, so check pg_matviews too — otherwise this
        # guard wrongly 503s ("migration 058 not applied") on every call even
        # though the populated matview is right there.
        view_exists = await conn.fetchval(
            """
            SELECT EXISTS (
                SELECT 1 FROM information_schema.views
                 WHERE table_schema = 'nidp' AND table_name = 'v_v3_mf_primitives'
            ) OR EXISTS (
                SELECT 1 FROM pg_matviews
                 WHERE schemaname = 'nidp' AND matviewname = 'v_v3_mf_primitives'
            )
            """
        )
        if not view_exists:
            raise HTTPException(
                status_code=503,
                detail="nidp.v_v3_mf_primitives missing — migration 058/098 not applied",
            )
        rows = await conn.fetch(
            f"""
            SELECT {_V3_MF_PRIMITIVE_COLS},
                   n.nav_date::text AS latest_nav_date
              FROM nidp.v_v3_mf_primitives v
              LEFT JOIN LATERAL (
                  SELECT MAX(nav_date) AS nav_date
                    FROM nidp.mf_nav_daily
                   WHERE scheme_code = v.scheme_code
              ) n ON true
             WHERE v.isin = ANY($1::text[])
            """,
            isins,
        )

    data = {r["isin"]: row_to_dict(r) for r in rows}
    return {
        "data":      data,
        "count":     len(data),
        "requested": len(raw_isins),
    }


# ── Category leaderboard (top-N per SEBI category) ───────────────────────

@router.get(
    "/category-top",
    summary="Top N funds in a SEBI category by composite rank",
)
async def category_top(
    category: str = Query(..., description="SEBI category string, e.g. 'Equity Scheme - Large Cap Fund'"),
    n: int = Query(5, ge=1, le=20, description="Number of top funds to return"),
    rank_date: Optional[str] = Query(None, description="YYYY-MM-DD; defaults to latest available"),
) -> Dict[str, Any]:
    """Return the top-N ranked funds for a SEBI category from mf_category_rank_daily.

    Includes scheme_name, composite score, category_rank, category_pct,
    and key metrics from metric_contributions (ret_3y, sharpe_1y, expense_ratio).
    Used by the fund detail drawer comparison panel.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        if rank_date:
            date_filter = "AND r.rank_date = $3::date"
            params = [category, n, rank_date]
        else:
            date_filter = "AND r.rank_date = (SELECT MAX(rank_date) FROM nidp.mf_category_rank_daily WHERE sebi_category = $1)"
            params = [category, n]

        rows = await conn.fetch(
            f"""
            SELECT
                r.scheme_code,
                sm.scheme_name,
                r.category_rank,
                r.category_pct,
                r.category_size,
                r.composite,
                r.status,
                r.metric_contributions,
                r.rank_date::text AS rank_date
            FROM nidp.mf_category_rank_daily r
            JOIN nidp.mf_scheme_master sm ON sm.scheme_code = r.scheme_code
            WHERE r.sebi_category = $1
              AND r.status IN ('ranked', 'low_confidence')
              {date_filter}
            ORDER BY r.category_rank ASC
            LIMIT $2
            """,
            *params,
        )

    result = []
    for row in rows:
        d = dict(row)
        mc = d.pop("metric_contributions", {}) or {}
        # Extract key metric values for display
        d["ret_3y"]        = (mc.get("return_3y") or {}).get("value")
        d["ret_1y"]        = (mc.get("return_1y") or {}).get("value")
        d["sharpe"]        = (mc.get("sharpe_1y") or {}).get("value")
        d["expense_ratio"] = (mc.get("expense_ratio") or {}).get("value")
        result.append(d)

    return {
        "category":   category,
        "rank_date":  result[0]["rank_date"] if result else None,
        "total_in_category": result[0]["category_size"] if result else 0,
        "funds": result,
    }
