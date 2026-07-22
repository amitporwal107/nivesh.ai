"""DB access for filing_insights — select material filings with parsed text,
write the generated insight.

Materiality (docs/FILINGS_HOME_SPEC.md §4.1, measured): a classified announcement
whose event_category is present and NOT in ('regulatory','other') and whose
impact_score is present, filed within the 30-day classifier window. It must also
have a PARSED document with chunk text — the insight is generated from the PDF,
never from the boilerplate `subject`/`description`.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from nidp.shared.storage.pg import get_pool

logger = logging.getLogger(__name__)

# Work queue: material announcements that (a) have a parsed doc and (b) do not yet
# have a filing_insight row. LATERAL picks the richest parsed doc for the filing
# (prefer results/press-release/presentation over a bare attachment, then newest).
# We only need the doc_id here; the text is fetched per-row so one giant filing
# can't blow the memory of the batch.
_FETCH_SQL = """
SELECT a.announcement_id,
       a.source,
       a.ticker_symbol,
       a.company_name,
       a.event_category,
       a.impact_score,
       a.sentiment,
       a.subject,
       a.filed_at,
       d.doc_id,
       d.doc_type
  FROM nidp.corporate_announcements a
  JOIN LATERAL (
        SELECT dd.doc_id, dd.doc_type
          FROM nidp.documents dd
         WHERE dd.announcement_id = a.announcement_id
           AND dd.announcement_source = a.source
           AND dd.parse_status = 'parsed'
         ORDER BY CASE dd.doc_type
                    WHEN 'financial_results'      THEN 0
                    WHEN 'press_release'          THEN 1
                    WHEN 'investor_presentation'  THEN 2
                    WHEN 'concall_transcript'     THEN 3
                    ELSE 9
                  END,
                  dd.filed_at DESC NULLS LAST
         LIMIT 1
       ) d ON TRUE
 WHERE a.filed_at >= NOW() - INTERVAL '30 days'
   AND a.event_category IS NOT NULL
   AND a.event_category NOT IN ('regulatory', 'other')
   AND a.impact_score IS NOT NULL
   AND NOT EXISTS (
        SELECT 1 FROM nidp.corporate_event_signals s
         WHERE s.signal_type = 'filing_insight'
           AND s.announcement_ref = a.announcement_id
           AND s.announcement_source = a.source
       )
 ORDER BY (a.impact_score = 'high') DESC NULLS LAST, a.filed_at DESC
 LIMIT $1
"""

# Reassemble the parsed PDF text in reading order (same pattern the DaaS
# documents router uses). Bounded so a pathological filing can't send an
# unbounded prompt to the model.
_CHUNKS_SQL = """
SELECT text, page_start, page_end
  FROM nidp.document_chunks
 WHERE doc_id = $1
 ORDER BY chunk_index
 LIMIT $2
"""

_UPSERT_SQL = """
INSERT INTO nidp.corporate_event_signals
    (symbol, event_type, event_date, period, sentiment, confidence,
     signal_json, announcement_ref, announcement_source, signal_type,
     model_used, analysed_at)
VALUES
    ($1, $2, $3, $4, $5, $6,
     $7::jsonb, $8, $9, 'filing_insight',
     $10, NOW())
ON CONFLICT (announcement_ref, announcement_source)
    WHERE signal_type = 'filing_insight'
DO UPDATE SET
     symbol       = EXCLUDED.symbol,
     event_type   = EXCLUDED.event_type,
     event_date   = EXCLUDED.event_date,
     period       = EXCLUDED.period,
     sentiment    = EXCLUDED.sentiment,
     confidence   = EXCLUDED.confidence,
     signal_json  = EXCLUDED.signal_json,
     model_used   = EXCLUDED.model_used,
     analysed_at  = NOW()
"""


async def fetch_material_pending(limit: int) -> list[dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(_FETCH_SQL, limit)
    return [dict(r) for r in rows]


async def fetch_doc_text(doc_id, max_chunks: int) -> tuple[str, Optional[int]]:
    """Reassemble the parsed PDF in reading order, annotated with `[[page N]]`
    rules at each page boundary, plus the highest page number present.

    The markers are what let the generator cite a real page range instead of
    guessing one, and `max_page` is what lets us throw away a citation that
    points past the end of the document (generator._clean_sections).
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(_CHUNKS_SQL, doc_id, max_chunks)

    parts: list[str] = []
    max_page: Optional[int] = None
    last_page: Optional[int] = None
    for r in rows:
        if not r["text"]:
            continue
        start, end = r["page_start"], r["page_end"]
        if start is not None and start != last_page:
            parts.append(f"[[page {start}]]")
            last_page = start
        for p in (start, end):
            if p is not None and (max_page is None or p > max_page):
                max_page = p
        parts.append(r["text"])
    return "\n\n".join(parts), max_page


async def store_insight(
    *,
    symbol: str,
    event_type: str,
    event_date,
    period: Optional[str],
    sentiment: str,
    confidence: Optional[float],
    signal_json: str,
    announcement_ref: str,
    announcement_source: str,
    model_used: str,
) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            _UPSERT_SQL,
            symbol, event_type, event_date, period, sentiment, confidence,
            signal_json, announcement_ref, announcement_source, model_used,
        )
