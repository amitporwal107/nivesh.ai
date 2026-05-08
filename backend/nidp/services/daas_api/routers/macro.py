"""Macro — Indian rate curve (RBI G-Sec) + global FRED series."""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query

from nidp.shared.storage.pg import get_pool
from nidp.services.daas_api.auth import require_api_key
from nidp.services.daas_api.responses import envelope, page_params, parse_date, row_to_dict


router = APIRouter(prefix="/macro", tags=["macro"], dependencies=[Depends(require_api_key)])


@router.get("/rbi-yields", summary="Indian G-Sec / T-bill / repo yields")
async def rbi_yields(
    tenor: Optional[str] = Query(None, description="OVERNIGHT | 91D | 364D | 1Y | 5Y | 10Y"),
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
            SELECT as_of_date, tenor, instrument, yield_pct
              FROM nidp.rbi_yields
             WHERE ($1::text IS NULL OR tenor = $1)
               AND ($2::date IS NULL OR as_of_date >= $2)
               AND ($3::date IS NULL OR as_of_date <= $3)
             ORDER BY as_of_date DESC, tenor
             LIMIT $4 OFFSET $5
            """,
            tenor, d_start, d_end, page["limit"], page["offset"],
        )
    return envelope([row_to_dict(r) for r in rows], **page)


@router.get("/fred", summary="Global macro series from FRED (US10Y, DXY, VIX, …)")
async def fred(
    series_id: Optional[str] = Query(None, description="FRED series id, e.g. DGS10, VIXCLS, DTWEXBGS"),
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
            SELECT as_of_date, series_id, series_name, value, units, frequency
              FROM nidp.fred_macro
             WHERE ($1::text IS NULL OR series_id = $1)
               AND ($2::date IS NULL OR as_of_date >= $2)
               AND ($3::date IS NULL OR as_of_date <= $3)
             ORDER BY as_of_date DESC, series_id
             LIMIT $4 OFFSET $5
            """,
            series_id, d_start, d_end, page["limit"], page["offset"],
        )
    return envelope([row_to_dict(r) for r in rows], **page)


@router.get("/fred/series", summary="Distinct FRED series we track")
async def fred_series() -> Dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT series_id, MAX(series_name) AS series_name,
                   MAX(units) AS units, MAX(frequency) AS frequency,
                   COUNT(*) AS observations,
                   MIN(as_of_date) AS first_date, MAX(as_of_date) AS last_date
              FROM nidp.fred_macro
             GROUP BY series_id
             ORDER BY series_id
            """
        )
    return {"data": [row_to_dict(r) for r in rows], "count": len(rows)}
