"""CAS statement period detector — extract the {from, to} dates from
the header text of an NSDL/CDSL/CAMS/KFintech CAS PDF.

These statements have header text like:
  "Consolidated Account Statement"
  "For the Period 01-Feb-2026 to 28-Feb-2026"
  "Statement Period: 01-FEB-2026 - 28-FEB-2026"
  "STATEMENT FOR THE PERIOD: APR 2025 - MAR 2026"

The detector tries several regexes against the first ~2 pages of text
and returns ISO dates. Falls back to month-name heuristics if exact
dates aren't present.
"""
from __future__ import annotations

import calendar
import io
import logging
import re
from datetime import date, datetime
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

MONTH_MAP = {m.upper(): i for i, m in enumerate(calendar.month_abbr) if m}
MONTH_MAP.update({m.upper(): i for i, m in enumerate(calendar.month_name) if m})

# DD-MMM-YYYY (eg "01-Feb-2026")
DATE_PATTERNS = [
    re.compile(r"(\d{1,2})[-\s/]([A-Za-z]{3,9})[-\s/](\d{2,4})"),
    re.compile(r"(\d{1,2})[-/](\d{1,2})[-/](\d{2,4})"),
    re.compile(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})"),
]

# Common header phrasings — the most reliable signal
HEADER_PATTERNS = [
    re.compile(r"(?:For the Period|Statement Period|Period\s*:|Account Statement (?:for|from))\s*[:\-]?\s*(.{1,80}?)\s*(?:Page|Folio|$)", re.IGNORECASE | re.DOTALL),
    re.compile(r"(\d{1,2}[-\s/][A-Za-z]{3,9}[-\s/]\d{2,4})\s*(?:to|-|–|—)\s*(\d{1,2}[-\s/][A-Za-z]{3,9}[-\s/]\d{2,4})", re.IGNORECASE),
    re.compile(r"(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})\s*(?:to|-|–|—)\s*(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})"),
]


def _parse_one_date(s: str) -> Optional[date]:
    s = s.strip()
    for pat in DATE_PATTERNS:
        m = pat.search(s)
        if not m:
            continue
        g = m.groups()
        try:
            if g[1].isalpha():
                # DD-MMM-YYYY
                d = int(g[0])
                mon = MONTH_MAP.get(g[1].upper()[:3])
                if not mon:
                    continue
                y = int(g[2])
                if y < 100:
                    y += 2000
                return date(y, mon, d)
            elif len(g[0]) == 4:
                # YYYY-MM-DD
                return date(int(g[0]), int(g[1]), int(g[2]))
            else:
                # DD-MM-YYYY (or MM-DD-YYYY — assume DD-MM in IN context)
                d, mo, y = int(g[0]), int(g[1]), int(g[2])
                if y < 100:
                    y += 2000
                if mo > 12:  # caller swapped — fall back to MM-DD
                    d, mo = mo, d
                return date(y, mo, d)
        except (ValueError, KeyError):
            continue
    return None


def _last_day(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def detect_statement_period(content: bytes) -> Tuple[Optional[str], Optional[str]]:
    """Returns ({start_iso}, {end_iso}) or (None, None) if undetectable.

    Reads the first 2 pages of text via PyPDF2 (fast — no OCR), tries
    several regex patterns against the header. The end-date is the most
    important one (used as the snapshot date)."""
    text = ""
    try:
        from PyPDF2 import PdfReader
        reader = PdfReader(io.BytesIO(content))
        for page in reader.pages[:2]:
            try:
                text += (page.extract_text() or "") + "\n"
            except Exception:  # noqa: BLE001
                continue
    except Exception as e:  # noqa: BLE001
        logger.debug("period-detector: text extract failed: %s", e)
        return None, None

    if not text:
        return None, None

    return detect_period_from_text(text)


def detect_period_from_text(text: str) -> Tuple[Optional[str], Optional[str]]:
    """Same as `detect_statement_period` but takes already-extracted text."""
    text = text.replace("\n", " ").replace("  ", " ")

    # Pass 1: explicit "DD-MMM-YYYY to DD-MMM-YYYY"
    m = HEADER_PATTERNS[1].search(text)
    if not m:
        m = HEADER_PATTERNS[2].search(text)
    if m:
        start = _parse_one_date(m.group(1))
        end = _parse_one_date(m.group(2))
        if start and end:
            return start.isoformat(), end.isoformat()

    # Pass 2: header phrase — extract trailing chunk and try to find 2 dates
    m = HEADER_PATTERNS[0].search(text)
    if m:
        chunk = m.group(1)
        # Find any 2 dates in the chunk
        dates = []
        for pat in DATE_PATTERNS:
            for hit in pat.finditer(chunk):
                d = _parse_one_date(hit.group(0))
                if d and d not in dates:
                    dates.append(d)
                if len(dates) >= 2:
                    break
            if len(dates) >= 2:
                break
        if len(dates) >= 2:
            dates.sort()
            return dates[0].isoformat(), dates[-1].isoformat()
        if len(dates) == 1:
            d = dates[0]
            return d.replace(day=1).isoformat(), date(d.year, d.month, _last_day(d.year, d.month)).isoformat()

    # Pass 3: month-name fallback — "STATEMENT FOR FEB 2026" etc.
    m = re.search(r"\b(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*\s+(\d{4})\b", text.upper())
    if m:
        mon = MONTH_MAP.get(m.group(1))
        y = int(m.group(2))
        if mon:
            start = date(y, mon, 1)
            end = date(y, mon, _last_day(y, mon))
            return start.isoformat(), end.isoformat()

    return None, None


def detect_period_from_filename(filename: str) -> tuple:
    """Extract statement period from NSDL/CAMS-style filenames.

    Handles patterns like:
      NSDLe-CAS_106904998_DEC_2025.PDF  →  2025-12-01 / 2025-12-31
      CAMS_CAS_JAN_2026.pdf             →  2026-01-01 / 2026-01-31
      cas_feb_2026.pdf                  →  2026-02-01 / 2026-02-29
    Returns (start_iso, end_iso) or (None, None) if not detectable.
    """
    name = (filename or "").upper()
    # Pattern 1: MON_YYYY  e.g. DEC_2025
    m = re.search(r'_(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[_\s\-](\d{4})', name)
    if not m:
        # Pattern 2: MON YYYY or MON-YYYY without leading underscore
        m = re.search(r'(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[_\s\-](\d{4})', name)
    if m:
        mon = MONTH_MAP.get(m.group(1))
        y = int(m.group(2))
        if mon and 2000 <= y <= 2100:
            start = date(y, mon, 1)
            end = date(y, mon, _last_day(y, mon))
            return start.isoformat(), end.isoformat()
    return None, None
