"""Content guard — detect error/bot-block pages served with HTTP 200.

The dominant *silent* feed failure is a source returning a human error page
(Akamai "Access Denied", a WAF "Request Rejected", a Cloudflare challenge, a
"under maintenance" notice) with **HTTP 200**. The fetch layer trusts the 200,
and a lenient parser (amfi_nav, rbi_yields) reduces the page to 0 rows → the run
is marked SKIPPED (indistinguishable from a holiday) instead of FAILED. See
HANDOFF-FEED-RELIABILITY.md §D1/D2.

`detect_unsupported_content()` returns a reason string when the body matches a
**high-confidence error-page signature**, else None. It is deliberately
CONSERVATIVE: it only matches phrases that never appear in legitimate market
data (CSV/JSON/XLS/ZIP or even a real RBI/NSE HTML table), so it is safe to run
against EVERY feed — including the ones that legitimately parse HTML. Binary
payloads (zip/gzip/xls) are skipped outright (an error page is always text).

Extend `_ERROR_PAGE_SIGNATURES` as new block/maintenance pages are observed.
"""
from __future__ import annotations

from typing import Optional

# Marker raised by fetchers that want to fail loud at fetch time. BaseIngester
# also has a non-exception path (finalize FAILED with error_class="CONTENT").
class UnsupportedContentError(Exception):
    """Source returned a non-data error/bot-block page under HTTP 200."""


# (lowercased needle, human reason). Matched against the first few KB of the
# body, lowercased. Keep these SPECIFIC — a false positive fails a good run.
_ERROR_PAGE_SIGNATURES: list[tuple[bytes, str]] = [
    (b"access denied",                         "CDN/Akamai 'Access Denied' (bot block)"),
    (b"you don't have permission to access",   "403 permission-denied page"),
    (b"the requested url was rejected",        "WAF 'Request Rejected'"),
    (b"request rejected",                       "WAF 'Request Rejected'"),
    (b"attention required! | cloudflare",       "Cloudflare challenge"),
    (b"cf-browser-verification",                "Cloudflare browser challenge"),
    (b"/cdn-cgi/challenge-platform",            "Cloudflare challenge"),
    (b"under maintenance",                      "source 'under maintenance' page"),
    (b"temporarily unavailable",                "source 'temporarily unavailable' page"),
    (b"service temporarily unavailable",        "503 service-unavailable page"),
]

# Binary magic bytes — an error page is never binary, so skip the scan.
_BINARY_MAGIC: tuple[bytes, ...] = (
    b"PK",          # zip / xlsx
    b"\x1f\x8b",    # gzip
    b"\xd0\xcf\x11\xe0",  # legacy .xls (OLE2)
    b"%PDF",        # pdf
)


# Magic-byte → content type. An error page is never binary, so these also let
# the content sniffer distinguish real binary payloads from text/HTML.
_MAGIC_TYPES: list[tuple[bytes, str]] = [
    (b"PK\x03\x04",                 "application/zip"),            # zip / xlsx
    (b"PK\x05\x06",                 "application/zip"),            # empty zip
    (b"\x1f\x8b",                   "application/gzip"),
    (b"%PDF",                       "application/pdf"),
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "application/vnd.ms-excel"),  # OLE2 .xls
]


def sniff_content_type(body: bytes) -> Optional[str]:
    """Best-effort content type from the actual bytes (magic + leading chars).
    Returns None for plain CSV/text (no reliable magic) — callers treat None as
    'unknown, don't flag'. Used to detect source format drift vs the URL-guessed
    type (a `.csv` URL that actually returned zip/HTML/pdf)."""
    if not body:
        return None
    for magic, mime in _MAGIC_TYPES:
        if body.startswith(magic):
            return mime
    head = body[:512].lstrip()[:200].lower()
    if head[:1] in (b"[", b"{"):
        return "application/json"
    if head.startswith(b"<!doctype html") or head.startswith(b"<html") or b"<html" in head:
        return "text/html"
    if head.startswith(b"<?xml"):
        return "application/xml"
    return None


def detect_unsupported_content(body: bytes, *, sample_bytes: int = 8192) -> Optional[str]:
    """Return a reason string if `body` looks like an error/bot-block page,
    else None. Never raises. Empty bodies return None (handled upstream as
    SKIPPED)."""
    if not body:
        return None
    head = body[:sample_bytes]
    if head.startswith(_BINARY_MAGIC):
        return None
    low = head.lower()
    for needle, reason in _ERROR_PAGE_SIGNATURES:
        if needle in low:
            return reason
    return None
