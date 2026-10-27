"""Collect recent exchange filings and the text of their attached documents.

Runs inside the backend image (it needs httpx and pdfplumber, which the host does not have).
Filings come from the NIDP data API; documents are downloaded from the exchange's archive.

Writes <out>/filings/<id>.json — one file per filing, with `text` and a `text_status`: OK, OK_OCR
(some pages were scanned images and were read by OCR, see ocr.py), or why the text is empty:
NO_URL, DOWNLOAD_FAILED, NOT_A_PDF or NO_TEXT (no text layer, and OCR read nothing or is not
installed). A filing without text can still be filtered on its subject; it cannot be analysed.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pdfplumber

import ea_core as core
import ocr

PAGE = 120                      # the data API's ceiling for /market-pulse/articles
MAX_PDF_BYTES = 15 * 1024 * 1024
MAX_PAGES = 8
PACE = 0.3                      # seconds between archive downloads
MAX_OCR_DOCS = 30               # documents OCR'd per run (~5 s a page, up to MAX_PAGES pages each)
# Subjects whose documents carry figures: what --reocr-since collects again when the old record is short.
DOC_SUBJECT = re.compile(r"(?i)outcome of board meeting|financial result|press release|investor presentation"
                         r"|analysts?/institutional investor meet|earnings call|transcript|business update")
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"


def fetch_feed(client: httpx.Client, base: str, key: str, days: int):
    """Every filing in the window, newest first."""
    offset = 0
    while True:
        r = client.get(f"{base}/v1/market-pulse/articles", headers={"X-API-Key": key},
                       params={"days": days, "limit": PAGE, "offset": offset, "sort": "latest"})
        r.raise_for_status()
        rows = r.json().get("articles") or []
        yield from rows
        if len(rows) < PAGE:
            return
        offset += len(rows)


def document_text(client: httpx.Client, url: str | None, use_ocr: bool = False) -> tuple[str, str, dict]:
    """(text, text_status, page info). Pages with no text layer are OCR'd when `use_ocr`."""
    if not url:
        return "", "NO_URL", {}
    try:
        r = client.get(url, headers={"User-Agent": UA}, follow_redirects=True)
        r.raise_for_status()
    except httpx.HTTPError:
        return "", "DOWNLOAD_FAILED", {}
    body = r.content
    if not body.startswith(b"%PDF") or len(body) > MAX_PDF_BYTES:
        return "", "NOT_A_PDF", {}
    try:
        with pdfplumber.open(io.BytesIO(body)) as pdf:
            pages = [(page.extract_text() or "") for page in pdf.pages[:MAX_PAGES]]
    except Exception:  # noqa: BLE001 — a malformed PDF is reported as a status, not a crash
        return "", "NO_TEXT", {}
    text, info = ocr.fill(body, pages, enabled=use_ocr)
    text = text.strip()[:core.ANALYSIS_TEXT_CHARS]
    if len(text) < 80:
        return "", "NO_TEXT", info
    return text, ("OK_OCR" if info["ocr_pages"] else "OK"), info


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Collect filings and document text for the event AI analysis")
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--days", type=int, default=3)
    p.add_argument("--max", type=int, default=250, help="new filings to collect this run")
    p.add_argument("--list", type=Path, help="JSON-lines filing list to use instead of the data API feed "
                                             "(the feed only reaches back 30 days)")
    p.add_argument("--reocr-since", help="YYYY-MM-DD: also collect again the filings from this date that were "
                                         "collected before OCR and may hold scanned pages (see ocr.needs_ocr)")
    p.add_argument("--max-ocr", type=int, default=MAX_OCR_DOCS, help="documents OCR'd this run")
    a = p.parse_args(argv)
    if a.reocr_since and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", a.reocr_since):
        print("--reocr-since must be YYYY-MM-DD", file=sys.stderr)
        return 2

    base = (os.environ.get("NIDP_DAAS_BASE_URL") or "").rstrip("/")
    key = os.environ.get("NIDP_DAAS_INTERNAL_TOKEN") or os.environ.get("NIDP_DAAS_API_KEY") or ""
    if not a.list and (not base or not key):
        print("NIDP_DAAS_BASE_URL and a data API key must be set", file=sys.stderr)
        return 2
    out = a.out / "filings"
    out.mkdir(parents=True, exist_ok=True)
    have = {p.stem for p in out.glob("*.json")}
    ocr_on = ocr.available()
    tally = {"seen": 0, "routine_skipped": 0, "already_collected": 0, "collected": 0, "recollected_for_ocr": 0,
             "ocr_available": ocr_on, "ocr_docs": 0, "ocr_pages": 0, "text": {}}

    with httpx.Client(timeout=45) as client:
        feed = ((json.loads(line) for line in a.list.read_text().splitlines() if line.strip())
                if a.list else fetch_feed(client, base, key, a.days))
        for f in feed:
            tally["seen"] += 1
            if not core.candidates([f], set()):
                tally["routine_skipped"] += 1
                continue
            again = False
            if f["id"] in have:
                if ocr_on and tally["ocr_docs"] < a.max_ocr:
                    try:
                        rec = json.loads((out / f"{f['id']}.json").read_text())
                    except (OSError, ValueError):
                        rec = {}
                    again = ocr.needs_ocr(rec, ocr_on, a.reocr_since,
                                          lambda r: DOC_SUBJECT.search(str(r.get("title") or "")))
                if not again:
                    tally["already_collected"] += 1
                    continue
            if tally["collected"] + tally["recollected_for_ocr"] >= a.max:
                continue
            use_ocr = ocr_on and tally["ocr_docs"] < a.max_ocr
            text, status, info = document_text(client, f.get("url"), use_ocr=use_ocr)
            time.sleep(PACE)
            row = {k: f.get(k) for k in ("id", "symbol", "company", "title", "summary", "source", "when", "url")}
            row.update(text=text, text_status=status, pages=info.get("pages"),
                       low_text_pages=info.get("low_text_pages", []), ocr=info.get("ocr"),
                       ocr_pages=info.get("ocr_pages", []), collected_at=datetime.now(timezone.utc).isoformat())
            (out / f"{f['id']}.json").write_text(json.dumps(row, ensure_ascii=False))
            tally["recollected_for_ocr" if again else "collected"] += 1
            if info.get("ocr"):
                tally["ocr_docs"] += 1
                tally["ocr_pages"] += len(info.get("ocr_pages") or [])
            tally["text"][status] = tally["text"].get(status, 0) + 1
    print(json.dumps(tally))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
