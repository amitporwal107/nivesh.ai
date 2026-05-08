"""Index reference — list of indices we track + effective-dated constituents."""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Path, Query

from nidp.shared.storage.pg import get_pool
from nidp.services.daas_api.auth import require_api_key
from nidp.services.daas_api.responses import envelope, page_params, parse_date, row_to_dict


router = APIRouter(prefix="/indices", tags=["indices"], dependencies=[Depends(require_api_key)])


@router.get("", summary="Distinct list of indices we track")
async def list_indices() -> Dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT index_name,
                   COUNT(*) AS days_tracked,
                   MIN(as_of_date) AS first_date,
                   MAX(as_of_date) AS latest_date
              FROM nidp.index_eod
             GROUP BY index_name
             ORDER BY index_name
            """
        )
    return {"data": [row_to_dict(r) for r in rows], "count": len(rows)}


@router.get("/{index_name}/constituents", summary="Effective-dated constituent list")
async def index_constituents(
    index_name: str = Path(..., description="e.g. 'Nifty 50', 'Nifty 500'"),
    on: Optional[str] = Query(None, description="Effective date YYYY-MM-DD; defaults to most recent"),
    page: Dict[str, int] = Depends(page_params),
) -> Dict[str, Any]:
    on_date = parse_date(on, field="on")
    pool = await get_pool()
    async with pool.acquire() as conn:
        if on_date is None:
            row = await conn.fetchrow(
                "SELECT MAX(as_of_date) AS d FROM nidp.index_constituents WHERE index_name = $1",
                index_name,
            )
            on_date = row["d"] if row else None
        if on_date is None:
            return envelope([], limit=page["limit"], offset=page["offset"],
                            extra={"index_name": index_name, "as_of": None})
        rows = await conn.fetch(
            """
            SELECT as_of_date, index_name, symbol, isin, company_name,
                   industry, weight_pct
              FROM nidp.index_constituents
             WHERE index_name = $1 AND as_of_date = $2
             ORDER BY weight_pct DESC NULLS LAST, symbol
             LIMIT $3 OFFSET $4
            """,
            index_name, on_date, page["limit"], page["offset"],
        )
    return envelope(
        [row_to_dict(r) for r in rows],
        **page,
        extra={"index_name": index_name, "as_of": on_date.isoformat()},
    )
