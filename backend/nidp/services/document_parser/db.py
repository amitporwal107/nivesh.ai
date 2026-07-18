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
import os
from datetime import date
from typing import Any
from uuid import UUID

from nidp.shared.storage.pg import get_pool
from nidp.shared import embeddings as _emb
from nidp.services.corporate_announcements.taxonomy import doc_type_for_subcategory

logger = logging.getLogger(__name__)

# Bounded retry for previously-'failed' documents: transient download failures
# (NSE-archive timeouts, BSE rate-limit 403s) must self-heal, while permanently-gone
# URLs (BSE purges old AttachLive files -> 404) stop after this many attempts.
_MAX_PARSE_ATTEMPTS = int(os.environ.get("NIDP_MAX_PARSE_ATTEMPTS", "5"))

_DISCOVER_SQL = """
SELECT announcement_id, source AS announcement_source, ticker_symbol, isin,
       scrip_code, company_name, attachment_url, filed_at, subcategory
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
    $1, $10, $2, $3,
    $4, $5, $6, $7, $8,
    'pending', $9
)
ON CONFLICT (source_url) DO UPDATE
   SET announcement_id     = COALESCE(nidp.documents.announcement_id, EXCLUDED.announcement_id),
       announcement_source = COALESCE(nidp.documents.announcement_source, EXCLUDED.announcement_source)
RETURNING doc_id, parse_status
"""

_FETCH_PENDING_SQL = """
SELECT d.doc_id, d.source_url, d.ticker_symbol, d.isin, d.scrip_code, d.company_name,
       d.doc_type, ca.subject, ca.subcategory
  FROM nidp.documents d
  LEFT JOIN nidp.corporate_announcements ca
         ON ca.announcement_id = d.announcement_id
        AND ca.source          = d.announcement_source
 WHERE (d.parse_status = ANY($2::text[])
        -- Transient download failures (NSE-archive timeouts, BSE rate-limit 403s)
        -- must self-heal instead of killing the doc forever; bounded by the cap so
        -- permanently-gone URLs (404) stop retrying.
        OR (d.parse_status = 'failed' AND d.parse_attempts < $3))
   -- Shard predicate. The queue has no row claiming, so two workers would
   -- otherwise fetch identical rows and download every PDF twice. Hashing
   -- doc_id gives each worker a disjoint, stable slice with no coordination.
   -- mod(mod(h,n)+n,n) is the safe positive-modulo idiom: hashtext() returns a
   -- signed int, and abs() would error on INT_MIN. Defaults ($4=1,$5=0) match
   -- every row, so the cron's unsharded call is unaffected.
   AND mod(mod(hashtext(d.doc_id::text), $4::int) + $4::int, $4::int) = $5::int
   -- Date window. Months are naturally disjoint, so partitioning a backfill by
   -- month lets workers run on different machines with no coordination and no
   -- hash sharding — and each month is a checkpoint you can stop and resume at.
   -- filed_at (not ingested_at): the filing's own date is what a month means to
   -- a user, and it stays stable across re-ingestion. NULLs match everything.
   AND ($6::date IS NULL OR d.filed_at >= $6::date)
   AND ($7::date IS NULL OR d.filed_at <  $7::date)
 ORDER BY (d.parse_status = 'pending') DESC, d.ingested_at ASC   -- new docs before backlog retries
 LIMIT $1
"""

