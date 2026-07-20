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
import re
import uuid
from datetime import date
from typing import Any
from urllib.parse import urlparse, urlunparse

import aiohttp

from nidp.services.corporate_announcements.doctype import classify

from .chunker import chunk_text
from .db import discover_pending, embed_pending, fetch_pending_docs, store_parse_result
from .audio_extractor import (audio_available, find_media_urls,
                              looks_like_audio_disclosure, transcribe_url)
from .pdf_extractor import ExtractedDoc, extract_text_from_pdf
from .vision_extractor import VISION_MAX_PAGES, extract_pages, vision_available

logger = logging.getLogger(__name__)

_HTTP_TIMEOUT = aiohttp.ClientTimeout(total=60)
# BSE/NSE archive hosts (www.bseindia.com/xml-data, nsearchives.nseindia.com)
# 403 any request that looks like a bot — missing a browser User-Agent and a
# same-origin Referer. The old "nidp-document-parser/1.0" UA got 403 on ~2.1k
# filings (verified: parser-UA -> 403, browser-UA+referer -> 200 %PDF). Send a
# browser UA + the host's own referer.
_BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

# Cap PDF size so a single corrupt 100MB filing can't OOM the worker.
_MAX_PDF_BYTES = 32 * 1024 * 1024


def _download_headers(url: str) -> dict[str, str]:
    """Browser-like headers with a same-origin Referer chosen from the URL host —
    BSE/NSE archive hosts reject downloads without them (HTTP 403)."""
    headers = {"User-Agent": _BROWSER_UA, "Accept": "application/pdf,*/*"}
    host = urlparse(url).netloc.lower()
    if "bseindia.com" in host:
        headers["Referer"] = "https://www.bseindia.com/"
        headers["Origin"] = "https://www.bseindia.com"
    elif "nseindia.com" in host:
        headers["Referer"] = "https://www.nseindia.com/"
    return headers


def _bse_archive_url(url: str) -> str | None:
    """BSE's historical-archive twin of an AttachLive URL, or None if N/A.

    BSE serves a filing's attachment from .../corpfiling/AttachLive/<file> only
    while it is recent, then MOVES the object to .../corpfiling/AttachHis/<file>
    — same filename. Once moved, the AttachLive path 404s. That 404 means "not at
    this path", NOT "destroyed": verified 3/3 on ~5-month-old filings that
    AttachLive -> 404 while AttachHis -> 200 with the real PDF. Since only
    AttachLive is ever constructed (parser_bse.py), every BSE attachment older
    than the live window needs this fallback or it is wrongly written off as
    permanently gone.
    """
    parts = urlparse(url)
    if "bseindia.com" not in parts.netloc.lower():
        return None
    if "/AttachLive/" not in parts.path:
        return None
    return urlunparse(parts._replace(path=parts.path.replace("/AttachLive/", "/AttachHis/", 1)))


async def _get(sess: aiohttp.ClientSession, url: str) -> bytes:
    async with sess.get(url, headers=_download_headers(url)) as resp:
        resp.raise_for_status()
        return await resp.read()


async def _download(url: str) -> tuple[bytes, str]:
    async with aiohttp.ClientSession(timeout=_HTTP_TIMEOUT) as sess:
        try:
            body = await _get(sess, url)
        except aiohttp.ClientResponseError as e:
            archive_url = _bse_archive_url(url) if e.status == 404 else None
            if archive_url is None:
                raise
            # Aged out of the live bucket — re-fetch from the historical one.
            logger.info("AttachLive 404, retrying via AttachHis url=%s", archive_url)
            body = await _get(sess, archive_url)
    if len(body) > _MAX_PDF_BYTES:
        raise ValueError(f"PDF too large: {len(body)} bytes (cap {_MAX_PDF_BYTES})")
    return body, hashlib.sha256(body).hexdigest()


