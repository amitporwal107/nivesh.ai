"""Engineered per-stock features (SMA / RSI / MACD / ATR / Bollinger / volume z)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query

from nidp.shared.storage.pg import get_pool
from nidp.services.daas_api.auth import require_api_key
from nidp.services.daas_api.responses import envelope, normalise_symbol, page_params, parse_date, row_to_dict


router = APIRouter(prefix="/features", tags=["features"], dependencies=[Depends(require_api_key)])

# Columns the strategy engine's evaluator needs — the DSL feature whitelist
# (STOCK_FEATURE_COLS) plus identifiers. Kept in sync with the per-symbol
# endpoint below so the bulk path returns the same shape.
# `sector` + the fundamental/ownership/risk columns are required so a strategy
# built from the copilot stock-screener (fundamental predicates + sector) can
# actually screen/backtest on the DaaS path — the evaluator reads these keys.
_FEATURE_COLS = """
    symbol, as_of_date, close, sector,
    sma20, sma50, sma100, sma200, sma50_slope,
    dist_200dma_pct, dist_52w_high_pct, dist_52w_low_pct,
    rsi14, macd, macd_signal, macd_hist,
    return_5d_pct, return_20d_pct, return_60d_pct,
    atr14, atr_pct, bb_width, bb_pos,
    avg_volume_20, vol_z20, deliv_pct_avg_20, deliv_trend10,
    swing_high_20, swing_low_20, pivot_breakout_flag,
    accumulation_score,
    pe_ttm, pb, ev_ebitda, pe_vs_sector_pct, dividend_yield_pct,
    roe_pct, roce_pct, profit_margin_pct, interest_coverage, earnings_consistency_score,
    revenue_growth_3y_cagr_pct, eps_growth_3y_cagr_pct,
    revenue_growth_yoy_pct, pat_growth_yoy_pct, eps_growth_yoy_pct, profit_margin_trend_pct,
    debt_to_equity, debt_trend_pct, liquidity_score,
    market_cap_cr,
    return_252d_pct, volatility_1y_pct, beta_1y, max_drawdown_1y_pct, momentum_score,
    promoter_pct, promoter_pledged_pct, fii_pct, dii_pct,
    fii_pct_change_qoq, promoter_pct_change_qoq
"""
# Hard caps so a single call can't ask for an unbounded scan.
_BULK_MAX_SYMBOLS = 300
_BULK_MAX_ROWS = 400_000


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
            SELECT symbol, as_of_date, close, sector,
                   sma20, sma50, sma100, sma200, sma50_slope,
                   dist_200dma_pct, dist_52w_high_pct, dist_52w_low_pct,
                   rsi14, macd, macd_signal, macd_hist,
                   return_5d_pct, return_20d_pct, return_60d_pct,
                   atr14, atr_pct, bb_width, bb_pos,
                   avg_volume_20, vol_z20,
                   deliv_pct_avg_20, deliv_trend10,
                   swing_high_20, swing_low_20, pivot_breakout_flag,
                   accumulation_score, accumulation_signals,
                   pe_ttm, pb, ev_ebitda, pe_vs_sector_pct, dividend_yield_pct,
                   roe_pct, roce_pct, profit_margin_pct, interest_coverage, earnings_consistency_score,
                   revenue_growth_3y_cagr_pct, eps_growth_3y_cagr_pct,
                   revenue_growth_yoy_pct, pat_growth_yoy_pct, eps_growth_yoy_pct, profit_margin_trend_pct,
                   debt_to_equity, debt_trend_pct, liquidity_score,
                   market_cap_cr,
                   return_252d_pct, volatility_1y_pct, beta_1y, max_drawdown_1y_pct, momentum_score,
                   promoter_pct, promoter_pledged_pct, fii_pct, dii_pct,
                   fii_pct_change_qoq, promoter_pct_change_qoq
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


@router.get("/calendar", summary="Distinct trading dates with feature snapshots")
async def feature_calendar(
    start: Optional[str] = Query(None, description="Inclusive YYYY-MM-DD"),
    end: Optional[str] = Query(None, description="Inclusive YYYY-MM-DD"),
) -> Dict[str, Any]:
    """Distinct as_of_date values present in stock_features_daily, ascending.

    The strategy backtest needs the real trading calendar to sweep dates;
    this replaces its direct `SELECT DISTINCT as_of_date` SQL so the app
    never has to reach NIDP's Postgres directly.
    """
    d_start = parse_date(start, field="start")
    d_end = parse_date(end, field="end")
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT DISTINCT as_of_date
              FROM nidp.stock_features_daily
             WHERE ($1::date IS NULL OR as_of_date >= $1)
               AND ($2::date IS NULL OR as_of_date <= $2)
             ORDER BY as_of_date
            """,
            d_start, d_end,
        )
    dates = [r["as_of_date"].isoformat() for r in rows]
    return {"dates": dates, "count": len(dates)}


@router.post("/bulk", summary="Daily engineered features for many symbols over a date range")
async def features_bulk(
    body: Dict[str, Any] = Body(
        ...,
        example={"symbols": ["RELIANCE", "TCS", "INFY"],
                 "start": "2021-01-01", "end": "2026-01-01"},
    ),
) -> Dict[str, Any]:
    """Bulk feature rows keyed by symbol, each a date-ascending list.

    Collapses the strategy engine's per-symbol fan-out into a few calls.
    The caller chunks the universe into <= _BULK_MAX_SYMBOLS batches.
    """
    raw = body.get("symbols") or []
    if not isinstance(raw, list):
        raise HTTPException(status_code=400, detail="symbols must be a list")
    symbols = [normalise_symbol(s) for s in raw if isinstance(s, str) and s.strip()]
    if not symbols:
        return {"data": {}, "count": 0, "requested": len(raw)}
    if len(symbols) > _BULK_MAX_SYMBOLS:
        raise HTTPException(status_code=400,
                            detail=f"too many symbols ({len(symbols)}); max {_BULK_MAX_SYMBOLS} per call")
    d_start = parse_date(body.get("start"), field="start")
    d_end = parse_date(body.get("end"), field="end")
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT {_FEATURE_COLS}
              FROM nidp.stock_features_daily
             WHERE symbol = ANY($1::text[])
               AND ($2::date IS NULL OR as_of_date >= $2)
               AND ($3::date IS NULL OR as_of_date <= $3)
             ORDER BY symbol, as_of_date
             LIMIT {_BULK_MAX_ROWS}
            """,
            symbols, d_start, d_end,
        )
    data: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        data.setdefault(r["symbol"], []).append(row_to_dict(r))
    return {"data": data, "count": len(rows), "symbols": len(data), "requested": len(symbols)}