_UPDATE_PARSED_SQL = """
UPDATE nidp.documents
   SET parse_status        = $2,
       parse_error         = $3,
       raw_sha256          = $4,
       raw_size_bytes      = $5,
       text_size_chars     = $6,
       page_count          = $7,
       doc_type            = COALESCE($8, doc_type),
       doc_type_confidence = COALESCE($9, doc_type_confidence),
       parse_attempts      = parse_attempts + 1,
       parsed_at           = NOW()
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
                # Type the attachment from the filing's BSE subcategory so concall
                # transcripts / investor presentations become first-class corpus
                # docs (default 'announcement_attachment' for everything else).
                doc_type = doc_type_for_subcategory(a.get("subcategory"))
                row = await conn.fetchrow(
                    _INSERT_DOC_SQL,
                    a["attachment_url"],
                    a["announcement_id"], a["announcement_source"],
                    a["ticker_symbol"], a["isin"], a["scrip_code"], a["company_name"],
                    a["filed_at"],
                    source_run_id,
                    doc_type,
                )
                if row and row["parse_status"] == "pending":
                    inserted += 1
    return inserted


async def fetch_pending_docs(limit: int,
                             max_attempts: int = _MAX_PARSE_ATTEMPTS,
                             shards: int = 1,
                             shard: int = 0,
                             from_date: date | None = None,
                             to_date: date | None = None) -> list[dict[str, Any]]:
    """Documents awaiting parse: new ('pending'), OCR-retryable ('skipped_non_text'),
    and previously-'failed' docs still under the attempt cap.

    `shards`/`shard` split the queue across parallel worker processes — needed
    because pypdf is pure Python, so the GIL caps a single process at ~1 core.
    Each worker takes a disjoint hash slice. Defaults are a no-op (every row).

    The 'failed' re-queue is the fix for the terminal-failure bug: a transient
    download blip used to kill a document permanently (18,574 of 18,579 stuck on
    staging while the URLs still served HTTP 200). Bounded by max_attempts so
    genuinely-gone URLs stop instead of looping every cron tick.
    """
    # Once OCR is installed, also retry the backlog of image PDFs previously marked
    # 'skipped_non_text' — they will now be OCR'd (or marked terminal 'failed' if OCR
    # can't read them either). Without OCR, only 'pending' so we don't loop forever.
    from .pdf_extractor import ocr_available
    statuses = ["pending", "skipped_non_text"] if ocr_available() else ["pending"]
    if not 0 <= shard < shards:
        raise ValueError(f"shard {shard} out of range for shards={shards}")
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(_FETCH_PENDING_SQL, limit, statuses, max_attempts,
                                shards, shard, from_date, to_date)
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
    doc_type: str | None = None,
    doc_type_confidence: int | None = None,
) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                _UPDATE_PARSED_SQL, doc_id, parse_status, parse_error,
                raw_sha256, raw_size_bytes, text_size_chars, page_count,
                doc_type, doc_type_confidence,
            )
            if chunks:
                for c in chunks:
                    await conn.execute(
                        _INSERT_CHUNKS_SQL,
                        doc_id, c["chunk_index"], c["text"],
                        c["char_start"], c["char_end"],
                        c["page_start"], c["page_end"], c["token_count"],
                    )


# ── Embedding pass ──────────────────────────────────────────────────
# Decoupled from parsing so it also backfills any pre-existing chunk with a
# NULL embedding. Runs after parse in the same invocation; the HNSW index
# (migration 119) makes the resulting vectors searchable.
_FETCH_UNEMBEDDED_SQL = """
SELECT chunk_id, text
  FROM nidp.document_chunks
 WHERE embedding IS NULL
   AND text IS NOT NULL AND length(btrim(text)) > 0
   -- Shard predicate: with $2=1 (the default) this is always true and behaves
   -- exactly as before. With $2=N>1, each of N parallel embed workers takes a
   -- disjoint hash slice, so they never fetch the same chunk. mod(mod(h,N)+N,N)
   -- is the positive-modulo idiom — plain mod() is negative for negative
   -- hashtext() values and would collapse two shards onto one.
   AND ($2::int = 1
        OR mod(mod(hashtext(chunk_id::text), $2::int) + $2::int, $2::int) = $3::int)
 ORDER BY ingested_at ASC
 LIMIT $1
"""

_UPDATE_CHUNK_EMBEDDING_SQL = """
UPDATE nidp.document_chunks
   SET embedding       = $2::vector,
       embedding_model = $3,
       embedded_at     = NOW()
 WHERE chunk_id = $1
"""


async def embed_pending(limit: int, shards: int = 1, shard: int = 0) -> dict[str, int]:
    """Embed up to `limit` chunks that don't yet have an embedding.

    Graceful by design: if the embedder is unavailable (no key / no local model)
    or the embedding call fails, it logs and returns embedded=0 so the parser
    keeps running — the chunks remain retrievable via full-text search until
    embeddings land.

    shards/shard: for parallel drains. Pass shards=N, shard=0..N-1 to give each
    worker a disjoint hash slice of the unembedded chunks so N processes can run
    at once without double-embedding. Default (1, 0) = no sharding, unchanged.
    """
    if not _emb.is_configured():
        logger.warning("embed_pending: embedder not configured — skipping embedding pass")
        return {"embedded": 0, "candidates": 0}
    if not 0 <= shard < shards:
        raise ValueError(f"shard {shard} out of range for shards={shards}")

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(_FETCH_UNEMBEDDED_SQL, limit, shards, shard)
    if not rows:
        return {"embedded": 0, "candidates": 0}

    try:
        vectors = await _emb.embed_texts([r["text"] for r in rows])
    except _emb.EmbeddingError as e:
        logger.warning("embed_pending: embedding call failed: %s", e)
        return {"embedded": 0, "candidates": len(rows)}

    embedded = 0
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            for r, vec in zip(rows, vectors):
                await conn.execute(
                    _UPDATE_CHUNK_EMBEDDING_SQL,
                    r["chunk_id"], _emb.to_pgvector_literal(vec), _emb.EMBED_MODEL,
                )
                embedded += 1
    logger.info("embed_pending: embedded %d/%d chunks (model=%s)",
                embedded, len(rows), _emb.EMBED_MODEL)
    return {"embedded": embedded, "candidates": len(rows)}
