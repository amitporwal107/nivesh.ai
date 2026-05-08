"""Frozen point-in-time snapshots: market-wide + per-stock."""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from nidp.shared.storage.pg import get_pool
from nidp.services.daas_api.auth import require_api_key
from nidp.services.daas_api.responses import envelope, normalise_symbol, page_params, parse_date, row_to_dict


router = APIRouter(prefix="/snapshots", tags=["snapshots"], dependencies=[Depends(require_api_key)])


@router.get("/market", summary="Market-wide daily snapshot (indices, breadth, flows)")
async def market_snapshot(
    on: Optional[str] = Query(None, description="YYYY-MM-DD; defaults to most recent"),
) -> Dict[str, Any]:
    on_d = parse_date(on, field="on")
    pool = await get_pool()
    async with pool.acquire() as conn:
        if on_d is None:
            row = await conn.fetchrow(
                "SELECT * FROM nidp.market_daily_snapshot ORDER BY as_of_date DESC LIMIT 1"
            )
        else:
            row = await conn.fetchrow(
                "SELECT * FROM nidp.market_daily_snapshot WHERE as_of_date = $1",
                on_d,
            )
    if row is None:
        raise HTTPException(status_code=404, detail="no snapshot for requested date")
    return {"data": row_to_dict(row)}


@router.get("/stock/{symbol}", summary="Per-stock daily snapshot (OHLCV + index flags + deals)")
async def stock_snapshot(
    symbol: str = Path(...),
    on: Optional[str] = Query(None),
) -> Dict[str, Any]:
    sym = normalise_symbol(symbol)
    on_d = parse_date(on, field="on")
    pool = await get_pool()
    async with pool.acquire() as conn:
        if on_d is None:
            row = await conn.fetchrow(
                """
                SELECT * FROM nidp.stock_daily_snapshot
                 WHERE symbol = $1
                 ORDER BY as_of_date DESC LIMIT 1
                """,
                sym,
            )
        else:
            row = await conn.fetchrow(
                """
                SELECT * FROM nidp.stock_daily_snapshot
                 WHERE symbol = $1 AND as_of_date = $2
                 LIMIT 1
                """,
                sym, on_d,
            )
    if row is None:
        raise HTTPException(status_code=404, detail=f"no snapshot for {sym}")
    return {"data": row_to_dict(row)}


@router.get("/market/recent", summary="Trailing N days of market snapshots")
async def market_recent(
    days: int = Query(30, ge=1, le=365),
    page: Dict[str, int] = Depends(page_params),
) -> Dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT as_of_date,
                   nifty50_close, nifty50_pct_change,
                   nifty500_close, bank_nifty_close, india_vix,
                   fii_cash_net_cr, dii_cash_net_cr,
                   advances_count, declines_count, unchanged_count,
                   total_traded_value_cr
              FROM nidp.market_daily_snapshot
             WHERE as_of_date >= CURRENT_DATE - ($1::int * INTERVAL '1 day')
             ORDER BY as_of_date DESC
             LIMIT $2 OFFSET $3
            """,
            days, page["limit"], page["offset"],
        )
    return envelope([row_to_dict(r) for r in rows], **page, extra={"days": days})
