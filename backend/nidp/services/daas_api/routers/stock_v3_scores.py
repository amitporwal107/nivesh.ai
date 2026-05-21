"""V3 Stock persisted-score endpoints (Quality + Health).

Reads from nidp.v3_stock_scores_daily / nidp.v_v3_stock_scores_latest
(migration 065), populated nightly by services.v3_scores_engine.

Companion to /v1/stocks/{symbol}/score (which returns primitives, not
composites). Use this endpoint when you want the COMPUTED composite score.

Scope: Quality + Health only. Exit/Add are portfolio-aware and stay
on-the-fly downstream when a user's portfolio is in context.

Every response includes coverage_pct — ranking comparisons must gate on it.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query

from nidp.services.daas_api.auth import require_api_key
from nidp.services.daas_api.responses import envelope, page_params, row_to_dict
from nidp.shared.storage.pg import get_pool

router = APIRouter(
    prefix="/stocks/scores",
    tags=["stock-scores"],
    dependencies=[Depends(require_api_key)],
)

_SCORE_COLS = """
    as_of_date, symbol, sector, industry, market_cap_bucket,
    quality_score, quality_components, quality_coverage_pct,
    health_score,  health_components,  health_coverage_pct,
    engine_version, computed_at
"""


@router.get(
    "/{symbol}",
    summary="Latest V3 Quality + Health composite score for one stock",
)
async def stock_score_latest(
    symbol: str = Path(..., description="NSE symbol e.g. HDFCBANK"),
) -> Dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"SELECT {_SCORE_COLS} FROM nidp.v_v3_stock_scores_latest WHERE symbol = $1",
            symbol.upper(),
        )
    if row is None:
        raise HTTPException(404, f"no persisted V3 score for {symbol.upper()!r}")
    return {"data": row_to_dict(row)}


@router.get(
    "/{symbol}/history",
    summary="V3 Quality + Health score history (last N days) for one stock",
)
async def stock_score_history(
    symbol: str = Path(...),
    days:   int = Query(30, ge=1, le=365),
) -> Dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT {_SCORE_COLS}
              FROM nidp.v3_stock_scores_daily
             WHERE symbol = $1
               AND as_of_date > CURRENT_DATE - $2::int
             ORDER BY as_of_date DESC
            """,
            symbol.upper(), days,
        )
    return {
        "symbol": symbol.upper(),
        "days":   days,
        "count":  len(rows),
        "history": [row_to_dict(r) for r in rows],
    }


@router.post(
    "/bulk",
    summary="Bulk latest V3 stock scores by symbol",
)
async def stock_scores_bulk(
    body: Dict[str, Any] = Body(..., example={"symbols": ["HDFCBANK", "INFY", "RELIANCE"]}),
) -> Dict[str, Any]:
    raw = body.get("symbols") or []
    if not isinstance(raw, list):
        raise HTTPException(status_code=400, detail="symbols must be a list")
    symbols = [s.strip().upper() for s in raw if isinstance(s, str) and s.strip()]
    if not symbols:
        return {"data": {}, "count": 0, "requested": len(raw)}

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT {_SCORE_COLS}
              FROM nidp.v_v3_stock_scores_latest
             WHERE symbol = ANY($1::text[])
            """,
            symbols,
        )
    data = {r["symbol"]: row_to_dict(r) for r in rows}
    return {"data": data, "count": len(data), "requested": len(raw)}


@router.get(
    "/",
    summary="Filtered + sorted V3 stock scores screener (latest snapshot)",
)
async def stock_scores_screener(
    sector:               Optional[str]   = Query(None, description="ILIKE %X% on sector"),
    market_cap:           Optional[str]   = Query(None, description="LARGE_CAP | MID_CAP | SMALL_CAP | MICRO_CAP"),
    min_quality:          Optional[float] = Query(None, ge=0, le=100),
    min_health:           Optional[float] = Query(None, ge=0, le=100),
    min_quality_coverage: Optional[float] = Query(80.0, ge=0, le=100,
        description="Minimum quality_coverage_pct (defaults to 80 — ranking-honest)"),
    sort_by:              str             = Query("quality_score",
        description="quality_score | health_score | quality_coverage_pct | health_coverage_pct"),
    sort_desc:            bool            = Query(True),
    page:                 Dict[str, int]  = Depends(page_params),
) -> Dict[str, Any]:
    _ALLOWED_SORT = {
        "quality_score", "health_score",
        "quality_coverage_pct", "health_coverage_pct",
    }
    if sort_by not in _ALLOWED_SORT:
        raise HTTPException(400, f"sort_by must be one of {sorted(_ALLOWED_SORT)}")
    direction = "DESC" if sort_desc else "ASC"

    conds: List[str] = ["TRUE"]
    args: List[Any] = []
    i = 1
    if sector:
        conds.append(f"sector ILIKE ${i}"); args.append(f"%{sector}%"); i += 1
    if market_cap:
        conds.append(f"market_cap_bucket = ${i}"); args.append(market_cap.upper()); i += 1
    if min_quality is not None:
        conds.append(f"quality_score >= ${i}"); args.append(min_quality); i += 1
    if min_health is not None:
        conds.append(f"health_score >= ${i}");  args.append(min_health);  i += 1
    if min_quality_coverage is not None:
        conds.append(f"quality_coverage_pct >= ${i}"); args.append(min_quality_coverage); i += 1

    where = " AND ".join(conds)
    pool = await get_pool()
    async with pool.acquire() as conn:
        total = await conn.fetchval(
            f"SELECT COUNT(*) FROM nidp.v_v3_stock_scores_latest WHERE {where}",
            *args,
        )
        rows = await conn.fetch(
            f"""
            SELECT {_SCORE_COLS}
              FROM nidp.v_v3_stock_scores_latest
             WHERE {where}
             ORDER BY {sort_by} {direction} NULLS LAST
             LIMIT ${i} OFFSET ${i+1}
            """,
            *args, page["limit"], page["offset"],
        )
    return envelope(
        [row_to_dict(r) for r in rows],
        total=total, **page,
        extra={
            "filters": {
                "sector":               sector,
                "market_cap":           market_cap,
                "min_quality":          min_quality,
                "min_health":           min_health,
                "min_quality_coverage": min_quality_coverage,
            },
            "sort_by":  sort_by,
            "sort_desc": sort_desc,
        },
    )
