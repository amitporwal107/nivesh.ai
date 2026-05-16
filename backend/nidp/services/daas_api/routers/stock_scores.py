"""V3 Stock score primitives and screener endpoints.

Exposes the full NIDP-computed primitive set for stocks (from migration 055:
nidp.v_v3_stock_primitives) and a multi-metric screener.

Endpoints:
    GET /v1/stocks/{symbol}/score      — full primitive row for one symbol
    GET /v1/stocks/screener            — filtered, ranked screener
    GET /v1/stocks/screener/top        — top-N by a single metric
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from nidp.shared.storage.pg import get_pool
from nidp.services.daas_api.auth import require_api_key
from nidp.services.daas_api.responses import envelope, page_params, row_to_dict

router = APIRouter(
    prefix="/stocks",
    tags=["stock-scores"],
    dependencies=[Depends(require_api_key)],
)

# Columns returned in every primitive row (safe to expose via API)
_PRIMITIVE_COLS = """
    f.symbol,
    f.as_of_date,
    f.sector,
    f.industry,
    f.market_cap_bucket,
    f.market_cap_cr,
    -- Quality inputs
    f.roe_pct,
    f.debt_to_equity,
    f.eps_growth_3y_cagr_pct,
    f.earnings_consistency_score,
    f.promoter_pct              AS promoter_holding_pct,
    CASE f.market_cap_bucket
        WHEN 'LARGE_CAP' THEN 'large'
        WHEN 'MID_CAP'   THEN 'mid'
        WHEN 'SMALL_CAP' THEN 'small'
        WHEN 'MICRO_CAP' THEN 'small'
        ELSE NULL
    END                         AS cap_bucket,
    -- Health inputs
    f.revenue_growth_3y_cagr_pct,
    f.profit_margin_trend_pct,
    f.debt_trend_pct,
    f.volatility_1y_pct,
    f.dividend_yield_pct,
    -- Exit inputs
    f.pe_vs_sector_pct          AS pe_overvaluation_pct,
    f.earnings_decline_flag,
    f.debt_spike_flag,
    f.liquidity_score,
    -- Add inputs
    f.momentum_score,
    -- Additional context
    f.pe_ttm,
    f.pb,
    f.roce_pct,
    f.interest_coverage,
    f.profit_margin_pct,
    f.ev_ebitda,
    f.pat_growth_yoy_pct,
    f.revenue_growth_yoy_pct,
    f.eps_growth_yoy_pct,
    f.return_252d_pct,
    f.beta_1y,
    f.max_drawdown_1y_pct,
    f.rsi14,
    f.accumulation_score,
    f.promoter_pct,
    f.fii_pct,
    f.dii_pct,
    f.promoter_pledged_pct,
    f.fii_pct_change_qoq,
    f.promoter_pct_change_qoq
