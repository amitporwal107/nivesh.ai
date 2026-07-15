"""DB access for document_parser.

Two phases:
  1. discover()  — find announcements with attachment_url that haven't
                   been registered as documents yet, INSERT one row each
                   into nidp.documents with parse_status='pending'.
  2. parse_pending() — for each pending document, download → extract →
                   chunk → UPDATE document row + INSERT chunks.

Splitting these phases means a fetch outage doesn't lose the queue: the
documents table IS the queue.
"""
from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from nidp.shared.storage.pg import get_pool

logger = logging.getLogger(__name__)

_DISCOVER_SQL = """
SELECT announcement_id, source AS announcement_source, ticker_symbol, isin,
       scrip_code, company_name, attachment_url, filed_at
  FROM nidp.v_announcements_needing_documents
 ORDER BY filed_at DESC
 LIMIT $1
"""

_INSERT_DOC_SQL = """
INSERT INTO nidp.documents (
    source_url, doc_type, announcement_id, announcement_source,
    ticker_symbol, isin, scrip_code, company_name, filed_at,
    parse_status, source_run_id
) VALUES (
    $1, 'announcement_attachment', $2, $3,
    $4, $5, $6, $7, $8,
    'pending', $9
)
ON CONFLICT (source_url) DO UPDATE
   SET announcement_id     = COALESCE(nidp.documents.announcement_id, EXCLUDED.announcement_id),
       announcement_source = COALESCE(nidp.documents.announcement_source, EXCLUDED.announcement_source)
RETURNING doc_id, parse_status
"""

_FETCH_PENDING_SQL = """
SELECT doc_id, source_url, ticker_symbol, isin, scrip_code, company_name
  FROM nidp.documents
 WHERE parse_status = ANY($2::text[])
 ORDER BY (parse_status = 'pending') DESC, ingested_at ASC   -- new docs before backlog retries
 LIMIT $1
"""

_UPDATE_PARSED_SQL = """
UPDATE nidp.documents
   SET parse_status    = $2,
       parse_error     = $3,
       raw_sha256      = $4,
       raw_size_bytes  = $5,
       text_size_chars = $6,
       page_count      = $7,
       parsed_at       = NOW()
 WHERE doc_id = $1
"""

_INSERT_CHUNKS_SQL = """
INSERT INTO nidp.document_chunks (
    doc_id, chunk_index, text, char_start, char_end,
    page_start, page_end, token_count
) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
ON CONFLICT (doc_id, chunk_index) DO UPDATE
   SET text        = EXCLUDED.text,
       char_start  = EXCLUDED.char_start,
       char_end    = EXCLUDED.char_end,
       page_start  = EXCLUDED.page_start,
       page_end    = EXCLUDED.page_end,
       token_count = EXCLUDED.token_count
"""


async def discover_pending(limit: int, source_run_id: UUID) -> int:
    """Insert documents rows for announcements with attachment_url not yet registered."""
    pool = await get_pool()
    inserted = 0
    async with pool.acquire() as conn:
        anns = await conn.fetch(_DISCOVER_SQL, limit)
        async with conn.transaction():
            for a in anns:
                row = await conn.fetchrow(
                    _INSERT_DOC_SQL,
                    a["attachment_url"],
                    a["announcement_id"], a["announcement_source"],
                    a["ticker_symbol"], a["isin"], a["scrip_code"], a["company_name"],
                    a["filed_at"],
                    source_run_id,
                )
                if row and row["parse_status"] == "pending":
                    inserted += 1
    return inserted


async def fetch_pending_docs(limit: int) -> list[dict[str, Any]]:
    # Once OCR is installed, also retry the backlog of image PDFs previously marked
    # 'skipped_non_text' — they will now be OCR'd (or marked terminal 'failed' if OCR
    # can't read them either). Without OCR, only 'pending' so we don't loop forever.
    from .pdf_extractor import ocr_available
    statuses = ["pending", "skipped_non_text"] if ocr_available() else ["pending"]
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(_FETCH_PENDING_SQL, limit, statuses)
    return [dict(r) for r in rows]


async def store_parse_result(
    doc_id: UUID,
    *,
    parse_status: str,
    parse_error: str | None,
    raw_sha256: str | None,
    raw_size_bytes: int | None,
    text_size_chars: int | None,
    page_count: int | None,
    chunks: list[dict] | None,
) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                _UPDATE_PARSED_SQL, doc_id, parse_status, parse_error,
                raw_sha256, raw_size_bytes, text_size_chars, page_count,
            )
            if chunks:
                for c in chunks:
                    await conn.execute(
                        _INSERT_CHUNKS_SQL,
                        doc_id, c["chunk_index"], c["text"],
                        c["char_start"], c["char_end"],
                        c["page_start"], c["page_end"], c["token_count"],
                    )
