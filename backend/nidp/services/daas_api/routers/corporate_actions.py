"""Corporate-action calendar — splits, bonuses, dividends, rights, mergers."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Path, Query

from nidp.shared.storage.pg import get_pool
from nidp.services.daas_api.auth import require_api_key
from nidp.services.daas_api.responses import (
    envelope, normalise_symbol, page_params, parse_date, row_to_dict,
)


router = APIRouter(prefix="/corporate-actions", tags=["corporate-actions"],
                   dependencies=[Depends(require_api_key)])


_VALID_TYPES = {
    "DIVIDEND", "SPLIT", "BONUS", "RIGHTS", "MERGER",
    "DEMERGER", "BUYBACK", "AGM", "BOARD_MEETING", "OTHER",
}


@router.get("", summary="Corporate-action calendar (filterable)")
async def corp_actions(
    symbol: Optional[str] = Query(None),
    action_type: Optional[str] = Query(None, description=f"One of: {sorted(_VALID_TYPES)}"),
    ex_from: Optional[str] = Query(None, description="Inclusive ex-date floor"),
    ex_to: Optional[str] = Query(None, description="Inclusive ex-date ceiling"),
    page: Dict[str, int] = Depends(page_params),
) -> Dict[str, Any]:
    sym = normalise_symbol(symbol) if symbol else None
    a_type = action_type.upper() if action_type else None
    if a_type and a_type not in _VALID_TYPES:
        a_type = None      # silently ignore — unknown filter shouldn't 400
    d_from = parse_date(ex_from, field="ex_from")
    d_to = parse_date(ex_to, field="ex_to")
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT symbol, series, action_type, action_subtype, purpose,
                   ratio, face_value_pre, face_value_post, dividend_amount,
                   record_date, ex_date, bc_start_date, bc_end_date,
                   announcement_date
              FROM nidp.corporate_actions
             WHERE ($1::text IS NULL OR symbol = $1)
               AND ($2::text IS NULL OR action_type = $2)
               AND ($3::date IS NULL OR ex_date >= $3)
               AND ($4::date IS NULL OR ex_date <= $4)
             ORDER BY ex_date DESC, symbol
             LIMIT $5 OFFSET $6
            """,
            sym, a_type, d_from, d_to,
            page["limit"], page["offset"],
        )
    return envelope([row_to_dict(r) for r in rows], **page)


@router.get("/{symbol}", summary="Corporate actions for one symbol")
async def corp_actions_for_symbol(
    symbol: str = Path(...),
    action_type: Optional[str] = Query(None),
    page: Dict[str, int] = Depends(page_params),
) -> Dict[str, Any]:
    sym = normalise_symbol(symbol)
    a_type = action_type.upper() if action_type else None
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT symbol, series, action_type, action_subtype, purpose,
                   ratio, face_value_pre, face_value_post, dividend_amount,
                   record_date, ex_date, announcement_date
              FROM nidp.corporate_actions
             WHERE symbol = $1
               AND ($2::text IS NULL OR action_type = $2)
             ORDER BY ex_date DESC
             LIMIT $3 OFFSET $4
            """,
            sym, a_type, page["limit"], page["offset"],
        )
    return envelope([row_to_dict(r) for r in rows], **page, extra={"symbol": sym})
