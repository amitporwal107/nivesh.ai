"""SEBI circulars parsers: the site RSS feed and the Legal listing pages.

RSS (https://www.sebi.gov.in/sebirss.xml), as served on 2026-10-14:
    <rss><channel>… <item><title>…</title><description>…</description>
        <link>https://www.sebi.gov.in/<section>/<kind>/<mon-yyyy>/<slug>_<id>.html</link>
        <pubDate>13 Oct, 2026 +0530</pubDate></item> …
The feed mixes every kind of SEBI item (enforcement orders, recovery notices, press releases,
circulars). Recovery notices name individuals with their PAN in the title and description.
Only items whose link path starts with /legal/circulars/ or /legal/master-circulars/ are kept;
everything else is dropped before it leaves this module. The description is never kept.
redact_rss() gives the feed with those items already removed: the ingester archives that copy,
never the bytes as fetched.

Listing pages (sebiweb/home/HomeAction.do?doListing=yes&sid=1&ssid=7 circulars, ssid=6 master
circulars) render a table:  Date ("Oct 07, 2026") | Title (linked to the circular's page).
Only page 1 (the 25 newest) is a plain GET; later pages are a JavaScript form post.

Neither source says which SEBI department issued an item (the department is only a search
filter on the listing page), so `department` is always None here.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime
from typing import Any, Optional
from urllib.parse import urljoin, urlsplit, urlunsplit
from xml.etree import ElementTree as ET

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

SEBI_HOST = "www.sebi.gov.in"
SEBI_WWW = f"https://{SEBI_HOST}"

# Link path prefix → kind. The two prefixes do not overlap.
_KIND_BY_PREFIX: tuple[tuple[str, str], ...] = (
    ("/legal/circulars/", "circular"),
    ("/legal/master-circulars/", "master_circular"),
)
KINDS: tuple[str, ...] = tuple(k for _, k in _KIND_BY_PREFIX)

# A PAN: five letters, four digits, one letter. A circular's title never carries one; if one
# ever does, the row is dropped rather than stored (defence in depth behind the path filter).
_PAN_RE = re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b")

# "13 Oct, 2026 +0530" (RSS pubDate) and RFC 822 "Mon, 13 Oct 2026 10:00:00 +0530".
_RE_DAY_MON_YEAR = re.compile(r"\b(\d{1,2})\s+([A-Za-z]{3})[A-Za-z]*\.?,?\s+(\d{4})\b")
# "Oct 07, 2026" (listing Date column).
_RE_MON_DAY_YEAR = re.compile(r"\b([A-Za-z]{3})[A-Za-z]*\.?\s+(\d{1,2}),?\s+(\d{4})\b")


class SebiFeedError(ValueError):
    """The body is not the SEBI RSS feed (not XML, or no <channel>)."""


def kind_for_url(url: str) -> Optional[str]:
    """'circular' | 'master_circular' for a sebi.gov.in link under /legal/circulars/ or
    /legal/master-circulars/, else None (enforcement orders, recovery notices, press releases,
    other hosts, the bare section index)."""
    try:
        parts = urlsplit((url or "").strip())
    except ValueError:
        return None
    if parts.scheme not in ("http", "https"):
        return None
    if (parts.hostname or "").lower() not in (SEBI_HOST, "sebi.gov.in"):
        return None
    for prefix, kind in _KIND_BY_PREFIX:
        if parts.path.startswith(prefix) and len(parts.path) > len(prefix):
            return kind
    return None


def canonical_url(url: str) -> str:
    """https://www.sebi.gov.in<path>[?query] — one key per circular whichever source or scheme
    it arrived with."""
    parts = urlsplit(url.strip())
    return urlunsplit(("https", SEBI_HOST, parts.path, parts.query, ""))


def parse_sebi_day(text: Optional[str]) -> Optional[date]:
    """The calendar day in an RSS pubDate or a listing Date cell, or None."""
    s = (text or "").strip()
    m = _RE_DAY_MON_YEAR.search(s)
    if m:
        day, mon, year = m.group(1), m.group(2), m.group(3)
    else:
        m = _RE_MON_DAY_YEAR.search(s)
        if not m:
            return None
        mon, day, year = m.group(1), m.group(2), m.group(3)
    try:
        return datetime.strptime(f"{int(day):02d} {mon.title()} {year}", "%d %b %Y").date()
    except ValueError:
        return None


def _clean_title(t: Optional[str]) -> str:
    return re.sub(r"\s+", " ", t or "").strip()


def _row(url: str, title: str, issued_on: Optional[date], source: str) -> Optional[dict[str, Any]]:
    kind = kind_for_url(url)
    if kind is None or not title:
        return None
    if _PAN_RE.search(title):
        logger.warning("sebi_circulars: dropped a %s item whose title carries a PAN-like token", kind)
        return None
    return {
        "url": canonical_url(url),
        "title": title,
        "kind": kind,
        "issued_on": issued_on,
        "department": None,
        "source": source,
    }


def _rss_channel(body: bytes) -> tuple[ET.Element, ET.Element]:
    """(root, channel) of the SEBI RSS feed. Raises SebiFeedError when the body is not an RSS
    document, so a changed or blocked feed fails the run instead of reading as "no circulars"."""
    if not body or not body.strip():
        raise SebiFeedError("empty body")
    head = body[:4096].lower()
    if b"<!entity" in head:
        # An RSS feed never declares entities; refuse rather than expand them.
        raise SebiFeedError("feed declares XML entities")
    try:
        root = ET.fromstring(body)
    except ET.ParseError as e:
        raise SebiFeedError(f"not XML: {e}") from e
    channel = root.find("channel") if root.tag == "rss" else None
    if channel is None:
        raise SebiFeedError(f"no rss/channel element (root <{root.tag}>)")
    return root, channel


def _item_row(it: ET.Element) -> Optional[dict[str, Any]]:
    return _row(
        urljoin(SEBI_WWW + "/", (it.findtext("link") or "").strip()),
        _clean_title(it.findtext("title")),
        parse_sebi_day(it.findtext("pubDate")),
        "sebi_rss",
    )


def parse_rss(body: bytes) -> list[dict[str, Any]]:
    """Circular and master-circular rows from the SEBI RSS feed; every other item is dropped."""
    _, channel = _rss_channel(body)
    items = channel.findall("item")
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for it in items:
        row = _item_row(it)
        if row is None or row["url"] in seen:
            continue
        seen.add(row["url"])
        out.append(row)
    logger.info("sebi_circulars rss: %d items, %d circulars kept", len(items), len(out))
    return out


def redact_rss(body: bytes) -> bytes:
    """The feed with every item that parse_rss would drop removed, for the raw archive.

    The ingester archives the bytes it fetched; the feed's recovery notices name individuals
    with their PAN, so only this redacted copy (channel header + circular items) is handed on."""
    root, channel = _rss_channel(body)
    for it in channel.findall("item"):
        if _item_row(it) is None:
            channel.remove(it)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def parse_listing(body: bytes) -> list[dict[str, Any]]:
    """Circular and master-circular rows from a SEBI Legal listing page (page 1).

    Each data row of the listing table is  <td>Oct 07, 2026</td> <td><a href=… title=…>…</a></td>.
    Links outside the two Legal sections (menus, footers) are ignored by kind_for_url."""
    text = body.decode("utf-8", errors="replace")
    soup = BeautifulSoup(text, "html.parser")
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for tr in soup.find_all("tr"):
        cells = tr.find_all("td")
        if len(cells) < 2:
            continue
        a = tr.find("a", href=True)
        if a is None:
            continue
        title = _clean_title(a.get("title") or a.get_text(" "))
        row = _row(
            urljoin(SEBI_WWW + "/", a["href"].strip()),
            title,
            parse_sebi_day(cells[0].get_text(" ")),
            "sebi_listing",
        )
        if row is None or row["url"] in seen:
            continue
        seen.add(row["url"])
        out.append(row)
    logger.info("sebi_circulars listing: %d circulars", len(out))
    return out
