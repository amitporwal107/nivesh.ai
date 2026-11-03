"""OCR for the pages of a filing PDF that have no text layer.

Why: many results filings are a typed cover letter followed by scanned result pages (Bajaj Auto,
27 Oct 2026: 1,446 characters of cover letter, 19 image pages). The whole-document check passed
("OK"), so the analysis saw only the cover letter. Here every page with almost no text is
rasterised (poppler `pdftoppm`) and read by `tesseract`.

Settings measured on that filing: 300 dpi greyscale with page segmentation mode 4 (one column of
variable-size text, which suits results tables) read the revenue, profit before tax, tax and
profit rows correctly; mode 6 garbled the same rows. About 5 s per page.

Without the binaries, `available()` is False and the text is the text layer alone, as before, so
the pipeline never breaks. OCR'd pages are marked in the text, so the model knows their figures
can carry recognition errors.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from typing import Callable, Optional

LOW_TEXT_CHARS = 200           # a page with less text than this is treated as an image page
OCR_DPI = "300"
OCR_PSM = "4"
OCR_TAG = f"tesseract psm{OCR_PSM} {OCR_DPI}dpi"
STEP_TIMEOUT_S = 120


def available() -> bool:
    return bool(shutil.which("pdftoppm") and shutil.which("tesseract"))


def low_text_pages(pages: list[str], min_chars: int = LOW_TEXT_CHARS) -> list[int]:
    """1-based numbers of the pages whose text layer is below `min_chars`."""
    return [i + 1 for i, p in enumerate(pages) if len((p or "").strip()) < min_chars]


def marker(page_no: int) -> str:
    return f"[page {page_no}: read by OCR from a scanned image; figures may contain recognition errors]"


def read_page(pdf_path: str, page_no: int, workdir: str) -> str:
    """OCR one page. A failed step returns "" (the page stays empty) rather than raising."""
    stem = os.path.join(workdir, f"p{page_no}")
    try:
        subprocess.run(["pdftoppm", "-png", "-gray", "-r", OCR_DPI, "-f", str(page_no), "-l", str(page_no),
                        "-singlefile", pdf_path, stem], check=True, capture_output=True, timeout=STEP_TIMEOUT_S)
        out = subprocess.run(["tesseract", stem + ".png", "-", "--psm", OCR_PSM, "-c", "preserve_interword_spaces=1"],
                             check=True, capture_output=True, text=True, timeout=STEP_TIMEOUT_S)
        return out.stdout
    except (subprocess.SubprocessError, OSError):
        return ""
    finally:
        if os.path.exists(stem + ".png"):
            os.remove(stem + ".png")


def fill(body: bytes, pages: list[str], enabled: Optional[bool] = None,
         reader: Optional[Callable[[str, int, str], str]] = None) -> tuple[str, dict]:
    """The document text with its image pages OCR'd: (text, info).

    info = {"pages": n, "low_text_pages": [1-based], "ocr_pages": [pages OCR gave text for],
            "ocr": OCR_TAG when OCR ran, else None}.
    `pages` is the text layer of the pages to read (already capped by the caller)."""
    reader = reader or read_page
    low = low_text_pages(pages)
    run = available() if enabled is None else enabled
    info = {"pages": len(pages), "low_text_pages": low, "ocr_pages": [], "ocr": OCR_TAG if (run and low) else None}
    texts = list(pages)
    if run and low:
        with tempfile.TemporaryDirectory() as td:
            pdf_path = os.path.join(td, "doc.pdf")
            with open(pdf_path, "wb") as fh:
                fh.write(body)
            for n in low:
                got = (reader(pdf_path, n, td) or "").strip()
                if len(got) >= LOW_TEXT_CHARS // 4:
                    texts[n - 1] = f"{marker(n)}\n{got}"
                    info["ocr_pages"].append(n)
    return "\n".join(t or "" for t in texts), info


def needs_ocr(rec: dict, ocr_on: bool, since: Optional[str], doc_subject) -> bool:
    """Should a filing already collected be collected again, now that OCR can run?

    New records say which pages had no text: collect again when some did and OCR did not run.
    Records from before OCR do not, so they are only collected again inside an explicit
    `--reocr-since` window: those with no text at all, or with a short text on a subject that
    carries figures (results, presentations, press releases, call transcripts)."""
    if not ocr_on:
        return False
    if "low_text_pages" in rec:
        return bool(rec["low_text_pages"]) and not rec.get("ocr")
    if not since or str(rec.get("when") or "")[:10] < since:
        return False
    if rec.get("text_status") == "NO_TEXT":
        return True
    return rec.get("text_status") == "OK" and len(rec.get("text") or "") < 4000 and bool(doc_subject(rec))
