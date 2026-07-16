"""pgvector cosine retriever for filing-document chunks.

Until the embedder service backfills `nidp.document_chunks.embedding`,
this retriever degrades cleanly to keyword matching on chunk text.
Once embeddings exist for any chunk, the vector branch wins automatically.

Supported subscription_params:
  tickers     list[str]  filter to these tickers (joined to documents)
  doc_types   list[str]  'announcement_attachment'|'annual_report'|'concall_transcript'|'investor_presentation'
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from services.feed_rag.base import Citation, FeedRetriever, RetrieverContext

try:
    from nidp.shared.storage.pg import get_pool      # type: ignore
except ImportError:
    get_pool = None  # type: ignore[assignment]

try:
    from nidp.shared import embeddings as _emb        # type: ignore
except ImportError:
    _emb = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

_RRF_K = 60

# Hybrid: pgvector cosine fused with FTS via Reciprocal Rank Fusion. Used when
# the query embeds AND some chunks are embedded.
_HYBRID_SQL = """
WITH vec AS (
    SELECT c.chunk_id,
           row_number() OVER (ORDER BY c.embedding <=> $1::vector) AS rnk
      FROM nidp.document_chunks c
      JOIN nidp.documents d ON d.doc_id = c.doc_id
     WHERE c.embedding IS NOT NULL
       AND ($3::text[] IS NULL OR d.ticker_symbol = ANY($3::text[]) OR d.scrip_code = ANY($3::text[]))
       AND ($4::text[] IS NULL OR d.doc_type = ANY($4::text[]))
     ORDER BY c.embedding <=> $1::vector
     LIMIT $5
),
fts AS (
    SELECT c.chunk_id,
           row_number() OVER (
               ORDER BY ts_rank_cd(to_tsvector('english', c.text),
                                   plainto_tsquery('english', $2)) DESC
           ) AS rnk
      FROM nidp.document_chunks c
      JOIN nidp.documents d ON d.doc_id = c.doc_id
     WHERE to_tsvector('english', c.text) @@ plainto_tsquery('english', $2)
       AND ($3::text[] IS NULL OR d.ticker_symbol = ANY($3::text[]) OR d.scrip_code = ANY($3::text[]))
       AND ($4::text[] IS NULL OR d.doc_type = ANY($4::text[]))
     ORDER BY rnk
     LIMIT $5
),
fused AS (
    SELECT chunk_id,
           COALESCE(1.0 / ($6 + vec.rnk), 0) + COALESCE(1.0 / ($6 + fts.rnk), 0) AS score
      FROM vec FULL OUTER JOIN fts USING (chunk_id)
)
SELECT c.chunk_id, c.doc_id, c.chunk_index, c.text, c.page_start, c.page_end,
       d.source_url, d.doc_type, d.ticker_symbol, d.company_name, d.filed_at,
       f.score
  FROM fused f
  JOIN nidp.document_chunks c USING (chunk_id)
  JOIN nidp.documents d ON d.doc_id = c.doc_id
 ORDER BY f.score DESC
 LIMIT $5
"""

# Fallback: FTS-only. Used before any embeddings exist, or when the query
# can't be embedded (no OPENAI_API_KEY).
_FALLBACK_TEXT_SQL = """
WITH q AS (SELECT plainto_tsquery('english', $1) AS tsq)
SELECT
    c.chunk_id,
    c.doc_id,
    c.chunk_index,
    c.text,
    c.page_start,
    c.page_end,
    d.source_url,
    d.doc_type,
    d.ticker_symbol,
    d.company_name,
    d.filed_at,
    ts_rank_cd(to_tsvector('english', c.text), q.tsq) AS score
  FROM nidp.document_chunks c
  JOIN nidp.documents d ON d.doc_id = c.doc_id, q
 WHERE to_tsvector('english', c.text) @@ q.tsq
   AND ($2::text[] IS NULL OR d.ticker_symbol = ANY($2::text[]) OR d.scrip_code = ANY($2::text[]))
   AND ($3::text[] IS NULL OR d.doc_type = ANY($3::text[]))
 ORDER BY score DESC
 LIMIT $4
"""


class FilingDocumentsRetriever(FeedRetriever):
    feed_id = "filing_documents"

    async def search(self, ctx: RetrieverContext) -> list[Citation]:
        if get_pool is None:
            return []
        params = ctx.subscription_params or {}
        tickers: Optional[list[str]] = params.get("tickers") or None
        if tickers:
            tickers = [t.upper() for t in tickers]
        doc_types: Optional[list[str]] = params.get("doc_types") or None

        # Embed the query for the vector leg. None → FTS-only fallback (also the
        # right behaviour mid-backfill when only some chunks are embedded).
        qvec = None
        if _emb is not None and _emb.is_configured():
            try:
                qvec = await _emb.embed_query(ctx.query)
            except _emb.EmbeddingError as e:            # pragma: no cover
                logger.warning("filing_documents: query embed failed, FTS fallback: %s", e)

        pool = await get_pool()
        async with pool.acquire() as conn:
            if qvec is not None:
                rows = await conn.fetch(
                    _HYBRID_SQL,
                    _emb.to_pgvector_literal(qvec),      # $1
                    ctx.query,                           # $2
                    tickers,                             # $3
                    doc_types,                           # $4
                    ctx.top_k,                           # $5
                    _RRF_K,                              # $6
                )
            else:
                rows = await conn.fetch(
                    _FALLBACK_TEXT_SQL,
                    ctx.query,
                    tickers,
                    doc_types,
                    ctx.top_k,
                )

        out: list[Citation] = []
        for r in rows:
            page_span = (
                f"p.{r['page_start']}-{r['page_end']}" if r["page_start"] and r["page_end"]
                else (f"p.{r['page_start']}" if r["page_start"] else "")
            )
            ticker = r["ticker_symbol"] or r["company_name"] or "?"
            title = f"[{ticker}] {r['doc_type']}{(' ' + page_span) if page_span else ''}"
            excerpt = (r["text"] or "")[:500]
            out.append(Citation(
                feed_id=self.feed_id,
                title=title,
                excerpt=excerpt,
                score=float(r["score"]),
                as_of=r["filed_at"] or datetime.now(timezone.utc),
                url=r["source_url"],
                metadata={
                    "doc_id": str(r["doc_id"]),
                    "chunk_index": r["chunk_index"],
                    "doc_type": r["doc_type"],
                    "ticker": r["ticker_symbol"],
                    "page_start": r["page_start"],
                    "page_end": r["page_end"],
                },
            ))
        return out
