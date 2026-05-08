"""Engineered per-stock features (SMA / RSI / MACD / ATR / Bollinger / volume z)."""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Path, Query

from nidp.shared.storage.pg import get_pool
from nidp.services.daas_api.auth import require_api_key
from nidp.services.daas_api.responses import envelope, normalise_symbol, page_params, parse_date, row_to_dict


router = APIRouter(prefix="/features", tags=["features"], dependencies=[Depends(require_api_key)])


@router.get("/stocks/{symbol}", summary="Daily engineered features for one symbol")
async def stock_features(
    symbol: str = Path(...),
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    page: Dict[str, int] = Depends(page_params),
) -> Dict[str, Any]:
    sym = normalise_symbol(symbol)
    d_start = parse_date(start, field="start")
    d_end = parse_date(end, field="end")
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT symbol, as_of_date, close,
                   sma20, sma50, sma100, sma200, sma50_slope,
                   dist_200dma_pct, dist_52w_high_pct, dist_52w_low_pct,
                   rsi14, macd, macd_signal, macd_hist,
                   return_5d_pct, return_20d_pct, return_60d_pct,
                   atr14, atr_pct, bb_width, bb_pos,
                   avg_volume_20, vol_z20,
                   deliv_pct_avg_20, deliv_trend10,
                   swing_high_20, swing_low_20, pivot_breakout_flag,
                   accumulation_score, accumulation_signals
              FROM nidp.stock_features_daily
             WHERE symbol = $1
               AND ($2::date IS NULL OR as_of_date >= $2)
               AND ($3::date IS NULL OR as_of_date <= $3)
             ORDER BY as_of_date DESC
             LIMIT $4 OFFSET $5
            """,
            sym, d_start, d_end, page["limit"], page["offset"],
        )
    return envelope([row_to_dict(r) for r in rows], **page, extra={"symbol": sym})


@router.get("/stocks/{symbol}/latest", summary="Most-recent feature row for one symbol")
async def latest_features(symbol: str = Path(...)) -> Dict[str, Any]:
    sym = normalise_symbol(symbol)
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT * FROM nidp.stock_features_daily
             WHERE symbol = $1
             ORDER BY as_of_date DESC
             LIMIT 1
            """,
            sym,
        )
    if row is None:
        return {"data": None, "error": "not_found"}
    return {"data": row_to_dict(row)}
