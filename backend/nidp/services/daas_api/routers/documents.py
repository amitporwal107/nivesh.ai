"""Hybrid search over ingested document CHUNKS — concall transcripts, investor
presentations, annual reports. Returns the matching passage plus its page span and
source PDF, so the answer layer can quote what management said with a page-level
citation. Complements /announcements (filing metadata) with document *content*.

Retrieval is HYBRID: pgvector cosine (OpenAI text-embedding-3-small) fused with
Postgres full-text via Reciprocal Rank Fusion. When the query can't be embedded
(no OPENAI_API_KEY) or no chunk is embedded yet, it degrades cleanly to FTS-only.
Both legs use the `english` tsvector config, matching the GIN + HNSW indexes from
migration 119.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query

from nidp.shared.storage.pg import get_pool, prepare_vector_search
from nidp.shared import embeddings as _emb
from nidp.services.daas_api.auth import require_api_key
from nidp.services.daas_api.responses import envelope, normalise_symbol, page_params, row_to_dict


router = APIRouter(prefix="/documents", tags=["documents"],
                   dependencies=[Depends(require_api_key)])

# RRF fuses two rankings scale-free: score = Σ 1/(K + rank). K=60 is the standard
# constant. Each leg pulls a candidate pool larger than the final page so fusion
# has room to reorder.
_RRF_K = 60

_HYBRID_SQL = """
WITH vec AS (
    SELECT c.chunk_id,
           row_number() OVER (ORDER BY c.embedding <=> $1::vector) AS rnk
      FROM nidp.document_chunks c
      JOIN nidp.documents d USING (doc_id)
     WHERE d.parse_status = 'parsed'
       AND c.embedding IS NOT NULL
       AND ($3::text[] IS NULL OR d.doc_type = ANY($3::text[]))
       AND ($4::text   IS NULL OR d.ticker_symbol = $4)
     ORDER BY c.embedding <=> $1::vector
     LIMIT $7
),
fts AS (
    SELECT c.chunk_id,
           row_number() OVER (
               ORDER BY ts_rank(to_tsvector('english', c.text),
                                plainto_tsquery('english', $2)) DESC
           ) AS rnk
      FROM nidp.document_chunks c
      JOIN nidp.documents d USING (doc_id)
     WHERE d.parse_status = 'parsed'
       AND ($3::text[] IS NULL OR d.doc_type = ANY($3::text[]))
       AND ($4::text   IS NULL OR d.ticker_symbol = $4)
       AND to_tsvector('english', c.text) @@ plainto_tsquery('english', $2)
     ORDER BY rnk
     LIMIT $7
),
fused AS (
    SELECT chunk_id,
           COALESCE(1.0 / ($8 + vec.rnk), 0) + COALESCE(1.0 / ($8 + fts.rnk), 0) AS score
      FROM vec FULL OUTER JOIN fts USING (chunk_id)
)
SELECT c.chunk_id, c.doc_id, c.chunk_index, c.text,
       c.page_start, c.page_end,
       d.doc_type, d.ticker_symbol, d.company_name, d.filed_at, d.source_url,
       f.score AS rank
  FROM fused f
  JOIN nidp.document_chunks c USING (chunk_id)
  JOIN nidp.documents d USING (doc_id)
 ORDER BY f.score DESC, d.filed_at DESC NULLS LAST
 LIMIT $5 OFFSET $6
"""

_FTS_SQL = """
SELECT c.chunk_id, c.doc_id, c.chunk_index, c.text,
       c.page_start, c.page_end,
       d.doc_type, d.ticker_symbol, d.company_name, d.filed_at, d.source_url,
       ts_rank(to_tsvector('english', c.text),
               plainto_tsquery('english', $1)) AS rank
  FROM nidp.document_chunks c
  JOIN nidp.documents d USING (doc_id)
 WHERE d.parse_status = 'parsed'
   AND ($2::text[] IS NULL OR d.doc_type = ANY($2::text[]))
   AND ($3::text   IS NULL OR d.ticker_symbol = $3)
   AND to_tsvector('english', c.text) @@ plainto_tsquery('english', $1)
 ORDER BY rank DESC, d.filed_at DESC NULLS LAST
 LIMIT $4 OFFSET $5
