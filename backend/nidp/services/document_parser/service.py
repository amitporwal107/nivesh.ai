"""Document parser orchestration.

Two-phase loop:
  1. discover_pending()  — register new announcement attachments as
                           documents (status='pending').
  2. parse_pending()     — for each pending doc, download PDF → extract
                           text → chunk → write back.

Crash-safe: the documents table itself is the work queue. parse_status
transitions monotonically (pending → parsed | failed | skipped_non_text).
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from typing import Any

import aiohttp

from .chunker import chunk_text
from .db import discover_pending, fetch_pending_docs, store_parse_result
from .pdf_extractor import extract_text_from_pdf

logger = logging.getLogger(__name__)

_HTTP_TIMEOUT = aiohttp.ClientTimeout(total=60)
_USER_AGENT = "nidp-document-parser/1.0 (+ops@nivesh.example)"

# Cap PDF size so a single corrupt 100MB filing can't OOM the worker.
_MAX_PDF_BYTES = 32 * 1024 * 1024


async def _download(url: str) -> tuple[bytes, str]:
    async with aiohttp.ClientSession(
        timeout=_HTTP_TIMEOUT, headers={"User-Agent": _USER_AGENT},
    ) as sess:
        async with sess.get(url) as resp:
            resp.raise_for_status()
            body = await resp.read()
    if len(body) > _MAX_PDF_BYTES:
        raise ValueError(f"PDF too large: {len(body)} bytes (cap {_MAX_PDF_BYTES})")
    return body, hashlib.sha256(body).hexdigest()


async def _parse_one(doc: dict[str, Any]) -> None:
    doc_id = doc["doc_id"]
    url = doc["source_url"]
    try:
        body, sha = await _download(url)
    except Exception as e:  # noqa: BLE001
        logger.warning("download failed doc=%s url=%s err=%s", doc_id, url, e)
        await store_parse_result(
            doc_id, parse_status="failed", parse_error=f"download: {e}",
            raw_sha256=None, raw_size_bytes=None, text_size_chars=None,
            page_count=None, chunks=None,
        )
        return

    try:
        # pypdf is sync — punt to a thread to keep the event loop free.
        extracted = await asyncio.to_thread(extract_text_from_pdf, body)
    except ValueError as e:
        await store_parse_result(
            doc_id, parse_status="failed", parse_error=f"format: {e}",
            raw_sha256=sha, raw_size_bytes=len(body), text_size_chars=None,
            page_count=None, chunks=None,
        )
        return
    except RuntimeError as e:
        # No extractable text. If OCR is installed it was already tried (see
        # pdf_extractor), so this is genuinely unreadable → terminal 'failed'
        # (prevents an infinite retry loop once skipped docs are re-queued).
        # If OCR is NOT installed, keep 'skipped_non_text' so it retries when it is.
        from .pdf_extractor import ocr_available
        status = "failed" if ocr_available() else "skipped_non_text"
        await store_parse_result(
            doc_id, parse_status=status, parse_error=str(e),
            raw_sha256=sha, raw_size_bytes=len(body), text_size_chars=None,
            page_count=None, chunks=None,
        )
        return
    except Exception as e:  # noqa: BLE001
        logger.exception("unexpected parse error doc=%s", doc_id)
        await store_parse_result(
            doc_id, parse_status="failed", parse_error=f"parse: {type(e).__name__}: {e}",
            raw_sha256=sha, raw_size_bytes=len(body), text_size_chars=None,
            page_count=None, chunks=None,
        )
        return

    chunks = chunk_text(extracted.full_text, extracted.pages)
    chunk_rows = [
        {
            "chunk_index": c.index,
            "text": c.text,
            "char_start": c.char_start,
            "char_end": c.char_end,
            "page_start": c.page_start,
            "page_end": c.page_end,
            "token_count": c.token_count,
        }
        for c in chunks
    ]
    await store_parse_result(
        doc_id, parse_status="parsed", parse_error=None,
        raw_sha256=sha, raw_size_bytes=len(body),
        text_size_chars=len(extracted.full_text),
        page_count=extracted.page_count, chunks=chunk_rows,
    )
    logger.info("parsed doc=%s pages=%d chars=%d chunks=%d",
                doc_id, extracted.page_count, len(extracted.full_text), len(chunks))


async def run_once(discover_limit: int = 500, parse_limit: int = 50,
                   concurrency: int = 4) -> dict:
    run_id = uuid.uuid4()
    logger.info("doc parser run=%s discover_limit=%d parse_limit=%d concurrency=%d",
                run_id, discover_limit, parse_limit, concurrency)

    discovered = await discover_pending(discover_limit, source_run_id=run_id)
    pending = await fetch_pending_docs(parse_limit)
    if not pending:
        logger.info("no pending documents")
        return {"discovered": discovered, "parsed": 0, "failed": 0, "skipped_non_text": 0}

    sem = asyncio.Semaphore(concurrency)

    async def _bounded(d: dict) -> None:
        async with sem:
            await _parse_one(d)

    await asyncio.gather(*[_bounded(d) for d in pending])

    # Summary derived from a follow-up SELECT — cheap and authoritative.
    from nidp.shared.storage.pg import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        summary = await conn.fetchrow(
            """
            SELECT
              COUNT(*) FILTER (WHERE parse_status = 'parsed')              AS parsed,
              COUNT(*) FILTER (WHERE parse_status = 'failed')              AS failed,
              COUNT(*) FILTER (WHERE parse_status = 'skipped_non_text')    AS skipped
              FROM nidp.documents
             WHERE doc_id = ANY($1::uuid[])
            """,
            [d["doc_id"] for d in pending],
        )
    return {
        "discovered": discovered,
        "parsed": summary["parsed"],
        "failed": summary["failed"],
        "skipped_non_text": summary["skipped"],
    }
