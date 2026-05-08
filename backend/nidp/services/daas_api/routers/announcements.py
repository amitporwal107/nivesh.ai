"""Real-time exchange announcements (NSE + BSE), with classification fields
filled in async by the Haiku classifier."""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Path, Query

from nidp.shared.storage.pg import get_pool
from nidp.services.daas_api.auth import require_api_key
from nidp.services.daas_api.responses import envelope, normalise_symbol, page_params, parse_date, row_to_dict


router = APIRouter(prefix="/announcements", tags=["announcements"],
                   dependencies=[Depends(require_api_key)])


@router.get("", summary="Recent corporate filings (filterable)")
async def announcements(
    symbol: Optional[str] = Query(None),
    impact: Optional[str] = Query(None, description="high | medium | low"),
    category: Optional[str] = Query(None, description="orders | mna | earnings | capex | …"),
    sentiment: Optional[str] = Query(None, description="positive | neutral | negative"),
    source: Optional[str] = Query(None, description="NSE_ANN | BSE_ANN | RBI | SEBI | PIB"),
    filed_from: Optional[str] = Query(None, description="ISO timestamp or YYYY-MM-DD"),
    filed_to: Optional[str] = Query(None),
    page: Dict[str, int] = Depends(page_params),
) -> Dict[str, Any]:
    sym = normalise_symbol(symbol) if symbol else None
    d_from = parse_date(filed_from, field="filed_from") if filed_from and len(filed_from) == 10 else None
    d_to = parse_date(filed_to, field="filed_to") if filed_to and len(filed_to) == 10 else None
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT announcement_id, source, ticker_symbol, isin, scrip_code,
                   company_name, filed_at, broadcast_at, subject, raw_category,
                   attachment_url, event_category, impact_score, sentiment,
                   classifier_version, classified_at
              FROM nidp.corporate_announcements
             WHERE ($1::text IS NULL OR ticker_symbol = $1)
               AND ($2::text IS NULL OR impact_score = $2)
               AND ($3::text IS NULL OR event_category = $3)
               AND ($4::text IS NULL OR sentiment = $4)
               AND ($5::text IS NULL OR source = $5)
               AND ($6::date IS NULL OR filed_at::date >= $6)
               AND ($7::date IS NULL OR filed_at::date <= $7)
             ORDER BY filed_at DESC
             LIMIT $8 OFFSET $9
            """,
            sym, impact, category, sentiment, source,
            d_from, d_to,
            page["limit"], page["offset"],
        )
    return envelope([row_to_dict(r) for r in rows], **page)


@router.get("/{announcement_id}", summary="Full announcement record (incl. body text)")
async def announcement_detail(announcement_id: str = Path(...)) -> Dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT announcement_id, source, ticker_symbol, isin, scrip_code,
                   company_name, filed_at, broadcast_at, subject, description,
                   raw_category, attachment_url, event_category, impact_score,
                   sentiment, classifier_version, classified_at, ingested_at
              FROM nidp.corporate_announcements
             WHERE announcement_id = $1
             ORDER BY ingested_at DESC
             LIMIT 1
            """,
            announcement_id,
        )
    if row is None:
        return {"data": None, "error": "not_found"}
    return {"data": row_to_dict(row)}
