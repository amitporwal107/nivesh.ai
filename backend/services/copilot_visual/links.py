"""Source-filing links the Copilot may show (owner, 31 Oct 2026: "source pdf link to download").

Only a link the data itself carries is ever shown (an exchange attachment URL from the filings feed or DaaS
/announcements); nothing is constructed from a symbol or a date. Before it reaches a payload it must be https and on an
exchange (or SEBI) host from the list below: anything else (http, javascript:, another host, a look-alike such as
nseindia.com.example.io, user-info in the URL) is dropped. The frontend repeats the same rule
(frontend-v5/src/components/chat/visual/schema.ts), so a forged payload cannot put another site behind "Source filing".
"""
from __future__ import annotations

from typing import Any, Optional
from urllib.parse import urlsplit

ALLOWED_HOSTS = frozenset({
    "nsearchives.nseindia.com", "archives.nseindia.com", "www.nseindia.com", "nseindia.com",
    "www.bseindia.com", "bseindia.com",
    "www.sebi.gov.in", "sebi.gov.in",
})
LINK_KINDS = ("pdf", "file", "page")
MAX_LEN = 2000


def safe_url(url: Any) -> Optional[str]:
    """The URL unchanged when it is an https link on an allowed host, else None."""
    if not isinstance(url, str):
        return None
    u = url.strip()
    if not u or len(u) > MAX_LEN or any(c.isspace() or c == "\\" or ord(c) < 32 for c in u):
        return None
    try:
        parts = urlsplit(u)
        host = parts.hostname
        parts.port  # noqa: B018 — raises ValueError on a malformed port
    except ValueError:
        return None
    if parts.scheme != "https" or not host or host not in ALLOWED_HOSTS:
        return None
    if parts.username is not None or parts.password is not None or parts.netloc.lower() not in (host, f"{host}:443"):
        return None
    return u


def kind_of(url: str) -> str:
    """"pdf" for a .pdf attachment, "page" for a web page, else "file" (the exchanges also attach .zip, .xml, .xlsx)."""
    path = urlsplit(url).path.lower()
    if path.endswith(".pdf"):
        return "pdf"
    if path.endswith((".htm", ".html", "/")) or "." not in path.rsplit("/", 1)[-1]:
        return "page"
    return "file"


def link(label: str, url: Any) -> Optional[dict]:
    """{label, url, kind} for an allowed URL, else None. The label gets "(PDF)" / "(file)" so the reader knows what opens."""
    ok = safe_url(url)
    if ok is None:
        return None
    k = kind_of(ok)
    suffix = " (PDF)" if k == "pdf" else " (file)" if k == "file" else ""
    return {"label": f"{label}{suffix}", "url": ok, "kind": k}
