"""Section detection + page classification for CAS PDFs.

Walks a PDF once with PyMuPDF, extracts per-page text, then labels each
page with the CAS-statement sections it contains. Downstream the hybrid
parser decides per section whether to (a) use the extracted text directly
or (b) ship the cropped page to Vision.

Vendor-agnostic — NSDL and CDSL both use similar nomenclature, and the
detector keys off semantic anchors (e.g. "Mutual Funds (M)") rather than
fixed coordinates.
"""
from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Section taxonomy ──────────────────────────────────────────────────
SECTION_INVESTOR = "investor"
SECTION_SUMMARY = "summary"
SECTION_EQUITY = "equities"
SECTION_PREF = "preference_shares"
SECTION_SGB = "sovereign_gold_bonds"
SECTION_MF_DEMAT = "mutual_funds_demat"
SECTION_MF_FOLIO = "mutual_fund_folios"
SECTION_DEMAT_TXN = "demat_transactions"
SECTION_MF_TXN = "mutual_fund_transactions"

ALL_SECTIONS = (
    SECTION_INVESTOR, SECTION_SUMMARY,
    SECTION_EQUITY, SECTION_PREF, SECTION_SGB,
    SECTION_MF_DEMAT, SECTION_MF_FOLIO,
    SECTION_DEMAT_TXN, SECTION_MF_TXN,
)


# Anchor regexes — first match per page wins, but a page may be tagged
# with multiple sections. Order matters only for tie-breaking on the
# "primary" section attribution; all matches are still recorded.
_ANCHORS: List[tuple[str, re.Pattern]] = [
    (SECTION_INVESTOR, re.compile(r"\b(investor|holder)\s+(name|details)\b|^\s*name\s*[:\-]", re.I | re.M)),
    (SECTION_SUMMARY,  re.compile(r"portfolio\s+(summary|value)|asset\s+allocation|holding\s+statement", re.I)),
    (SECTION_EQUITY,   re.compile(r"\bequit(?:y|ies)\b\s*(?:\(?\s*e\s*\)?)?|equity\s+holdings|securities\s+held", re.I)),
    (SECTION_PREF,     re.compile(r"preference\s+shares?", re.I)),
    (SECTION_SGB,      re.compile(r"sovereign\s+gold\s+bond|\bsgb\b", re.I)),
    (SECTION_MF_DEMAT, re.compile(r"mutual\s+funds?\s*\(?\s*m\s*\)?|mutual\s+fund\s+units\s+in\s+demat|mf\s+demat", re.I)),
    (SECTION_MF_FOLIO, re.compile(r"folio\s*(no|number|#)|mutual\s+fund\s+folio|scheme\s+name.*nav", re.I)),
    (SECTION_DEMAT_TXN, re.compile(r"transaction\s+statement.*demat|opening\s+balance.*closing\s+balance", re.I)),
    (SECTION_MF_TXN,   re.compile(r"transaction\s+summary|purchase.*redemption|sip\s+purchase|systematic\s+investment", re.I)),
]

# Heuristic: a page is "table-dense" (and therefore a Vision candidate
# even when text was extractable) when it contains many ISIN-looking
# strings or many decimal numbers.
_ISIN_RE = re.compile(r"\bIN[A-Z0-9]{10}\b")
_DECIMAL_RE = re.compile(r"\b\d{1,3}(?:,\d{2,3})*\.\d{2,4}\b")


@dataclass
class PageInfo:
    page_num: int                       # 1-indexed
    text: str
    width: float
    height: float
    sections: List[str] = field(default_factory=list)
    isin_count: int = 0
    decimal_count: int = 0
    is_table_dense: bool = False

    @property
    def text_is_meaningful(self) -> bool:
        """A page whose extracted text contains enough characters and at
        least one ISIN/decimal pair is probably a text-PDF page we can
        parse without Vision."""
        return (
            len(self.text) > 200
            and (self.isin_count > 0 or self.decimal_count > 2)
        )


@dataclass
class CASSection:
    """A logical section spanning one or more pages."""
    name: str
    pages: List[int]                    # 1-indexed page numbers
    text_blob: str                      # joined text for those pages
    needs_vision: bool                  # True when text alone is insufficient


