"""Full-text search over ingested document CHUNKS — concall transcripts, investor
presentations, annual reports. Returns the matching passage plus its page span and
source PDF, so an answer layer can quote what management said with a page-level
citation. Complements /announcements (filing metadata) with document *content*.

No FTS index exists yet (see migration 031); this uses on-the-fly
`to_tsvector('simple', text)`. Cheap when a symbol filter narrows to one company's
docs; a GIN index is the follow-up for heavy thematic (no-symbol) scans.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query

from nidp.shared.storage.pg import get_pool
from nidp.services.daas_api.auth import require_api_key
from nidp.services.daas_api.responses import envelope, normalise_symbol, page_params, row_to_dict


router = APIRouter(prefix="/documents", tags=["documents"],
                   dependencies=[Depends(require_api_key)])

# doc_parser tags ALL auto-ingested PDFs as 'announcement_attachment' — and in
# India, earnings-call transcripts + investor presentations are FILED as
# announcements, so their chunks live under that doc_type too. Therefore the
# default search spans ALL doc_types (announcement_attachment / concall_transcript
# / investor_presentation / annual_report); pass ?doc_type= to narrow.
@router.get("/search", summary="Full-text search over document chunks (all doc types)")
async def documents_search(
    q: str = Query(..., min_length=2, max_length=256, description="free-text query"),
    symbol: Optional[str] = Query(None, description="restrict to one ticker"),
    doc_type: Optional[str] = Query(None, description="announcement_attachment | concall_transcript | investor_presentation | annual_report"),
    page: Dict[str, int] = Depends(page_params),
) -> Dict[str, Any]:
    sym = normalise_symbol(symbol) if symbol else None
    doc_types: Optional[List[str]] = [doc_type] if doc_type else None  # None → all types
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT c.chunk_id, c.doc_id, c.chunk_index, c.text,
                   c.page_start, c.page_end,
                   d.doc_type, d.ticker_symbol, d.company_name,
                   d.filed_at, d.source_url,
                   ts_rank(to_tsvector('simple', c.text),
                           plainto_tsquery('simple', $1)) AS rank
              FROM nidp.document_chunks c
              JOIN nidp.documents d USING (doc_id)
             WHERE d.parse_status = 'parsed'
               AND ($2::text[] IS NULL OR d.doc_type = ANY($2::text[]))
               AND ($3::text IS NULL OR d.ticker_symbol = $3)
               AND to_tsvector('simple', c.text) @@ plainto_tsquery('simple', $1)
             ORDER BY rank DESC, d.filed_at DESC NULLS LAST
             LIMIT $4 OFFSET $5
            """,
            q, doc_types, sym, page["limit"], page["offset"],
        )
    return envelope([row_to_dict(r) for r in rows], **page,
                    extra={"query": q, "doc_types": doc_types or "all"})


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
