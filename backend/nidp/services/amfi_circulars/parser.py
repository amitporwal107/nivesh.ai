"""AMFI circulars/notices listing-page parser.

The listing page renders a table of recent notices with the columns
roughly:
    Date | Title (linked) | optional category

We're conservative: extract every <a> whose href looks like a circular
PDF/page (under amfiindia.com or a /modules/Notices path). For each:
  - title       = link text
  - url         = absolute link href
  - published_at= heuristic date scraped from the row (best-effort)
  - kind        = inferred from title/url ('addendum'|'notice'|'circular')

If AMFI restructures their HTML, we fail soft (zero rows) so the
ingester logs a parse warning rather than crashing.
"""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime
from typing import Any, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from nidp.shared.config import AMFI_WWW

logger = logging.getLogger(__name__)


_RE_DATE = re.compile(
    r"(\d{1,2})[\s\-/]+([A-Za-z]{3,9}|\d{1,2})[\s\-/]+(\d{2,4})"
)


def _parse_date_loose(s: str) -> Optional[str]:
    m = _RE_DATE.search(s or "")
    if not m:
        return None
    raw = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    for fmt in ("%d-%b-%Y", "%d-%B-%Y", "%d-%m-%Y", "%d-%m-%y"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _infer_kind(title: str, url: str) -> str:
    h = (title + " " + url).lower()
    if "addendum" in h:
        return "addendum"
    if "circular" in h:
        return "circular"
    return "notice"


def _circular_id(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]


def parse_circulars(body: bytes) -> list[dict[str, Any]]:
    text = body.decode("utf-8", errors="replace")
    soup = BeautifulSoup(text, "html.parser")
    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    # Walk every link inside the main content. We filter to plausible
    # circular destinations: PDFs, /modules/Notices, /research-information.
    for a in soup.find_all("a", href=True):
        href = (a["href"] or "").strip()
        title = (a.get_text() or "").strip()
        if not href or not title or len(title) < 8:
            continue
        url = urljoin(AMFI_WWW + "/", href)
        # Heuristic filter: keep only links to amfi-hosted circular content
        lower = url.lower()
        if "amfiindia.com" not in lower:
            continue
        if not (
            lower.endswith(".pdf")
            or "notice" in lower
            or "circular" in lower
            or "addendum" in lower
            or "/modules/" in lower
        ):
            continue
        if url in seen:
            continue
        seen.add(url)

        # Try to lift a date from the parent row's text.
        parent_txt = ""
        if a.parent:
            parent_txt = a.parent.get_text(" ", strip=True)
        published_at = _parse_date_loose(parent_txt) or _parse_date_loose(title)

        out.append({
            "circular_id": _circular_id(url),
            "title":       title,
            "url":         url,
            "published_at": published_at,
            "kind":        _infer_kind(title, url),
        })

    return out