def extract_pages(pdf_bytes: bytes) -> List[PageInfo]:
    """Open the PDF once and return PageInfo per page. Pure CPU; callers
    should run this in a thread executor when invoking from async code."""
    import fitz  # PyMuPDF

    pages: List[PageInfo] = []
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        for i, page in enumerate(doc, start=1):
            txt = page.get_text("text") or ""
            isin_n = len(_ISIN_RE.findall(txt))
            dec_n = len(_DECIMAL_RE.findall(txt))
            info = PageInfo(
                page_num=i,
                text=txt,
                width=page.rect.width,
                height=page.rect.height,
                isin_count=isin_n,
                decimal_count=dec_n,
                is_table_dense=(isin_n >= 3 or dec_n >= 8),
            )
            for name, pattern in _ANCHORS:
                if pattern.search(txt):
                    info.sections.append(name)
            pages.append(info)
    finally:
        doc.close()
    return pages


def render_pages_as_jpeg(
    pdf_bytes: bytes, page_numbers: List[int], *, dpi: int = 180,
) -> Dict[int, bytes]:
    """Render specific 1-indexed pages to JPEG bytes. Used to feed Vision
    with only the pages that actually need it."""
    import fitz

    out: Dict[int, bytes] = {}
    if not page_numbers:
        return out
    wanted = {int(p) for p in page_numbers}
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        zoom = dpi / 72.0
        mat = fitz.Matrix(zoom, zoom)
        for i, page in enumerate(doc, start=1):
            if i not in wanted:
                continue
            pix = page.get_pixmap(matrix=mat, alpha=False)
            buf = io.BytesIO()
            # Use PNG-style high quality JPEG so OCR fine-tables stay sharp
            img_bytes = pix.tobytes("jpeg", jpg_quality=85)
            buf.write(img_bytes)
            out[i] = buf.getvalue()
    finally:
        doc.close()
    return out


def group_sections(pages: List[PageInfo]) -> List[CASSection]:
    """Cluster contiguous pages by the section anchors they contain.

    A page with no anchors inherits the previous page's section (treats
    multi-page tables as a single section). A page with a *new* anchor
    starts a new section.
    """
    sections: List[CASSection] = []
    current: Optional[CASSection] = None

    for p in pages:
        primary = p.sections[0] if p.sections else None
        if primary is None:
            # No anchor on this page — only attach to current if we're
            # already inside a table-bearing section AND this page also
            # looks like a table (continuation). Otherwise treat as filler.
            if current and p.is_table_dense:
                current.pages.append(p.page_num)
                current.text_blob += "\n" + p.text
            continue

        # New anchor — flush current
        if current is None or current.name != primary:
            if current is not None:
                sections.append(current)
            current = CASSection(
                name=primary,
                pages=[p.page_num],
                text_blob=p.text,
                needs_vision=not p.text_is_meaningful,
            )
        else:
            current.pages.append(p.page_num)
            current.text_blob += "\n" + p.text
            if not p.text_is_meaningful:
                current.needs_vision = True

    if current is not None:
        sections.append(current)

    return sections


def vision_target_pages(pages: List[PageInfo], sections: List[CASSection]) -> List[int]:
    """Return the 1-indexed page numbers worth sending to Vision.

    A page is worth shipping when:
      - its primary section is needs_vision=True (text extraction failed), OR
      - the page is table-dense but had zero anchors detected — likely a
        layout the regex anchors missed (e.g. a vendor-specific heading)
    """
    needs: set[int] = set()
    for sec in sections:
        if sec.needs_vision:
            needs.update(sec.pages)
    for p in pages:
        if not p.sections and p.is_table_dense:
            needs.add(p.page_num)
    return sorted(needs)


def coverage_summary(pages: List[PageInfo], sections: List[CASSection]) -> dict:
    """Return a small diagnostic dict for structured logging."""
    return {
        "pages_total": len(pages),
        "pages_text_ok": sum(1 for p in pages if p.text_is_meaningful),
        "pages_table_dense": sum(1 for p in pages if p.is_table_dense),
        "sections_detected": [s.name for s in sections],
        "vision_pages": vision_target_pages(pages, sections),
    }
