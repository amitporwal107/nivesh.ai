"""DB access for the announcement classifier — read unclassified, write results."""
from __future__ import annotations

import logging
from typing import Any

from nidp.shared.storage.pg import get_pool

logger = logging.getLogger(__name__)

# $2 = window in days; 0 means "no window". A fixed 30-day window permanently stranded
# every older unclassified row: 42,359 rows sat outside it with no run able to reach them.
#
# filing_text (2026-09-17): many filings carry their substance only in the attached PDF —
# the subject/description are boilerplate ("General Updates", "Announcement Pursuant To
# Reg. 30 Of The SEBI LODR Regulations, 2015.") while the parsed attachment states the real
# content (e.g. Tega's preferential-issue price and use of proceeds). 97% of currently
# unclassified rows already have a parsed document sitting unused. The LEFT JOIN LATERAL
# concatenates the first 3 parsed chunks (in page order) per announcement, capped so a long
# annual-report-style attachment cannot blow the prompt; NULL when nothing is parsed yet, in
# which case the classifier falls back to subject/description exactly as before.
_FETCH_SQL = """
SELECT a.announcement_id, a.source, a.ticker_symbol, a.isin, a.scrip_code, a.company_name,
       a.subject, a.description, a.raw_category, doc.filing_text
  FROM nidp.corporate_announcements a
  LEFT JOIN LATERAL (
        SELECT left(string_agg(c.text, E'\n' ORDER BY c.chunk_index), 4000) AS filing_text
          FROM nidp.documents d
          JOIN nidp.document_chunks c ON c.doc_id = d.doc_id AND c.chunk_index < 3
         WHERE d.announcement_id = a.announcement_id AND d.announcement_source = a.source
           AND d.parse_status = 'parsed'
       ) doc ON true
 WHERE a.event_category IS NULL
   AND ($2::int = 0 OR a.filed_at >= NOW() - make_interval(days => $2::int))
 ORDER BY a.filed_at ASC  -- oldest first: newest-first starves the backlog once behind
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


async def fetch_unclassified(limit: int, days: int = 30) -> list[dict[str, Any]]:
    """Oldest unclassified announcements; `days` bounds how far back to look (0 = all)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(_FETCH_SQL, limit, days)
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
