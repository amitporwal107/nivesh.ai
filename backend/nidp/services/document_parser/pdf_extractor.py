"""Extract text from PDF bytes using pypdf.

Most NSE/BSE filings are text-PDFs (extractable layer present). Scanned
PDFs land as parse_status='skipped_non_text' — OCR is a follow-up sprint.
"""
from __future__ import annotations

import io
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ExtractedDoc:
    full_text: str
    pages: list[str]                      # page-indexed text (1-based meaning index 0 = page 1)
    page_count: int


def extract_text_from_pdf(body: bytes) -> ExtractedDoc:
    """Return ExtractedDoc with full_text + per-page text.

    Raises:
        ValueError: PDF is not a valid PDF (header check).
        RuntimeError: PDF parses but yields no text (likely a scan; caller
            should mark parse_status='skipped_non_text').
    """
    if not body[:4] == b"%PDF":
        raise ValueError(f"not a PDF (first 4 bytes: {body[:4]!r})")

    try:
        from pypdf import PdfReader            # local import — heavy dep
    except ImportError as e:
        raise RuntimeError(f"pypdf not installed: {e}") from e

    reader = PdfReader(io.BytesIO(body))
    pages: list[str] = []
    for i, page in enumerate(reader.pages):
        try:
            text = page.extract_text() or ""
        except Exception as e:  # noqa: BLE001 — pypdf throws on malformed pages
            logger.warning("page %d extraction failed: %s", i + 1, e)
            text = ""
        pages.append(text)

    full = "\n\n".join(p for p in pages if p.strip())
    if not full.strip():
        raise RuntimeError("zero extractable text — likely scanned/image PDF")
    return ExtractedDoc(full_text=full, pages=pages, page_count=len(pages))
