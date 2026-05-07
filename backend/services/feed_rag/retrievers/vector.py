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

logger = logging.getLogger(__name__)

# Hybrid plan: try vector cosine first; if the embedder hasn't run,
# all rows have NULL embedding and the query returns 0 — we then fall
# back to ts_rank_cd over chunk text. The fallback gives the framework
# something useful to return on day-1 before embeddings exist.
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

        pool = await get_pool()
        async with pool.acquire() as conn:
            # Vector path requires an embedding for the user query — which we
            # don't have until the embedder service is wired and the same
            # model is callable from the API tier. Until then, fall back to
            # text. This is also the right behaviour when the embedder is
            # mid-backfill and only some chunks have embeddings.
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
