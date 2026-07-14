"""End-of-day price endpoints — raw bhavcopy + adjusted (split/bonus/div).

Backed by nidp.prices_eod and nidp.prices_eod_adjusted. Adjusted is the
right choice for return calculations across corporate actions; raw is
the right choice when you need actual quoted prices on a given day."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query

from nidp.shared.storage.pg import get_pool
from nidp.services.daas_api.auth import require_api_key
from nidp.services.daas_api.responses import (
    envelope, jsonify, normalise_symbol, page_params, parse_date, row_to_dict,
)


router = APIRouter(prefix="/prices", tags=["prices"], dependencies=[Depends(require_api_key)])

# Bounds mirror the features bulk endpoint.
_BULK_MAX_SYMBOLS = 300
_BULK_MAX_ROWS = 400_000


@router.get("/eod/{symbol}", summary="Daily OHLCV for one symbol (raw)")
async def prices_eod(
    symbol: str = Path(..., description="NSE ticker (e.g. RELIANCE, TCS, INFY)"),
    start: Optional[str] = Query(None, description="Inclusive YYYY-MM-DD"),
    end: Optional[str] = Query(None, description="Inclusive YYYY-MM-DD"),
    series: Optional[str] = Query(None, description="EQ | BE | BZ — defaults to all"),
    page: Dict[str, int] = Depends(page_params),
) -> Dict[str, Any]:
    sym = normalise_symbol(symbol)
    d_start = parse_date(start, field="start")
    d_end = parse_date(end, field="end")
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT as_of_date, symbol, series, isin,
                   prev_close, open_price, high_price, low_price, close_price,
                   last_price, avg_price, volume, turnover, trades,
                   deliv_qty, deliv_pct
              FROM nidp.prices_eod
             WHERE symbol = $1
               AND ($2::date IS NULL OR as_of_date >= $2)
               AND ($3::date IS NULL OR as_of_date <= $3)
               AND ($4::text IS NULL OR series = $4)
             ORDER BY as_of_date DESC
             LIMIT $5 OFFSET $6
            """,
            sym, d_start, d_end, series,
            page["limit"], page["offset"],
        )
    return envelope([row_to_dict(r) for r in rows], **page, extra={"symbol": sym})


@router.get("/adjusted/{symbol}", summary="Split/bonus/dividend-adjusted OHLCV")
async def prices_adjusted(
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
            SELECT symbol, as_of_date,
                   raw_open, raw_high, raw_low, raw_close, raw_volume,
                   adj_open, adj_high, adj_low, adj_close, adj_volume,
                   tret_close,
                   cumulative_adj_factor, cumulative_tret_factor,
                   last_event_ex_date, last_event_type
              FROM nidp.prices_eod_adjusted
             WHERE symbol = $1
               AND ($2::date IS NULL OR as_of_date >= $2)
               AND ($3::date IS NULL OR as_of_date <= $3)
             ORDER BY as_of_date DESC
             LIMIT $4 OFFSET $5
            """,
            sym, d_start, d_end, page["limit"], page["offset"],
        )
    return envelope(
        [row_to_dict(r) for r in rows],
        **page,
        extra={
            "symbol": sym,
            "note": "adj_* columns: split+bonus only (price-return). tret_close: split+bonus+dividend (total-return).",
        },
    )


@router.post("/adjusted/bulk", summary="Split/bonus-adjusted OHLC for many symbols over a date range")
async def prices_adjusted_bulk(
    body: Dict[str, Any] = Body(
        ...,
        example={"symbols": ["RELIANCE", "TCS"], "start": "2021-01-01", "end": "2026-01-01"},
    ),
) -> Dict[str, Any]:
    """Bulk adjusted bars keyed by symbol, each a date-ascending list.

    Serves the strategy backtest's exit-bar + entry-price needs (adj_high/
    adj_low/adj_close + cumulative_adj_factor) without per-symbol fan-out.
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
            SELECT symbol, as_of_date,
                   adj_open, adj_high, adj_low, adj_close, adj_volume,
                   tret_close, cumulative_adj_factor
              FROM nidp.prices_eod_adjusted
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


@router.get("/latest/{symbol}", summary="Most-recent EOD bar for one symbol")
async def prices_latest(symbol: str = Path(...)) -> Dict[str, Any]:
    sym = normalise_symbol(symbol)
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT as_of_date, symbol, series, isin,
                   open_price, high_price, low_price, close_price,
                   prev_close, volume, turnover, deliv_pct
              FROM nidp.prices_eod
             WHERE symbol = $1
             ORDER BY as_of_date DESC
             LIMIT 1
            """,
            sym,
        )
    if row is None:
        raise HTTPException(status_code=404, detail=f"no prices found for {sym}")
    return {"data": row_to_dict(row), "as_of": jsonify(row["as_of_date"])}


@router.get("/eod", summary="Daily OHLCV for all symbols on one date")
async def prices_eod_by_date(
    on: str = Query(..., description="Trading day, YYYY-MM-DD"),
    series: Optional[str] = Query("EQ", description="EQ | BE | BZ — defaults to EQ"),
    page: Dict[str, int] = Depends(page_params),
) -> Dict[str, Any]:
    d = parse_date(on, field="on")
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT as_of_date, symbol, series, isin,
                   open_price, high_price, low_price, close_price, prev_close,
                   volume, turnover, trades, deliv_pct
              FROM nidp.prices_eod
             WHERE as_of_date = $1
               AND ($2::text IS NULL OR series = $2)
             ORDER BY turnover DESC NULLS LAST, symbol
             LIMIT $3 OFFSET $4
            """,
            d, series, page["limit"], page["offset"],
        )
    return envelope([row_to_dict(r) for r in rows], **page, extra={"on": d.isoformat()})


@router.get("/index/{index_name}", summary="Daily OHLC for an index (Nifty 50, Bank Nifty, …)")
async def prices_index(
    index_name: str = Path(..., description="Exact index name, e.g. 'Nifty 50', 'Nifty Bank'"),
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    page: Dict[str, int] = Depends(page_params),
) -> Dict[str, Any]:
    d_start = parse_date(start, field="start")
    d_end = parse_date(end, field="end")
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT as_of_date, index_name,
                   open_price, high_price, low_price, close_price,
                   pe_ratio, pb_ratio, div_yield, pts_change, pct_change,
                   volume, turnover
              FROM nidp.index_eod
             WHERE index_name = $1
               AND ($2::date IS NULL OR as_of_date >= $2)
               AND ($3::date IS NULL OR as_of_date <= $3)
             ORDER BY as_of_date DESC
             LIMIT $4 OFFSET $5
            """,
            index_name, d_start, d_end, page["limit"], page["offset"],
        )
    return envelope(
        [row_to_dict(r) for r in rows],
        **page,
        extra={"index_name": index_name},
    )


@router.get("/delivery/{symbol}", summary="Daily delivered-quantity / delivery %")
async def delivery(
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
            SELECT as_of_date, symbol, series,
                   traded_qty, deliverable_qty, deliverable_pct
              FROM nidp.delivery_data
             WHERE symbol = $1
               AND ($2::date IS NULL OR as_of_date >= $2)
               AND ($3::date IS NULL OR as_of_date <= $3)
             ORDER BY as_of_date DESC
             LIMIT $4 OFFSET $5
            """,
            sym, d_start, d_end, page["limit"], page["offset"],
        )
    return envelope([row_to_dict(r) for r in rows], **page, extra={"symbol": sym})