# Financial-results statements are frequently SCANNED and carry a GARBLED embedded
# text layer — pypdf reads "incom€/(loi6)" for "income/(loss)" and "1/s1,066.06" for
# "1,51,066.06" — so the numbers land in the corpus unusable and the copilot cannot
# quote Revenue/PAT (verified 2026-07-20 on SSWL). Unlike the low-text vision path in
# pdf_extractor, these pages are NOT low-text: they are FULL of garbled text, so that
# path never fires. Detect the results-table pages by their header cluster and
# re-transcribe them with OpenAI vision (which reads the rendered image, not the bad
# text layer) — vision returned the SSWL table clean, matching the filing's own
# arithmetic, where the pypdf text layer did not.
# A results-statement page co-locates MANY of these line-item concepts; ordinary
# prose hits only a couple. We score rather than match a fixed header string, because
# a scanned filing's OCR mangles individual terms unpredictably ("revenue lrom
# operatrons", "Profit/(loss) Derore tax", garbled dates) — but 5+ of the ten signals
# still survive on a real table, while an auditor's letter or a notes page does not
# reach that. Measured on the SSWL filing: the two table pages scored >=5, the four
# cover/auditor/notes pages scored <=4.
_RESULTS_SIGNAL_RES = [re.compile(p, re.I) for p in (
    r"revenue",
    r"total\s+inco",                       # total income
    r"total\s+expen",                      # total expenses
    r"profit",
    r"\btax\b",
    r"earnings?\s+per|per\s+equity\s+share|\beps\b",
    r"comprehensive",
    r"deprec",                             # depreciation
    r"finance\s+cost|interest",
    r"quarter|standalone|consolidated|3[01][.,/ ]?0[0-9][.,/ ]?20\d\d",
)]
_RESULTS_MIN_SIGNALS = 5


def _results_table_pages(pages: list[str], limit: int) -> list[int]:
    """1-based indices of pages that look like a formal quarterly-results statement.

    Scores each page against the results-line-item signal set (see above) and selects
    pages hitting >= _RESULTS_MIN_SIGNALS. Robust to OCR garble; specific enough that a
    passing mention of "revenue"/"profit" in prose does not qualify.
    """
    out: list[int] = []
    for i, txt in enumerate(pages, start=1):
        t = txt or ""
        score = sum(1 for rx in _RESULTS_SIGNAL_RES if rx.search(t))
        if score >= _RESULTS_MIN_SIGNALS:
            out.append(i)
            if len(out) >= limit:
                break
    return out


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

    # Audio-disclosure recovery. Many issuers file a one-page letter pointing at
    # an mp3 instead of publishing a transcript — the letter parses fine and
    # carries no content, and its "earnings conference call" wording makes the
    # classifier type it concall_transcript (35% of typed transcripts on staging
    # are these). If this is that letter and it names a media URL, transcribe the
    # recording and use THAT as the document's text. Graceful: unavailable
    # transcription just stores the letter, exactly as today.
    audio_transcript = None
    if looks_like_audio_disclosure(extracted.full_text) and audio_available():
        for media_url in find_media_urls(extracted.full_text, body):
            audio_transcript = await asyncio.to_thread(transcribe_url, media_url)
            if audio_transcript:
                logger.info("doc=%s recovered %d chars of transcript from audio %s",
                            doc_id, len(audio_transcript), media_url[:80])
                # The transcript IS the document now: chunk/type/store it as one
                # page, so retrieval cites the call rather than the letterhead.
                extracted = ExtractedDoc(full_text=audio_transcript,
                                         pages=[audio_transcript], page_count=1)
                break

    # Scanned-results recovery. Mirrors the audio-disclosure block above:
    # content-detect the results-table pages, escalate them to vision, replace the
    # garbled page text with the clean transcription, then chunk/type/store the
    # clean text. Never fails the parse — vision unavailable or erroring just leaves
    # the original text (graceful, exactly like today). Bounded to a few pages/doc.
    if audio_transcript is None and vision_available() and extracted.pages:
        table_pages = _results_table_pages(extracted.pages, min(6, VISION_MAX_PAGES))
        if table_pages:
            try:
                vis = await asyncio.to_thread(extract_pages, body, table_pages)
            except Exception as e:  # noqa: BLE001 — vision must never break a parse
                logger.warning("doc=%s vision results-transcription failed: %s", doc_id, e)
                vis = {}
            new_pages = list(extracted.pages)
            replaced = 0
            for pno, vtext in vis.items():
                # Only replace when vision actually returned substantive text, so a
                # blank/refused transcription can't wipe the (garbled but present)
                # original.
                if vtext and len(vtext) >= 40 and 1 <= pno <= len(new_pages):
                    new_pages[pno - 1] = vtext
                    replaced += 1
            if replaced:
                extracted = ExtractedDoc(full_text="\n".join(new_pages),
                                         pages=new_pages,
                                         page_count=extracted.page_count)
                logger.info("doc=%s vision-transcribed %d results-table page(s)",
                            doc_id, replaced)

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

    # Type the document from its OWN content (first two pages — a transcript's
    # page 1 is often a cover letter), overriding the discover-time subcategory
    # guess whenever the content is a confident match. Falls back to the existing
    # doc_type when the content yields no signal (score 0).
    head_text = "\n".join(extracted.pages[:2]) if extracted.pages else extracted.full_text[:6000]
    content_type, dt_score, _ = classify(
        headline=doc.get("subject") or "",
        first_page_text=head_text[:6000],
        subcategory=doc.get("subcategory") or "",
    )
    existing_type = doc.get("doc_type") or "announcement_attachment"
    final_type = content_type if content_type != "announcement_attachment" else existing_type
    if audio_transcript:
        # We transcribed the actual call: this is a transcript by construction,
        # not by classifier guess. Confidence is certainty, not a content score.
        final_type, dt_score = "concall_transcript", 100

    await store_parse_result(
        doc_id, parse_status="parsed", parse_error=None,
        raw_sha256=sha, raw_size_bytes=len(body),
        text_size_chars=len(extracted.full_text),
        page_count=extracted.page_count, chunks=chunk_rows,
        doc_type=final_type, doc_type_confidence=dt_score,
    )
    logger.info("parsed doc=%s pages=%d chars=%d chunks=%d type=%s(%d)",
                doc_id, extracted.page_count, len(extracted.full_text), len(chunks),
                final_type, dt_score)


