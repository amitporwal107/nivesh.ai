"""Corporate events + AI signals endpoints.

    GET /v1/events/calendar          — upcoming result dates (all companies)
    GET /v1/events/{symbol}          — all events for one stock
    GET /v1/signals/{symbol}         — AI signals for one stock
    GET /v1/signals/latest           — latest signals across all stocks
    GET /v1/signals/{symbol}/{date}  — specific event signal
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Path, Query

from nidp.shared.storage.pg import get_pool
from nidp.services.daas_api.auth import require_api_key
from nidp.services.daas_api.responses import envelope, normalise_symbol, page_params, row_to_dict

router = APIRouter(tags=["events"])


# ── Event Calendar ───────────────────────────────────────────────────

@router.get(
    "/events/calendar",
    summary="Upcoming corporate result dates",
    dependencies=[Depends(require_api_key)],
)
async def event_calendar(
    from_date: Optional[str] = Query(None, description="YYYY-MM-DD (default: today)"),
    to_date:   Optional[str] = Query(None, description="YYYY-MM-DD (default: +30 days)"),
    event_type: Optional[str] = Query(None, description="quarterly_results|dividend|bonus|split|agm|…"),
    page: Dict[str, int] = Depends(page_params),
) -> Dict[str, Any]:
    today = date.today()
    dt_from = date.fromisoformat(from_date) if from_date else today
    dt_to   = date.fromisoformat(to_date)   if to_date   else today + timedelta(days=30)

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT symbol, company_name, event_type, event_date,
                   period, purpose, ex_date, record_date, source, fetched_at
              FROM nidp.event_calendar
             WHERE event_date BETWEEN $1 AND $2
               AND ($3::text IS NULL OR event_type = $3)
             ORDER BY event_date ASC, symbol ASC
             LIMIT $4 OFFSET $5
            """,
            dt_from, dt_to, event_type, page["limit"], page["offset"],
        )
    return envelope([row_to_dict(r) for r in rows], **page,
                    extra={"from_date": str(dt_from), "to_date": str(dt_to)})


@router.get(
    "/events/{symbol}",
    summary="All corporate events for a stock",
    dependencies=[Depends(require_api_key)],
)
async def symbol_events(
    symbol: str = Path(...),
    event_type: Optional[str] = Query(None),
    from_date:  Optional[str] = Query(None),
    page: Dict[str, int] = Depends(page_params),
) -> Dict[str, Any]:
    sym = normalise_symbol(symbol)
    dt_from = date.fromisoformat(from_date) if from_date else date.today() - timedelta(days=365)
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT symbol, company_name, event_type, event_date,
                   period, purpose, ex_date, record_date, source
              FROM nidp.event_calendar
             WHERE symbol = $1
               AND event_date >= $2
               AND ($3::text IS NULL OR event_type = $3)
             ORDER BY event_date DESC
             LIMIT $4 OFFSET $5
            """,
            sym, dt_from, event_type, page["limit"], page["offset"],
        )
    return envelope([row_to_dict(r) for r in rows], **page, extra={"symbol": sym})


# ── AI Signals ───────────────────────────────────────────────────────

@router.get(
    "/signals/latest",
    summary="Latest AI signals across all stocks",
    dependencies=[Depends(require_api_key)],
)
async def latest_signals(
    sentiment: Optional[str] = Query(None, description="strongly_bullish|bullish|neutral|bearish|strongly_bearish"),
    event_type: Optional[str] = Query(None),
    min_confidence: Optional[float] = Query(None, description="Minimum confidence score 0-100"),
    page: Dict[str, int] = Depends(page_params),
) -> Dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT symbol, event_type, event_date, period,
                   sentiment, confidence,
                   estimated_move_pct_low, estimated_move_pct_high,
                   signal_json->>'summary'       AS summary,
                   signal_json->>'trading_note'  AS trading_note,
                   analysed_at, model_used
              FROM nidp.corporate_event_signals
             WHERE ($1::text IS NULL OR sentiment = $1)
               AND ($2::text IS NULL OR event_type = $2)
               AND ($3::numeric IS NULL OR confidence >= $3)
             ORDER BY analysed_at DESC
             LIMIT $4 OFFSET $5
            """,
            sentiment, event_type, min_confidence, page["limit"], page["offset"],
        )
    return envelope([row_to_dict(r) for r in rows], **page)


@router.get(
    "/signals/{symbol}",
    summary="AI signals for a stock",
    dependencies=[Depends(require_api_key)],
)
async def symbol_signals(
    symbol: str = Path(...),
    event_type: Optional[str] = Query(None),
    page: Dict[str, int] = Depends(page_params),
) -> Dict[str, Any]:
    sym = normalise_symbol(symbol)
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT event_type, event_date, period,
                   sentiment, confidence,
                   estimated_move_pct_low, estimated_move_pct_high,
                   signal_json, analysed_at, model_used
              FROM nidp.corporate_event_signals
             WHERE symbol = $1
               AND ($2::text IS NULL OR event_type = $2)
             ORDER BY event_date DESC, analysed_at DESC
             LIMIT $3 OFFSET $4
            """,
            sym, event_type, page["limit"], page["offset"],
        )
    return envelope([row_to_dict(r) for r in rows], **page, extra={"symbol": sym})