"""


# doc_parser tags ALL auto-ingested PDFs as 'announcement_attachment' — and in
# India, earnings-call transcripts + investor presentations are FILED as
# announcements, so their chunks live under that doc_type too. Therefore the
# default search spans ALL doc_types (announcement_attachment / concall_transcript
# / investor_presentation / annual_report); pass ?doc_type= to narrow.
@router.get("/search", summary="Hybrid (vector + keyword) search over document chunks")
async def documents_search(
    q: str = Query(..., min_length=2, max_length=256, description="free-text query"),
    symbol: Optional[str] = Query(None, description="restrict to one ticker"),
    doc_type: Optional[str] = Query(None, description="announcement_attachment | concall_transcript | investor_presentation | annual_report"),
    page: Dict[str, int] = Depends(page_params),
) -> Dict[str, Any]:
    sym = normalise_symbol(symbol) if symbol else None
    doc_types: Optional[List[str]] = [doc_type] if doc_type else None  # None → all types

    # Embed the query for the vector leg (graceful: None → FTS-only path).
    qvec: Optional[List[float]] = None
    if _emb.is_configured():
        try:
            qvec = await _emb.embed_query(q)
        except _emb.EmbeddingError:
            qvec = None

    pool = await get_pool()
    async with pool.acquire() as conn:
        if qvec is not None:
            # Without this the vector leg returns 0 rows whenever `symbol` or
            # `doc_type` is set — see prepare_vector_search() for the measurement.
            await prepare_vector_search(conn)
            candidate_pool = min(200, max(50, page["limit"] + page["offset"]))
            rows = await conn.fetch(
                _HYBRID_SQL,
                _emb.to_pgvector_literal(qvec),         # $1
                q,                                       # $2
                doc_types,                               # $3
                sym,                                     # $4
                page["limit"],                           # $5
                page["offset"],                          # $6
                candidate_pool,                          # $7
                _RRF_K,                                  # $8
            )
            mode = "hybrid"
        else:
            rows = await conn.fetch(
                _FTS_SQL, q, doc_types, sym, page["limit"], page["offset"],
            )
            mode = "fts"

    return envelope([row_to_dict(r) for r in rows], **page,
                    extra={"query": q, "doc_types": doc_types or "all", "mode": mode})


@router.get("/filing", summary="Full text of the latest matching filing (per-filing content)")
async def filing_content(
    symbol: str = Query(..., description="ticker"),
    doc_type: Optional[str] = Query(None, description="narrow to a doc_type; default = most recent parsed filing"),
    page: Dict[str, int] = Depends(page_params),
) -> Dict[str, Any]:
    """Per-filing full text: the most recent PARSED document for the ticker (optionally
    of a given doc_type), with its chunks in order + a joined full_text — for deep-context
    reading once search has identified the company/filing."""
    sym = normalise_symbol(symbol)
    pool = await get_pool()
    async with pool.acquire() as conn:
        doc = await conn.fetchrow(
            """
            SELECT doc_id, doc_type, ticker_symbol, company_name, filed_at, source_url, page_count
              FROM nidp.documents
             WHERE parse_status = 'parsed' AND ticker_symbol = $1
               AND ($2::text IS NULL OR doc_type = $2)
             ORDER BY filed_at DESC NULLS LAST
             LIMIT 1
            """,
            sym, doc_type,
        )
        if doc is None:
            return {"data": None, "error": "no_parsed_filing"}
        chunks = await conn.fetch(
            """
            SELECT chunk_index, text, page_start, page_end
              FROM nidp.document_chunks
             WHERE doc_id = $1
             ORDER BY chunk_index
             LIMIT $2
            """,
            doc["doc_id"], page["limit"],
        )
    return {"data": {
        **row_to_dict(doc),
        "chunks": [row_to_dict(c) for c in chunks],
        "full_text": "\n\n".join((c["text"] or "") for c in chunks),
    }}


@router.get("/coverage", summary="Corpus coverage — chunk/doc counts by doc_type (diagnostic)")
async def documents_coverage() -> Dict[str, Any]:
    """Quick diagnostic so the answer layer (and ops) can see whether the
    concall/presentation corpus is actually populated + parsed."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT d.doc_type,
                   count(DISTINCT d.doc_id)                             AS docs,
                   count(DISTINCT d.doc_id) FILTER (WHERE d.parse_status='parsed') AS docs_parsed,
                   count(c.chunk_id)                                    AS chunks,
                   count(c.chunk_id) FILTER (WHERE c.embedding IS NOT NULL) AS chunks_embedded,
                   max(d.filed_at)                                      AS latest_filed
              FROM nidp.documents d
              LEFT JOIN nidp.document_chunks c USING (doc_id)
             GROUP BY d.doc_type
             ORDER BY chunks DESC
            """,
        )
    return {"data": [row_to_dict(r) for r in rows]}


@router.get("/by-symbol", summary="All source documents for one company, newest first")
async def documents_by_symbol(
    symbol: str = Query(..., min_length=1, max_length=32,
                        description="NSE ticker, e.g. INFY"),
    doc_type: Optional[str] = Query(None, description="filter to one doc_type"),
    limit: int = Query(200, ge=1, le=500),
) -> Dict[str, Any]:
    """The company's filing library — what the Filings Intelligence screen offers
    for download (transcripts, investor presentations, annual reports, quarterly
    results and any other attachment).

    Returns the SOURCE URL as filed with the exchange; we never re-host the PDF.
    Rows with no `source_url` are omitted because a download entry the user
    cannot open is worse than an absent one. `parse_status` is surfaced so the UI
    can say whether Nivesh has actually read a document or is only linking it.
    """
    sym = symbol.strip().upper()
    dt = doc_type.strip() if doc_type and doc_type.strip() else None
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT doc_id, doc_type, company_name, ticker_symbol,
                   filed_at, source_url, page_count, parse_status,
                   raw_size_bytes, announcement_id, announcement_source
              FROM nidp.documents
             WHERE UPPER(ticker_symbol) = $1
               AND source_url IS NOT NULL
               AND ($2::text IS NULL OR doc_type = $2)
             ORDER BY filed_at DESC NULLS LAST
             LIMIT $3
            """,
            sym, dt, limit,
        )
        counts = await conn.fetch(
            """
            SELECT doc_type, count(*) AS n
              FROM nidp.documents
             WHERE UPPER(ticker_symbol) = $1 AND source_url IS NOT NULL
             GROUP BY doc_type
             ORDER BY n DESC
            """,
            sym,
        )
    return {
        "symbol": sym,
        "data": [row_to_dict(r) for r in rows],
        "count": len(rows),
        "by_type": {r["doc_type"]: r["n"] for r in counts},
    }
