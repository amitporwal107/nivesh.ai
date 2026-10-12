"""Collect recent exchange filings and the text of their attached documents.

Runs inside the backend image (it needs httpx and pdfplumber, which the host does not have).
Filings come from the NIDP data API; documents are downloaded from the exchange's archive.

Writes <out>/filings/<id>.json — one file per filing, with `text` and a `text_status` that says
why the text is empty when it is: NO_URL, DOWNLOAD_FAILED, NOT_A_PDF or NO_TEXT (a scanned
document). A filing without text can still be filtered on its subject; it cannot be analysed.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
from pathlib import Path

import httpx
import pdfplumber

import ea_core as core

PAGE = 120                      # the data API's ceiling for /market-pulse/articles
MAX_PDF_BYTES = 15 * 1024 * 1024
MAX_PAGES = 8
PACE = 0.3                      # seconds between archive downloads
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


def document_text(client: httpx.Client, url: str | None) -> tuple[str, str]:
    if not url:
        return "", "NO_URL"
    try:
        r = client.get(url, headers={"User-Agent": UA}, follow_redirects=True)
        r.raise_for_status()
    except httpx.HTTPError:
        return "", "DOWNLOAD_FAILED"
    body = r.content
    if not body.startswith(b"%PDF") or len(body) > MAX_PDF_BYTES:
        return "", "NOT_A_PDF"
    try:
        with pdfplumber.open(io.BytesIO(body)) as pdf:
            text = "\n".join((page.extract_text() or "") for page in pdf.pages[:MAX_PAGES])
    except Exception:  # noqa: BLE001 — a malformed PDF is reported as a status, not a crash
        return "", "NO_TEXT"
    text = text.strip()[:core.ANALYSIS_TEXT_CHARS]
    return (text, "OK") if len(text) >= 80 else ("", "NO_TEXT")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Collect filings and document text for the event AI analysis")
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--days", type=int, default=3)
    p.add_argument("--max", type=int, default=250, help="new filings to collect this run")
    a = p.parse_args(argv)

    base = (os.environ.get("NIDP_DAAS_BASE_URL") or "").rstrip("/")
    key = os.environ.get("NIDP_DAAS_INTERNAL_TOKEN") or os.environ.get("NIDP_DAAS_API_KEY") or ""
    if not base or not key:
        print("NIDP_DAAS_BASE_URL and a data API key must be set", file=sys.stderr)
        return 2
    out = a.out / "filings"
    out.mkdir(parents=True, exist_ok=True)
    have = {p.stem for p in out.glob("*.json")}
    tally = {"seen": 0, "routine_skipped": 0, "already_collected": 0, "collected": 0, "text": {}}

    with httpx.Client(timeout=45) as client:
        for f in fetch_feed(client, base, key, a.days):
            tally["seen"] += 1
            if not core.candidates([f], set()):
                tally["routine_skipped"] += 1
                continue
            if f["id"] in have:
                tally["already_collected"] += 1
                continue
            if tally["collected"] >= a.max:
                continue
            text, status = document_text(client, f.get("url"))
            time.sleep(PACE)
            row = {k: f.get(k) for k in ("id", "symbol", "company", "title", "summary", "source", "when", "url")}
            row.update(text=text, text_status=status)
            (out / f"{f['id']}.json").write_text(json.dumps(row, ensure_ascii=False))
            tally["collected"] += 1
            tally["text"][status] = tally["text"].get(status, 0) + 1
    print(json.dumps(tally))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
