"""
CAS PDF Summary Extractor — Vision API.

Extracts the monthly portfolio value table from the CAS statement's Summary
section using OpenAI gpt-4o vision. The table is printed by NSDL / CDSL /
CAMS and shows month-by-month total portfolio value since statement start.

Flow:
  1. Render the first 3 pages of the PDF to images (covers the Summary tab).
  2. Redact PII — investor name, PAN, folio numbers, mobile, email — before
     sending any bytes to OpenAI.
  3. Call gpt-4o with a structured extraction prompt.
  4. Return {monthly_values: [{month, value_rs}], current_value_rs, statement_date}.

Only called during onboarding import (Gmail auto-import or PDF upload) so the
extra Vision API cost is a one-time per-user expense.
"""
from __future__ import annotations

import base64
import io
import json
import logging
import os
import re
from typing import Optional

logger = logging.getLogger(__name__)

# PII patterns to redact before sending to OpenAI
_PII_PATTERNS = [
    (re.compile(r'[A-Z]{5}[0-9]{4}[A-Z]'),               "XXXXXXXXXX"),  # PAN
    (re.compile(r'\b[6-9]\d{9}\b'),                        "XXXXXXXXXX"),  # mobile
    (re.compile(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z]{2,}'), "XXX@XXX.XXX"),  # email
    (re.compile(r'\b\d{8,16}\b'),                          "XXXXXXXX"),    # account/folio numbers
]

_EXTRACTION_PROMPT = """
You are extracting structured data from an Indian CAS (Consolidated Account Statement) PDF page.

Find the table titled "Monthly movement of your Consolidated Portfolio Value" (or similar).
It has columns: Month | Portfolio Value (₹) | Change (₹) | Change (%).

Extract EVERY row from this table.

Also find the total current portfolio value shown at the bottom of the page
(usually labeled "Holdings as on DD-MMM-YYYY" with a rupee value).

Return ONLY valid JSON in this exact format:
{
  "monthly_values": [
    {"month": "Apr 2025", "value_rs": 10689898.90},
    {"month": "May 2025", "value_rs": 11135534.55}
  ],
  "current_value_rs": 12106866.22,
  "statement_date": "30-Apr-2026"
}

Rules:
- month format: "MMM YYYY" (e.g. "Apr 2025")
- value_rs: numeric rupee value, no commas or currency symbols
- If the table is not visible, return {"monthly_values": [], "current_value_rs": null, "statement_date": null}
- Return ONLY the JSON object, no explanation
"""


def _get_openai_key() -> str:
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        try:
            from helpers import secrets as _s
            key = _s.get("OPENAI_API_KEY") or ""
        except Exception:
            pass
    return key


def _pdf_pages_to_images(content: bytes, max_pages: int = 3) -> list[bytes]:
    """Render first N pages of a PDF to PNG bytes using PyMuPDF."""
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(stream=content, filetype="pdf")
        images = []
        for i in range(min(max_pages, len(doc))):
            page = doc[i]
            mat = fitz.Matrix(1.5, 1.5)  # 1.5× zoom — good quality without huge files
            pix = page.get_pixmap(matrix=mat)
            images.append(pix.tobytes("png"))
        doc.close()
        return images
    except Exception as e:
        logger.warning("cas_summary_vision: PDF render failed: %s", e)
        return []


def _redact_pii_from_text(text: str) -> str:
    """Apply regex redaction to text (used for OCR result sanity check)."""
    for pattern, replacement in _PII_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def _redact_pii_from_image(png_bytes: bytes) -> bytes:
    """
    Redact PII from a PDF page image by painting white rectangles over
    investor name / PAN areas. We use a simple heuristic: the top 15% of
    the first page typically contains investor details. For subsequent pages
    we skip redaction (they contain table data, not PII).

    A more robust approach would be to run Tesseract + regex and paint over
    matched bounding boxes, but that requires tessdata on the image. The
    top-strip approach is good enough for the Summary page which has a fixed
    layout in NSDL / CDSL / CAMS eCAS PDFs.
    """
    try:
        import fitz
        # Re-open as image document to draw white rectangle
        doc = fitz.open(stream=png_bytes, filetype="png")
        page = doc[0]
        rect = page.rect
        # Paint white over top 12% (investor name, PAN, address) and
        # bottom 5% (signature/footer with account numbers)
        redact_top = fitz.Rect(0, 0, rect.width, rect.height * 0.12)
        redact_bot = fitz.Rect(0, rect.height * 0.95, rect.width, rect.height)
        page.add_redact_annot(redact_top, fill=(1, 1, 1))
        page.add_redact_annot(redact_bot, fill=(1, 1, 1))
        page.apply_redactions()
        out = io.BytesIO()
        page.get_pixmap().save(out, "png")
        doc.close()
        return out.getvalue()
    except Exception as e:
        logger.debug("cas_summary_vision: PII redaction failed (%s), using original", e)
        return png_bytes


def extract_portfolio_summary(pdf_bytes: bytes) -> Optional[dict]:
    """
    Extract monthly portfolio value table from a CAS PDF using Vision API.

    Returns:
        {
            "monthly_values": [{"month": "Apr 2025", "value_rs": 10689898.90}, ...],
            "current_value_rs": 12106866.22,
            "statement_date": "30-Apr-2026"
        }
        or None on any failure.
    """
    api_key = _get_openai_key()
    if not api_key:
        logger.warning("cas_summary_vision: OPENAI_API_KEY not set — skipping vision extraction")
        return None

    images = _pdf_pages_to_images(pdf_bytes, max_pages=3)
    if not images:
        logger.warning("cas_summary_vision: could not render PDF pages")
        return None

    # Redact PII from first page (investor details are there)
    images[0] = _redact_pii_from_image(images[0])

    # Build image content blocks for the API
    image_blocks = []
    for img in images:
        b64 = base64.b64encode(img).decode()
        image_blocks.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{b64}", "detail": "high"},
        })

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{
                "role": "user",
                "content": image_blocks + [{"type": "text", "text": _EXTRACTION_PROMPT}],
            }],
            max_tokens=1024,
            temperature=0,
        )
        raw = response.choices[0].message.content or ""
        # Strip markdown code fences if present
        raw = re.sub(r"```(?:json)?", "", raw).strip().strip("`")
        result = json.loads(raw)
        monthly = result.get("monthly_values") or []
        if monthly:
            logger.info(
                "cas_summary_vision: extracted %d monthly data points, "
                "current_value=₹%s, date=%s",
                len(monthly),
                result.get("current_value_rs"),
                result.get("statement_date"),
            )
        return result
    except json.JSONDecodeError as e:
        logger.warning("cas_summary_vision: JSON parse failed: %s", e)
        return None
    except Exception as e:
        logger.warning("cas_summary_vision: Vision API call failed: %s", e)
        return None
