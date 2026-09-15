"""Calendar-day source monitor: fetch every live/listing source, store new raw events, write a run manifest.

    python -m nidp.services.catalyst_intel.monitor --home /app/research/tpd3_forward/events [--only rbi_press,...] [--back 5]

Runs on every calendar day (cron, 7 days a week); the exchange day APIs are re-queried over a rolling window of
calendar days and deduplicated, so late publication, outages and holidays cannot lose a filing silently.
"""
from __future__ import annotations

import argparse
import http.cookiejar
import json
import logging
import time as _time
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

from ..tpd_model.event_gate import IST
from . import adapters
from .registry import SOURCES, Source, get_source
from .store import EventStore

logger = logging.getLogger(__name__)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
RUNNABLE = ("live", "listing")


def window_days(today: date, back: int = 5) -> list[date]:
    """The last `back` calendar days ending today — weekends and holidays included, on purpose."""
    return [today - timedelta(days=k) for k in range(back - 1, -1, -1)]


def _opener():
    jar = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    op.addheaders = [("User-Agent", UA), ("Accept", "application/json, application/xml, text/xml, text/html;q=0.9, */*;q=0.8")]
    return op


def _get(op, url: str, referer: Optional[str] = None, timeout: int = 60, tries: int = 3) -> bytes:
    last = None
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers={"Referer": referer} if referer else {})
            with op.open(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001 — retried, then raised to the caller which isolates it
            last = e; _time.sleep(2 * (k + 1))
    raise last


def fetch_source(source: Source, days: list[date], received_at: datetime, op=None) -> list[dict]:
    op = op or _opener()
    fn = getattr(adapters, source.adapter)
    if source.fetch == "get":
        raw = _get(op, source.url, referer=source.url)
        return fn(raw, received_at=received_at, source_id=source.id, base_url=source.url) if source.adapter == "parse_listing" else fn(raw, received_at=received_at, source_id=source.id)
    if source.fetch == "nse_api_days":
        try:
            op.open(urllib.request.Request("https://www.nseindia.com/"), timeout=20).read()
        except Exception:  # noqa: BLE001 — the API answers without the cookie from this host
            pass
        out = []
        for d in days:
            raw = _get(op, source.url.format(d=d.strftime("%d-%m-%Y")), referer="https://www.nseindia.com/companies-listing/corporate-filings-announcements")
            out += fn(raw, received_at=received_at, source_id=source.id); _time.sleep(1.0)
        return out
    if source.fetch == "cci_datatable":
        q = ("?draw=1&columns%5B0%5D%5Bdata%5D=DT_RowIndex&columns%5B1%5D%5Bdata%5D=title&columns%5B2%5D%5Bdata%5D=order_date&columns%5B3%5D%5Bdata%5D=files"
             "&order%5B0%5D%5Bcolumn%5D=0&order%5B0%5D%5Bdir%5D=desc&start=0&length=50&searchString=&fromdate=&todate=")
        req = urllib.request.Request(source.url + q, headers={"Referer": source.url, "X-Requested-With": "XMLHttpRequest", "Accept": "application/json, text/javascript, */*; q=0.01"})
        with op.open(req, timeout=60) as r:
            raw = r.read()
        return fn(raw, received_at=received_at, source_id=source.id)
    if source.fetch == "bse_subcat_days":
        out = []
        for d in days:
            for page in range(1, 40):
                raw = _get(op, source.url.format(d=d.strftime("%Y%m%d"), page=page), referer="https://www.bseindia.com/corporates/ann.html")
                rows = fn(raw, received_at=received_at, source_id=source.id); out += rows
                if len(rows) < 50:
                    break
                _time.sleep(0.5)
        return out
    raise ValueError(f"unknown fetch mode {source.fetch}")


def run_sources(sources: list[Source], store: EventStore, fetchers: Optional[dict[str, Callable]] = None, today: Optional[date] = None, back: int = 5) -> dict:
    today = today or datetime.now(IST).date()
    days = window_days(today, back)
    received_at = datetime.now(IST)
    manifest = {"run_at": received_at.isoformat(), "days": [str(d) for d in days], "sources": {}, "ok": 0, "failed": 0, "new_total": 0}
    op = _opener()
    for s in sources:
        t0 = _time.time(); rec = {"status": s.status}
        try:
            fn = (fetchers or {}).get(s.id) or (lambda src, dd, ra: fetch_source(src, dd, ra, op))
            events = fn(s, days, received_at)
            new = store.add(events)
            rec.update(fetched=len(events), new=new, seconds=round(_time.time() - t0, 1)); manifest["ok"] += 1; manifest["new_total"] += new
        except Exception as e:  # noqa: BLE001 — one source must never stop the others
            rec.update(error=f"{type(e).__name__}: {str(e)[:200]}", seconds=round(_time.time() - t0, 1)); manifest["failed"] += 1
            logger.warning("source %s failed: %s", s.id, rec["error"])
        manifest["sources"][s.id] = rec
    runs = store.home / "runs"; runs.mkdir(exist_ok=True)
    (runs / f"{received_at.strftime('%Y-%m-%dT%H%M%S')}.json").write_text(json.dumps(manifest, indent=1))
    return manifest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--home", type=Path, required=True); ap.add_argument("--only", default=None); ap.add_argument("--back", type=int, default=5)
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ids = a.only.split(",") if a.only else [s.id for s in SOURCES if s.status in RUNNABLE]
    m = run_sources([get_source(i) for i in ids], EventStore(a.home), back=a.back)
    logger.info("run: %d sources ok, %d failed, %d new events", m["ok"], m["failed"], m["new_total"])
    for sid, r in m["sources"].items():
        logger.info("  %-26s %s", sid, r.get("error") or f"fetched {r['fetched']:5d} new {r['new']:5d} ({r['seconds']}s)")
    return 0 if m["failed"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
