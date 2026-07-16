"""Extract text from PDF bytes using pypdf, with an OCR fallback.

Most NSE/BSE filings are text-PDFs (extractable layer present) → pypdf. Scanned /
image-rendered PDFs (many investor presentations, some transcripts/annual reports)
have no text layer; for those we rasterize (pdftoppm) + OCR (tesseract). If the OCR
binaries aren't installed, we degrade to the old behaviour (raise → caller marks
parse_status='skipped_non_text'), so this never breaks the pipeline.
"""
from __future__ import annotations

import io
import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# OCR is slow (~1-3s/page); cap pages so the */15 parser cron doesn't stall.
_OCR_MAX_PAGES = int(os.environ.get("NIDP_OCR_MAX_PAGES", "60"))
_OCR_DPI = os.environ.get("NIDP_OCR_DPI", "200")

# A page with fewer than this many extracted characters is treated as
# image-heavy and eligible for the Claude-vision fallback (see vision_extractor).
_VISION_MIN_CHARS = int(os.environ.get("NIDP_VISION_MIN_CHARS", "200"))


def _low_text_pages(pages: list[str], min_chars: int = _VISION_MIN_CHARS) -> list[int]:
    """0-based indices of pages whose extracted text is below `min_chars`
    (image-heavy slides). Pure helper — unit-testable without any PDF."""
    return [i for i, p in enumerate(pages) if len((p or "").strip()) < min_chars]


def ocr_available() -> bool:
    """True when the OCR tooling (poppler pdftoppm + tesseract) is installed.
    The nidp-staging deploy workflow apt-installs these; ops can check this to
    confirm image/scanned filing PDFs will be OCR'd rather than skipped."""
    import shutil
    return bool(shutil.which("pdftoppm") and shutil.which("tesseract"))


def _ocr_pdf(body: bytes, max_pages: int = _OCR_MAX_PAGES) -> list[str] | None:
    """Rasterize + OCR a scanned/image PDF → per-page text. Returns None when the
    OCR tooling (poppler `pdftoppm` + `tesseract`) is unavailable (graceful skip)."""
    import shutil
    import subprocess
    import tempfile

    if not (shutil.which("pdftoppm") and shutil.which("tesseract")):
        logger.info("OCR skipped — pdftoppm/tesseract not installed")
        return None
    pages: list[str] = []
    with tempfile.TemporaryDirectory() as td:
        pdf_path = os.path.join(td, "doc.pdf")
        with open(pdf_path, "wb") as fh:
            fh.write(body)
        try:
            subprocess.run(
                ["pdftoppm", "-png", "-r", _OCR_DPI, "-l", str(max_pages),
                 pdf_path, os.path.join(td, "pg")],
                check=True, timeout=600, capture_output=True,
            )
        except Exception as e:  # noqa: BLE001 — rasterize failure → give up on OCR
            logger.warning("OCR rasterize (pdftoppm) failed: %s", e)
            return None
        for img in sorted(f for f in os.listdir(td) if f.endswith(".png")):
            try:
                out = subprocess.run(
                    ["tesseract", os.path.join(td, img), "stdout", "-l", "eng"],
                    check=True, timeout=120, capture_output=True, text=True,
                )
                pages.append(out.stdout or "")
            except Exception as e:  # noqa: BLE001 — one bad page shouldn't kill the doc
                logger.warning("OCR (tesseract) failed on %s: %s", img, e)
                pages.append("")
    return pages


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

    # Per-page Claude-vision fallback: investor decks and mixed PDFs often have
    # slides that are image/chart-only with little or no text layer. Escalate
    # just those low-text pages to vision (bounded + graceful; no-op when the
    # fallback is unavailable). Fully-scanned docs (no page has text) still fall
    # to the cheaper whole-doc OCR path below.
    low = _low_text_pages(pages)
    if low:
        from .vision_extractor import vision_available, extract_pages as _vision_pages
        if vision_available():
            vis = _vision_pages(body, [i + 1 for i in low])   # vision uses 1-based page numbers
            for i in low:
                vtext = vis.get(i + 1, "")
                if len(vtext) > len((pages[i] or "").strip()):
                    pages[i] = vtext

    full = "\n\n".join(p for p in pages if p.strip())
    if not full.strip():
        # No text layer → scanned/image PDF. Try OCR before giving up.
        ocr_pages = _ocr_pdf(body)
        if ocr_pages and any(p.strip() for p in ocr_pages):
            n = sum(1 for p in ocr_pages if p.strip())
            logger.info("OCR fallback extracted text from %d/%d pages", n, len(ocr_pages))
            ocr_full = "\n\n".join(p for p in ocr_pages if p.strip())
            return ExtractedDoc(full_text=ocr_full, pages=ocr_pages, page_count=len(ocr_pages))
        raise RuntimeError("zero extractable text — scanned/image PDF and OCR unavailable/empty")
    return ExtractedDoc(full_text=full, pages=pages, page_count=len(pages))
