"""DB access for the announcement classifier — read unclassified, write results."""
from __future__ import annotations

import logging
from typing import Any

from nidp.shared.storage.pg import get_pool

logger = logging.getLogger(__name__)

_FETCH_SQL = """
SELECT announcement_id, source, ticker_symbol, isin, scrip_code, company_name,
       subject, description, raw_category
  FROM nidp.corporate_announcements
 WHERE event_category IS NULL
   AND filed_at >= NOW() - INTERVAL '30 days'
 ORDER BY filed_at DESC
 LIMIT $1
"""

_UPDATE_SQL = """
UPDATE nidp.corporate_announcements
   SET event_category     = $3,
       impact_score       = $4,
       sentiment          = $5,
       classifier_version = $6,
       classified_at      = NOW()
 WHERE announcement_id = $1 AND source = $2
"""


async def fetch_unclassified(limit: int) -> list[dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(_FETCH_SQL, limit)
    return [dict(r) for r in rows]


async def store_classification(
    announcement_id: str,
    source: str,
    *,
    event_category: str,
    impact_score: str,
    sentiment: str,
    classifier_version: str,
) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            _UPDATE_SQL, announcement_id, source,
            event_category, impact_score, sentiment, classifier_version,
        )
