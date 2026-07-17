"""OpenAI-vision fallback for image-heavy PDF pages.

pypdf extracts a text layer; tesseract OCR handles fully-scanned docs. Neither
handles the common middle case — investor-presentation slides that are mostly
images/charts with little or no extractable text. For those low-text pages we
rasterize the single page (poppler `pdftoppm`, already used for OCR) and ask
OpenAI vision (gpt-4o-mini by default) to transcribe it verbatim. Mirrors the OpenAI
vision path in services/cas_summary_vision.py.

Graceful by contract: if openai isn't installed, OPENAI_API_KEY is unset, or
pdftoppm is missing, `vision_available()` is False and callers skip the vision
path — the pipeline never breaks.

Deploy note: OPENAI_API_KEY is already required on the VM (embedder + classifier
use it), and `openai` is in nidp/deploy/requirements.txt — so vision needs no
extra key. Model defaults to gpt-4o-mini (cost); set NIDP_VISION_MODEL=gpt-4o to
cost on a large corpus (this is a high-volume, transcription-only task).
"""
from __future__ import annotations

import base64
import glob
import logging
import os
import shutil
from nidp.shared.openai_key import get_openai_api_key, openai_configured
import subprocess
import tempfile

logger = logging.getLogger(__name__)

# Cheap by DEFAULT, expensive by choice. This tier fires per low-text page with
# no corpus-level budget cap: at VISION_MAX_PAGES=20 a single deck can cost ~20
# calls, and the corpus is ~16.5k documents. gpt-4o-mini is ~10x cheaper, and the
# job here is transcribing chart-heavy slides — not the reasoning task that would
# justify gpt-4o. Measured context: pypdf already recovers ~99% of material
# figures on content pages, so vision is a thin top-up, not the main source.
# Until 2026-07 this defaulted to gpt-4o and prod was protected only by the API
# key being invalid; a key rotated into GSM would have silently started billing
# gpt-4o on every low-text page. Set NIDP_VISION_MODEL=gpt-4o to opt back in.
VISION_MODEL = os.environ.get("NIDP_VISION_MODEL", "gpt-4o-mini")
VISION_DPI = os.environ.get("NIDP_VISION_DPI", "150")
# Per-page vision calls cost money; cap how many pages of one doc we escalate.
VISION_MAX_PAGES = int(os.environ.get("NIDP_VISION_MAX_PAGES", "20"))

_VISION_PROMPT = (
    "Transcribe this document page verbatim. Output ONLY the text visible on the "
    "page — headings, body text, table cells, bullet points, labels, and numbers "
    "in natural reading order. Do not summarize, describe images, or add any "
    "commentary. If the page contains no readable text, output nothing."
)


def vision_available() -> bool:
    """True when the vision fallback can run: pdftoppm + openai SDK + API key."""
    if not shutil.which("pdftoppm"):
        return False
    if not openai_configured():
        return False
    try:
        import openai  # noqa: F401
    except ImportError:
        return False
    return True


def _rasterize_page(pdf_path: str, page_no: int, out_dir: str) -> bytes | None:
    """Render one 1-based PDF page to PNG bytes via pdftoppm. None on failure."""
    prefix = os.path.join(out_dir, "vpg")
    try:
        subprocess.run(
            ["pdftoppm", "-png", "-r", str(VISION_DPI),
             "-f", str(page_no), "-l", str(page_no), pdf_path, prefix],
            check=True, timeout=120, capture_output=True,
        )
    except Exception as e:  # noqa: BLE001 — rasterize failure → skip this page
        logger.warning("vision: pdftoppm failed for page %d: %s", page_no, e)
        return None
    pngs = glob.glob(prefix + "*.png")
    if not pngs:
        return None
    try:
        with open(pngs[0], "rb") as fh:
            return fh.read()
    except OSError:
        return None


def _transcribe_sync(png_bytes: bytes) -> str:
    """Single OpenAI-vision call transcribing one page image. '' on failure."""
    try:
        from openai import OpenAI
        client = OpenAI(api_key=get_openai_api_key())
        b64 = base64.b64encode(png_bytes).decode()
        resp = client.chat.completions.create(
            model=VISION_MODEL,
            max_tokens=4096,
            temperature=0,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url",
                     "image_url": {"url": f"data:image/png;base64,{b64}", "detail": "high"}},
                    {"type": "text", "text": _VISION_PROMPT},
                ],
            }],
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as e:  # noqa: BLE001 — one page's failure must not kill the doc
        logger.warning("vision: OpenAI transcription failed: %s", e)
        return ""


def extract_pages(body: bytes, page_numbers: list[int]) -> dict[int, str]:
    """Transcribe the given 1-based pages with OpenAI vision.

    Returns {page_no: text} for pages that yielded text. Bounded by
    VISION_MAX_PAGES; never raises (returns {} if the fallback is unavailable).
    """
    if not page_numbers or not vision_available():
        return {}
    capped = page_numbers[:VISION_MAX_PAGES]
    if len(page_numbers) > VISION_MAX_PAGES:
        logger.info("vision: capping %d low-text pages to %d",
                    len(page_numbers), VISION_MAX_PAGES)

    out: dict[int, str] = {}
    with tempfile.TemporaryDirectory() as td:
        pdf_path = os.path.join(td, "doc.pdf")
        try:
            with open(pdf_path, "wb") as fh:
                fh.write(body)
        except OSError:
            return {}
        for page_no in capped:
            with tempfile.TemporaryDirectory() as pd:
                png = _rasterize_page(pdf_path, page_no, pd)
            if not png:
                continue
            text = _transcribe_sync(png)
            if text:
                out[page_no] = text
    if out:
        logger.info("vision: transcribed %d/%d low-text pages (model=%s)",
                    len(out), len(capped), VISION_MODEL)
    return out