async def run_once(discover_limit: int = 500, parse_limit: int = 50,
                   concurrency: int = 4, embed_limit: int = 200,
                   shards: int = 1, shard: int = 0,
                   from_date: date | None = None, to_date: date | None = None) -> dict:
    run_id = uuid.uuid4()
    logger.info("doc parser run=%s discover_limit=%d parse_limit=%d concurrency=%d "
                "embed_limit=%d shard=%d/%d window=%s..%s",
                run_id, discover_limit, parse_limit, concurrency, embed_limit, shard, shards,
                from_date or "-", to_date or "-")

    discovered = await discover_pending(discover_limit, source_run_id=run_id)
    pending = await fetch_pending_docs(parse_limit, shards=shards, shard=shard,
                                      from_date=from_date, to_date=to_date)
    if pending:
        sem = asyncio.Semaphore(concurrency)

        async def _bounded(d: dict) -> None:
            async with sem:
                try:
                    await _parse_one(d)
                except Exception:                              # noqa: BLE001
                    # _parse_one records its own download/parse failures, so
                    # reaching here means storing a SUCCESSFUL parse failed —
                    # e.g. extracted text Postgres rejects. Logged, not
                    # swallowed: the document is left for the next run rather
                    # than aborting the batch. An 18k backfill was lost this
                    # way to one filing containing a lone surrogate.
                    logger.exception("doc=%s could not be stored — skipped, batch continues",
                                     d.get("doc_id"))

        await asyncio.gather(*[_bounded(d) for d in pending])
    else:
        logger.info("no pending documents")

    # Summary derived from a follow-up SELECT — cheap and authoritative.
    parsed = failed = skipped = 0
    if pending:
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
        parsed, failed, skipped = summary["parsed"], summary["failed"], summary["skipped"]

    # Embedding pass — always runs (backfills any NULL-embedding chunk, not just
    # the ones parsed this invocation) so the semantic index stays populated.
    embed_summary = await embed_pending(embed_limit)

    return {
        "discovered": discovered,
        "parsed": parsed,
        "failed": failed,
        "skipped_non_text": skipped,
        "embedded": embed_summary["embedded"],
    }
