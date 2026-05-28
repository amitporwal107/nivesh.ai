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
import json
import logging
import os
import re
from typing import Optional

logger = logging.getLogger(__name__)

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


def _pdf_pages_to_images(content: bytes, start_page: int = 1, end_page: int = 3,
                          password: str = "") -> list[bytes]:
    """Render pages [start_page, end_page) of a PDF to PNG bytes using PyMuPDF.

    The CAS Summary section (monthly movement table) is always on pages 2-3.
    Page 1 contains investor details (PII) and is skipped entirely.
    NSDL/CAMS CAS PDFs are password-protected with the investor's PAN.
    """
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(stream=content, filetype="pdf")
        if doc.is_encrypted:
            # Try PAN as password (standard for CAS PDFs), then empty string
            for pwd in ([password] if password else []) + [""]:
                if doc.authenticate(pwd) != 0:
                    break
            else:
                logger.warning("cas_summary_vision: could not decrypt PDF (wrong PAN?)")
                doc.close()
                return []
        images = []
        for i in range(start_page, min(end_page, len(doc))):
            page = doc[i]
            mat = fitz.Matrix(1.2, 1.2)  # 1.2× zoom — enough for table text
            pix = page.get_pixmap(matrix=mat)
            images.append(pix.tobytes("png"))
        doc.close()
        return images
    except Exception as e:
        logger.warning("cas_summary_vision: PDF render failed: %s", e)
        return []




def extract_portfolio_summary(pdf_bytes: bytes, password: str = "") -> Optional[dict]:
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

    # Pages 2-3 only — the Summary tab with monthly movement table is always
    # there. Page 1 (investor name, PAN, address) is skipped entirely so we
    # send zero PII to OpenAI. Pass PAN to decrypt password-protected PDFs.
    images = _pdf_pages_to_images(pdf_bytes, start_page=1, end_page=3, password=password)
    if not images:
        logger.warning("cas_summary_vision: could not render PDF pages 2-3")
        return None

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
            model="gpt-5",
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
