"""Postgres writer for nidp.corporate_announcements.

Upsert on (announcement_id, source). Re-fetches of the same window are
no-ops on the row body but bump ingested_at + source_run_id so we can
trace which run last touched a record.
"""
from __future__ import annotations

import json
import logging
from typing import Iterable
from uuid import UUID

from nidp.shared.storage.pg import get_pool

logger = logging.getLogger(__name__)

SOURCE_NAME = "NSE_ANN"

_UPSERT_SQL = """
INSERT INTO nidp.corporate_announcements (
    announcement_id, source, ticker_symbol, isin, scrip_code, company_name,
    filed_at, broadcast_at, subject, description, raw_category, subcategory, attachment_url,
    source_run_id, raw_payload
) VALUES (
    $1,$2,$3,$4,$5,$6,
    $7,$8,$9,$10,$11,$12,$13,
    $14,$15::jsonb
)
ON CONFLICT (announcement_id, source) DO UPDATE SET
    ticker_symbol  = EXCLUDED.ticker_symbol,
    isin           = EXCLUDED.isin,
    scrip_code     = EXCLUDED.scrip_code,
    company_name   = EXCLUDED.company_name,
    broadcast_at   = EXCLUDED.broadcast_at,
    subject        = EXCLUDED.subject,
    description    = COALESCE(EXCLUDED.description, nidp.corporate_announcements.description),
    raw_category   = EXCLUDED.raw_category,
    -- keep an existing (subcategory-sweep) value if a later coarse sweep re-upserts NULL
    subcategory    = COALESCE(EXCLUDED.subcategory, nidp.corporate_announcements.subcategory),
    attachment_url = EXCLUDED.attachment_url,
    source_run_id  = EXCLUDED.source_run_id,
    raw_payload    = EXCLUDED.raw_payload,
    ingested_at    = NOW();
"""


async def upsert_announcements(rows: Iterable[dict], source_run_id: UUID) -> int:
    rows = list(rows)
    if not rows:
        return 0
    pool = await get_pool()
    n = 0
    async with pool.acquire() as conn:
        async with conn.transaction():
            for r in rows:
                await conn.execute(
                    _UPSERT_SQL,
                    r["announcement_id"],
                    r["source"],
                    r.get("ticker_symbol"),
                    r.get("isin"),
                    r.get("scrip_code"),
                    r.get("company_name"),
                    r["filed_at"],
                    r.get("broadcast_at"),
                    r.get("subject"),
                    r.get("description"),
                    r.get("raw_category"),
                    r.get("subcategory"),
                    r.get("attachment_url"),
                    source_run_id,
                    json.dumps(r.get("raw_payload") or {}, default=str),
                )
                n += 1
    logger.info("writer: upserted %d announcements (run=%s)", n, source_run_id)
    return n