"""


@router.get(
    "/screener",
    summary="Multi-metric stock screener from NIDP feature store",
)
async def stock_screener(
    sector:          Optional[str]   = Query(None, description="Filter by sector (case-insensitive contains)"),
    market_cap:      Optional[str]   = Query(None, description="LARGE_CAP | MID_CAP | SMALL_CAP | MICRO_CAP"),
    min_roe:         Optional[float] = Query(None, description="Minimum ROE %"),
    max_de:          Optional[float] = Query(None, description="Maximum debt-to-equity"),
    min_eps_cagr_3y: Optional[float] = Query(None, description="Minimum 3Y EPS CAGR %"),
    min_rev_cagr_3y: Optional[float] = Query(None, description="Minimum 3Y Revenue CAGR %"),
    max_rsi:         Optional[float] = Query(None, description="Maximum RSI14 (overheated filter)"),
    min_rsi:         Optional[float] = Query(None, description="Minimum RSI14 (oversold filter)"),
    max_pe_vs_sector:Optional[float] = Query(None, description="Max PE vs sector overvaluation %"),
    sort_by:         str             = Query("momentum_score", description="Sort column: momentum_score | roe_pct | eps_growth_3y_cagr_pct | revenue_growth_3y_cagr_pct | earnings_consistency_score | return_252d_pct | liquidity_score"),
    sort_desc:       bool            = Query(True),
    as_of_date:      Optional[str]   = Query(None, description="YYYY-MM-DD — defaults to latest date in feature store"),
    page: Dict[str, int] = Depends(page_params),
) -> Dict[str, Any]:
    """Screener over the NIDP stock feature store. Returns raw V3 primitives
    for qualifying stocks, sorted by the chosen metric. The copilot uses this
    to generate quality-ranked or momentum-ranked pick lists."""
    _allowed_sort = {
        "momentum_score", "roe_pct", "eps_growth_3y_cagr_pct",
        "revenue_growth_3y_cagr_pct", "earnings_consistency_score",
        "return_252d_pct", "liquidity_score", "market_cap_cr",
        "roce_pct", "profit_margin_pct",
    }
    if sort_by not in _allowed_sort:
        sort_by = "momentum_score"

    pool = await get_pool()
    async with pool.acquire() as conn:
        # Resolve the target date
        if as_of_date:
            target_date = as_of_date
        else:
            r = await conn.fetchval(
                "SELECT MAX(as_of_date) FROM nidp.stock_features_daily"
            )
            target_date = r

        direction = "DESC" if sort_desc else "ASC"

        rows = await conn.fetch(
            f"""
            SELECT {_PRIMITIVE_COLS}
              FROM nidp.stock_features_daily f
             WHERE f.as_of_date = $1
               AND ($2::text IS NULL OR UPPER(f.sector) ILIKE '%' || UPPER($2) || '%')
               AND ($3::text IS NULL OR f.market_cap_bucket = $3)
               AND ($4::numeric IS NULL OR f.roe_pct >= $4)
               AND ($5::numeric IS NULL OR f.debt_to_equity <= $5)
               AND ($6::numeric IS NULL OR f.eps_growth_3y_cagr_pct >= $6)
               AND ($7::numeric IS NULL OR f.revenue_growth_3y_cagr_pct >= $7)
               AND ($8::numeric IS NULL OR f.rsi14 <= $8)
               AND ($9::numeric IS NULL OR f.rsi14 >= $9)
               AND ($10::numeric IS NULL OR f.pe_vs_sector_pct <= $10)
             ORDER BY f.{sort_by} {direction} NULLS LAST
             LIMIT $11 OFFSET $12
            """,
            target_date,
            sector, market_cap,
            min_roe, max_de,
            min_eps_cagr_3y, min_rev_cagr_3y,
            max_rsi, min_rsi, max_pe_vs_sector,
            page["limit"], page["offset"],
        )

    return envelope(
        rows=[row_to_dict(r) for r in rows],
        meta={"as_of_date": str(target_date), "sort_by": sort_by, "sort_desc": sort_desc},
        page=page,
    )


@router.get(
    "/screener/top",
    summary="Top-N stocks by a single metric",
)
async def top_stocks(
    metric:     str           = Query("momentum_score", description="Sort metric"),
    sector:     Optional[str] = Query(None),
    market_cap: Optional[str] = Query(None),
    limit:      int           = Query(10, ge=1, le=100),
    as_of_date: Optional[str] = Query(None),
) -> Dict[str, Any]:
    """Top-N stocks by a chosen metric (quality, momentum, return, etc.)
    Used by the copilot recommendation node for sector-specific or universe-wide picks."""
    _allowed = {
        "momentum_score", "roe_pct", "eps_growth_3y_cagr_pct",
        "earnings_consistency_score", "revenue_growth_3y_cagr_pct",
        "return_252d_pct", "roce_pct", "liquidity_score",
    }
    if metric not in _allowed:
        metric = "momentum_score"

    pool = await get_pool()
    async with pool.acquire() as conn:
        if not as_of_date:
            as_of_date = str(await conn.fetchval(
                "SELECT MAX(as_of_date) FROM nidp.stock_features_daily"
            ))
        rows = await conn.fetch(
            f"""
            SELECT {_PRIMITIVE_COLS}
              FROM nidp.stock_features_daily f
             WHERE f.as_of_date = $1
               AND f.{metric} IS NOT NULL
               AND ($2::text IS NULL OR UPPER(f.sector) ILIKE '%' || UPPER($2) || '%')
               AND ($3::text IS NULL OR f.market_cap_bucket = $3)
             ORDER BY f.{metric} DESC NULLS LAST
             LIMIT $4
            """,
            as_of_date, sector, market_cap, limit,
        )

    return {"as_of_date": as_of_date, "metric": metric, "count": len(rows), "stocks": [row_to_dict(r) for r in rows]}


@router.get(
    "/{symbol}/score",
    summary="Full V3 primitive row for one stock",
)
async def stock_primitives(
    symbol:     str           = Path(..., description="NSE symbol e.g. HDFCBANK"),
    as_of_date: Optional[str] = Query(None, description="YYYY-MM-DD — defaults to latest"),
) -> Dict[str, Any]:
    """Returns the full set of V3 scoring primitives for a stock from the NIDP
    feature store. The copilot uses these to compute composite scores and build
    a multi-dimension analysis."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        if as_of_date:
            row = await conn.fetchrow(
                f"""
                SELECT {_PRIMITIVE_COLS}
                  FROM nidp.stock_features_daily f
                 WHERE f.symbol = UPPER($1) AND f.as_of_date = $2
                """,
                symbol, as_of_date,
            )
        else:
            row = await conn.fetchrow(
                f"""
                SELECT {_PRIMITIVE_COLS}
                  FROM nidp.stock_features_daily f
                 WHERE f.symbol = UPPER($1)
                 ORDER BY f.as_of_date DESC
                 LIMIT 1
                """,
                symbol,
            )

    if row is None:
        raise HTTPException(404, f"No feature data for {symbol.upper()!r}")
    return {"symbol": symbol.upper(), "data": row_to_dict(row)}
