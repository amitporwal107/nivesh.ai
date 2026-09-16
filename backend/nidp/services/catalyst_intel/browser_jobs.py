"""File-based browser-job queue: the monitor enqueues a job for every source whose HTTP routes fail (or that is
browser-only), a worker with a real browser on some other egress (a laptop, an office box, app-vm once a browser
is installed) runs the jobs and drops results in done/, and the monitor ingests those through the same adapters.

    <home>/browser_jobs/pending/<source_id>__<hash>.json     what to fetch (url, adapter, reason)
    <home>/browser_jobs/done/<same name>.json                {status, http_status, fetched_at, egress, body_b64}
    <home>/browser_jobs/archive/<name>.<ts>.json             results after ingestion

Worker:  python -m nidp.services.catalyst_intel.browser_jobs worker --home <home> [--once] [--egress laptop]
Requires playwright + chromium on the worker host only; the analytics VM never needs a browser."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import logging
import time as _time
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..tpd_model.event_gate import IST
from . import adapters
from .transports import Response, classify

logger = logging.getLogger(__name__)
ADAPTER_NEEDS_BASE_URL = ("parse_listing", "parse_cppp_table")


def _dirs(home: Path) -> dict[str, Path]:
    d = {k: Path(home) / "browser_jobs" / k for k in ("pending", "done", "archive")}
    for p in d.values():
        p.mkdir(parents=True, exist_ok=True)
    return d


def job_name(source_id: str, url: str) -> str:
    return f"{source_id}__{hashlib.sha1(url.encode()).hexdigest()[:8]}.json"


def enqueue(home: Path, source, route, reason: str, at: Optional[datetime] = None, adapter_kwargs: Optional[dict] = None) -> Path:
    """Idempotent: an identical pending job is not duplicated."""
    d = _dirs(home)
    p = d["pending"] / job_name(source.id, route.url)
    if p.exists():
        return p
    job = {"source_id": source.id, "name": source.name, "url": route.url, "adapter": route.adapter, "fetch": route.fetch, "mode": "browser", "reason": reason,
           "enqueued_at": (at or datetime.now(IST)).isoformat(), "adapter_kwargs": adapter_kwargs or {},
           "actions": [{"goto": route.url}, {"wait": "networkidle"}, {"capture": "html"}], "notes": source.notes}
    p.write_text(json.dumps(job, indent=1, ensure_ascii=False))
    return p


def pending(home: Path) -> list[Path]:
    return sorted(_dirs(home)["pending"].glob("*.json"))


def ingest_results(home: Path, store, health, registry: Optional[dict] = None) -> dict:
    """Read done/*.json, run the adapter on the captured body, store the events, update health, archive the file."""
    d = _dirs(home)
    summary = {"ingested": 0, "new_events": 0, "failed": 0}
    for p in sorted(d["done"].glob("*.json")):
        try:
            res = json.loads(p.read_text())
            sid, status = res["source_id"], res.get("status", "ok")
            fetched_at = datetime.fromisoformat(res["fetched_at"]) if res.get("fetched_at") else datetime.now(IST)
            if fetched_at.tzinfo is None:
                fetched_at = fetched_at.replace(tzinfo=IST)
            if status == "ok" and res.get("body_b64"):
                fn = getattr(adapters, res["adapter"])
                kw = dict(res.get("adapter_kwargs") or {})
                if res["adapter"] in ADAPTER_NEEDS_BASE_URL:
                    kw.setdefault("base_url", res["url"])
                if "day" in kw and isinstance(kw["day"], str):
                    kw["day"] = datetime.fromisoformat(kw["day"]).date()
                events = fn(base64.b64decode(res["body_b64"]), received_at=fetched_at, source_id=sid, **kw)
                new = store.add(events)
                health.record(sid, observed="live_browser", fetched=len(events), at=fetched_at, route=f"browser:{res.get('egress', '?')}")
                summary["ingested"] += 1; summary["new_events"] += new
            else:
                health.record(sid, observed=status if status != "ok" else "empty_response", fetched=0, at=fetched_at, route=None, error=res.get("error") or f"browser status {status}")
                summary["failed"] += 1
            (d["pending"] / p.name).unlink(missing_ok=True)
        except Exception as e:  # noqa: BLE001 — one bad result must not block the rest
            logger.warning("browser result %s failed: %s", p.name, e)
            summary["failed"] += 1
        p.rename(d["archive"] / f"{p.stem}.{datetime.now(IST).strftime('%Y%m%dT%H%M%S')}.json")
    health.save()
    return summary


def run_worker(home: Path, once: bool = True, egress: str = "worker", headless: bool = True, sleep_s: int = 60) -> int:
    """Executes pending jobs with Playwright/Chromium. Returns 3 when no browser is available (loudly)."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("browser worker: playwright is not installed on this host (pip install playwright && playwright install chromium)")
        return 3
    d = _dirs(home)
    while True:
        jobs = pending(home)
        if jobs:
            with sync_playwright() as pw:
                try:
                    browser = pw.chromium.launch(headless=headless)
                except Exception as e:  # noqa: BLE001
                    print(f"browser worker: chromium launch failed: {e}")
                    return 3
                for p in jobs:
                    job = json.loads(p.read_text())
                    page = browser.new_page()
                    status_code, body, err = 0, b"", None
                    try:
                        r = page.goto(job["url"], wait_until="networkidle", timeout=90_000)
                        status_code = r.status if r else 0
                        body = page.content().encode()
                    except Exception as e:  # noqa: BLE001
                        err = f"{type(e).__name__}: {str(e)[:200]}"
                    finally:
                        page.close()
                    observed = classify(Response(status_code or 599, body, {}, job["url"], f"browser:{egress}")) if not err else "unreachable"
                    out = {"source_id": job["source_id"], "url": job["url"], "adapter": job["adapter"], "adapter_kwargs": job.get("adapter_kwargs", {}),
                           "status": observed, "http_status": status_code, "fetched_at": datetime.now(IST).isoformat(), "egress": egress,
                           "body_b64": base64.b64encode(body).decode() if observed == "ok" else "", "error": err}
                    (d["done"] / p.name).write_text(json.dumps(out))
                    print(f"{job['source_id']:28s} {observed:18s} http={status_code} bytes={len(body)}")
                browser.close()
        if once:
            return 0
        _time.sleep(sleep_s)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("worker"); w.add_argument("--home", type=Path, required=True); w.add_argument("--once", action="store_true"); w.add_argument("--egress", default="worker"); w.add_argument("--headed", action="store_true")
    ls = sub.add_parser("list"); ls.add_argument("--home", type=Path, required=True)
    a = ap.parse_args(argv)
    if a.cmd == "list":
        for p in pending(a.home):
            j = json.loads(p.read_text()); print(f"{j['source_id']:28s} {j['reason']:18s} {j['url']}")
        return 0
    return run_worker(a.home, once=a.once, egress=a.egress, headless=not a.headed)


if __name__ == "__main__":
    raise SystemExit(main())
