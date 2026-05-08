"""Capital flows + large-trade prints — FII/DII, bulk deals, block deals."""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query

from nidp.shared.storage.pg import get_pool
from nidp.services.daas_api.auth import require_api_key
from nidp.services.daas_api.responses import envelope, normalise_symbol, page_params, parse_date, row_to_dict


router = APIRouter(prefix="/flows", tags=["flows"], dependencies=[Depends(require_api_key)])


@router.get("/fii-dii", summary="FII / DII net flows by category × segment")
async def fii_dii(
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    category: Optional[str] = Query(None, description="FII | DII | PROP | CLIENT"),
    segment: Optional[str] = Query(
        None,
        description="EQUITY_CASH | INDEX_FUTURES | INDEX_OPTIONS | STOCK_FUTURES | STOCK_OPTIONS",
    ),
    page: Dict[str, int] = Depends(page_params),
) -> Dict[str, Any]:
    d_start = parse_date(start, field="start")
    d_end = parse_date(end, field="end")
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT as_of_date, category, segment,
                   buy_value_cr, sell_value_cr, net_value_cr,
                   buy_contracts, sell_contracts, net_contracts,
                   open_interest
              FROM nidp.fii_dii_flows
             WHERE ($1::date IS NULL OR as_of_date >= $1)
               AND ($2::date IS NULL OR as_of_date <= $2)
               AND ($3::text IS NULL OR category = $3)
               AND ($4::text IS NULL OR segment = $4)
             ORDER BY as_of_date DESC, category, segment
             LIMIT $5 OFFSET $6
            """,
            d_start, d_end, category, segment,
            page["limit"], page["offset"],
        )
    return envelope([row_to_dict(r) for r in rows], **page)


@router.get("/bulk-deals", summary="Bulk deals (>0.5% of listed shares in one client name)")
async def bulk_deals(
    symbol: Optional[str] = Query(None),
    client: Optional[str] = Query(None, description="Substring match on client_name"),
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    page: Dict[str, int] = Depends(page_params),
) -> Dict[str, Any]:
    sym = normalise_symbol(symbol) if symbol else None
    pattern = f"%{client.upper()}%" if client else None
    d_start = parse_date(start, field="start")
    d_end = parse_date(end, field="end")
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT as_of_date, symbol, client_name, deal_type,
                   quantity, avg_price, deal_seq, remarks
              FROM nidp.bulk_deals
             WHERE ($1::text IS NULL OR symbol = $1)
               AND ($2::text IS NULL OR UPPER(client_name) LIKE $2)
               AND ($3::date IS NULL OR as_of_date >= $3)
               AND ($4::date IS NULL OR as_of_date <= $4)
             ORDER BY as_of_date DESC, symbol
             LIMIT $5 OFFSET $6
            """,
            sym, pattern, d_start, d_end, page["limit"], page["offset"],
        )
    return envelope([row_to_dict(r) for r in rows], **page)


@router.get("/block-deals", summary="Block deals (negotiated > ₹10 Cr or > 5L shares)")
async def block_deals(
    symbol: Optional[str] = Query(None),
    client: Optional[str] = Query(None),
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    page: Dict[str, int] = Depends(page_params),
) -> Dict[str, Any]:
    sym = normalise_symbol(symbol) if symbol else None
    pattern = f"%{client.upper()}%" if client else None
    d_start = parse_date(start, field="start")
    d_end = parse_date(end, field="end")
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT as_of_date, symbol, client_name, deal_type,
                   quantity, avg_price, deal_seq, remarks
              FROM nidp.block_deals
             WHERE ($1::text IS NULL OR symbol = $1)
               AND ($2::text IS NULL OR UPPER(client_name) LIKE $2)
               AND ($3::date IS NULL OR as_of_date >= $3)
               AND ($4::date IS NULL OR as_of_date <= $4)
             ORDER BY as_of_date DESC, symbol
             LIMIT $5 OFFSET $6
            """,
            sym, pattern, d_start, d_end, page["limit"], page["offset"],
        )
    return envelope([row_to_dict(r) for r in rows], **page)
