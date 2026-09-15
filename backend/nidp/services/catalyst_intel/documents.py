"""Document text for filings whose exchange summary says nothing ("as per attachment", "has informed the Exchange
about <category>"): fetch the attachment once, extract text with pdftotext, cache by event hash, cap the size."""
from __future__ import annotations

import re
import subprocess
import tempfile
import urllib.request
from pathlib import Path
from typing import Callable, Optional

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
EXCHANGE_SOURCES = ("nse_announcements_api", "nse_announcements_rss", "bse_subcat_api", "bse_announcements_rss")
ROUTINE = ("Trading Window", "Analysts/Institutional Investor Meet/Con. Call Updates", "Shareholders meeting", "Copy of Newspaper Publication", "ESOP/ESOS/ESPS", "Reply to Clarification- Financial results")
_GENERIC = re.compile(r"has informed the exchange (?:about|regarding)\s+[A-Za-z()/ ,'-]{3,60}\.?$|as per attachment|please find (?:enclosed|attached)|^\s*$", re.I)


def needs_document(e: dict) -> bool:
    if e.get("source_id") not in EXCHANGE_SOURCES or (e.get("category") or "") in ROUTINE:
        return False
    if not (e.get("url") or "").lower().endswith(".pdf"):
        return False
    s = (e.get("summary") or "").strip()
    return len(s) < 40 or bool(_GENERIC.search(s))


def _fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": "https://www.nseindia.com/" if "nse" in url else "https://www.bseindia.com/"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def _extract(pdf: bytes) -> str:
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as f:
        f.write(pdf); f.flush()
        out = subprocess.run(["pdftotext", "-layout", "-l", "6", f.name, "-"], capture_output=True, text=True, timeout=60)
    return re.sub(r"[ \t]+", " ", out.stdout)


class DocumentCache:
    def __init__(self, home: Path, fetch: Callable[[str], bytes] = _fetch, extract: Callable[[bytes], str] = _extract, max_chars: int = 20_000):
        self.home = Path(home); self.home.mkdir(parents=True, exist_ok=True); self.fetch, self.extract, self.max_chars = fetch, extract, max_chars

    def text(self, event_hash: str, url: str) -> Optional[str]:
        p = self.home / f"{event_hash}.txt"
        if p.exists():
            return p.read_text()
        try:
            t = self.extract(self.fetch(url))[: self.max_chars]
        except Exception as e:  # noqa: BLE001 — a missing document is recorded, not fatal
            t = ""; (self.home / f"{event_hash}.err").write_text(f"{type(e).__name__}: {e}")
        p.write_text(t)
        return t or None
