"""Claude-vision fallback for image-heavy PDF pages.

pypdf extracts a text layer; tesseract OCR handles fully-scanned docs. Neither
handles the common middle case — investor-presentation slides that are mostly
images/charts with little or no extractable text. For those low-text pages we
rasterize the single page (poppler `pdftoppm`, already used for OCR) and ask
Claude vision to transcribe it verbatim.

Graceful by contract: if anthropic isn't installed, ANTHROPIC_API_KEY is unset,
or pdftoppm is missing, `vision_available()` is False and callers skip the
vision path — the pipeline never breaks.

Deploy note: the NIDP/document_parser image must ship the `anthropic` package
(added to nidp/deploy/requirements.txt) and ANTHROPIC_API_KEY must be in
/opt/nidp/nidp.env for this to activate on the VM.

Model defaults to claude-opus-4-8; set NIDP_VISION_MODEL=claude-haiku-4-5 to cut
cost on a large corpus (this is a high-volume, transcription-only task).
"""
from __future__ import annotations

import base64
import glob
import logging
import os
import shutil
import subprocess
import tempfile

logger = logging.getLogger(__name__)

VISION_MODEL = os.environ.get("NIDP_VISION_MODEL", "claude-opus-4-8")
VISION_DPI = os.environ.get("NIDP_VISION_DPI", "150")
# Per-page vision calls cost money; cap how many pages of one doc we escalate.
VISION_MAX_PAGES = int(os.environ.get("NIDP_VISION_MAX_PAGES", "20"))

_VISION_PROMPT = (
    "Transcribe this document page verbatim. Output ONLY the text visible on the "
    "page — headings, body text, table cells, bullet points, labels, and numbers "
    "in natural reading order. Do not summarize, describe images, or add any "
    "commentary. If the page contains no readable text, output nothing."
)
_VISION_SYSTEM = (
    "You are a precise document transcriber. You output only the page's text, "
    "with no preamble, explanation, or meta-commentary."
)


def vision_available() -> bool:
    """True when Claude-vision fallback can run: pdftoppm + anthropic SDK + key."""
    if not shutil.which("pdftoppm"):
        return False
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return False
    try:
        import anthropic  # noqa: F401
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
    """Single Claude-vision call transcribing one page image. '' on failure."""
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        msg = client.messages.create(
            model=VISION_MODEL,
            max_tokens=4096,
            system=_VISION_SYSTEM,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {
                        "type": "base64", "media_type": "image/png",
                        "data": base64.b64encode(png_bytes).decode(),
                    }},
                    {"type": "text", "text": _VISION_PROMPT},
                ],
            }],
        )
        return "".join(b.text for b in msg.content if b.type == "text").strip()
    except Exception as e:  # noqa: BLE001 — one page's failure must not kill the doc
        logger.warning("vision: Claude transcription failed: %s", e)
        return ""


def extract_pages(body: bytes, page_numbers: list[int]) -> dict[int, str]:
    """Transcribe the given 1-based pages with Claude vision.

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
