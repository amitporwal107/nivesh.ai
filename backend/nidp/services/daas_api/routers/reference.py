"""Reference data — symbols, sectors, holidays."""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query

from nidp.shared.storage.pg import get_pool
from nidp.services.daas_api.auth import require_api_key
from nidp.services.daas_api.responses import envelope, normalise_symbol, page_params, parse_date, row_to_dict


router = APIRouter(prefix="", tags=["reference"], dependencies=[Depends(require_api_key)])


@router.get("/symbols", summary="Symbol master — symbol, company, sector, ISIN")
async def symbols(
    sector: Optional[str] = Query(None),
    series: Optional[str] = Query(None, description="EQ | BE | BZ"),
    page: Dict[str, int] = Depends(page_params),
) -> Dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT symbol, company_name, series, isin,
                   listing_date, face_value, market_lot,
                   sector, industry
              FROM nidp.sector_master
             WHERE ($1::text IS NULL OR sector = $1)
               AND ($2::text IS NULL OR series = $2)
             ORDER BY symbol
             LIMIT $3 OFFSET $4
            """,
            sector, series, page["limit"], page["offset"],
        )
    return envelope([row_to_dict(r) for r in rows], **page)


@router.get("/symbols/search", summary="Substring search over symbol + company name")
async def symbols_search(
    q: str = Query(..., min_length=1, max_length=64),
    limit: int = Query(20, ge=1, le=100),
) -> Dict[str, Any]:
    needle = f"%{q.strip().upper()}%"
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT symbol, company_name, sector, industry, isin
              FROM nidp.sector_master
             WHERE UPPER(symbol) LIKE $1
                OR UPPER(company_name) LIKE $1
             ORDER BY
                CASE WHEN UPPER(symbol) = $2 THEN 0
                     WHEN UPPER(symbol) LIKE $2 || '%' THEN 1
                     ELSE 2 END,
                symbol
             LIMIT $3
            """,
            needle, q.strip().upper(), limit,
        )
    return {"data": [row_to_dict(r) for r in rows], "count": len(rows), "query": q}


@router.get("/symbols/{symbol}", summary="Symbol master row for one ticker")
async def symbol_detail(symbol: str) -> Dict[str, Any]:
    sym = normalise_symbol(symbol)
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT symbol, company_name, series, isin,
                   listing_date, face_value, paid_up_value, market_lot,
                   sector, industry, sector_source
              FROM nidp.sector_master
             WHERE symbol = $1
            """,
            sym,
        )
    if row is None:
        return {"data": None, "error": "not_found"}
    return {"data": row_to_dict(row)}


@router.get("/sectors", summary="Distinct sector list with member counts")
async def sectors() -> Dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT sector, COUNT(*) AS symbols, COUNT(industry) AS industries_resolved
              FROM nidp.sector_master
             WHERE sector IS NOT NULL
             GROUP BY sector
             ORDER BY symbols DESC
            """
        )
    return {"data": [row_to_dict(r) for r in rows], "count": len(rows)}


@router.get("/holidays", summary="NSE trading holidays")
async def holidays(
    segment: str = Query("CM", description="CM | FO | CD | COM | DEBT | MF"),
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    page: Dict[str, int] = Depends(page_params),
) -> Dict[str, Any]:
    d_from = parse_date(from_date, field="from")
    d_to = parse_date(to_date, field="to")
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT holiday_date, segment, description
              FROM nidp.nse_holidays
             WHERE segment = $1
               AND ($2::date IS NULL OR holiday_date >= $2)
               AND ($3::date IS NULL OR holiday_date <= $3)
             ORDER BY holiday_date
             LIMIT $4 OFFSET $5
            """,
            segment, d_from, d_to, page["limit"], page["offset"],
        )
    return envelope([row_to_dict(r) for r in rows], **page, extra={"segment": segment})
