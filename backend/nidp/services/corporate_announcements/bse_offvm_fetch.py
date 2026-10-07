#!/usr/bin/env python3
"""Fetch BSE corporate-announcement history from a NON-CLOUD network.

STANDALONE: Python 3.9+ standard library only. No pip install, no nidp imports.
Copy this one file to your own machine and run it there.

WHY THIS RUNS OFF THE VM

api.bseindia.com answers HTTP 403 "Access Denied" to cloud networks — nidp-stack-vm
directly AND through the app-vm proxy — since 2026-09-23. It is a cloud-ASN block:
the identical request succeeds from a home or office connection, which is why
www.bseindia.com/corporates/ann works in a browser. The announcements page itself
calls this same host (its route chunk builds "/AnnSubCategoryGetData/w" on top of
https://api.bseindia.com), so the only way to history is a non-cloud network.

WHAT IT SAVES — AND WHY IN THIS SHAPE

For every calendar day it saves EXACTLY the bytes the production ingesters'
fetch() would have returned: every page's raw JSON, joined by the \\x1e record
separator that production parse() splits on. The VM replays those bytes through
the production pipeline unchanged (DQ gate, raw archive, parse, validate, upsert,
validation, job log), so the rows carry genuine NEWSID-based ids, CATEGORYNAME and
SUBCATNAME — none of which the RSS stopgap could provide.

The request constants below mirror backend/nidp/services/corporate_announcements/
service.py and nidp/shared/sources/nse_fetcher.py. A test on the VM
(test_bse_offvm.py) imports both and fails if they ever drift apart.

  <out>/coarse/YYYY-MM-DD.bin    AnnGetData/w, strCat=-1   (BseAnnouncementsIngester)
  <out>/subcat/YYYY-MM-DD.bin    AnnSubCategoryGetData/w   (BseSubcategoryAnnouncementsIngester)
  <out>/<kind>/YYYY-MM-DD.json   pages, bytes, sha256, last_url, last_status
  <out>/manifest.json            every file with its sha256 (the VM verifies these)

USAGE

  python3 bse_offvm_fetch.py --self-test
  python3 bse_offvm_fetch.py --from 2024-06-01 --to 2026-09-25 --out bse_history

It is resumable: a day whose .bin and .json both exist is skipped, so it can be
stopped and restarted freely. A day that fails is NOT written, so the next run
retries it. It stops at once on HTTP 403 — that means your network is blocked
too, and continuing would only hammer the exchange.

PROXY (for runs on cloud infrastructure, e.g. a Cloud Run job)

Cloud egress is blocked at the exchange's edge — verified from a Cloud Run job
(egress 34.96.40.138, HTTP 403) as well as both VMs. A cloud run therefore needs a
proxy whose exit IPs are not cloud ranges. The proxy URL carries credentials, so
it is NEVER a command-line argument (argv is visible to every process) and is
never printed: set BSE_PROXY_URL in the environment (on Cloud Run: from Secret
Manager via --set-secrets), or pass --proxy-file PATH to a file holding it.
Format: http://USER:PASS@HOST:PORT (must support HTTPS CONNECT). --self-test
prints the egress IP so you can confirm traffic really leaves via the proxy.

Pace: one request per --delay seconds (default 1.0, matching production's own
throttle). Expect roughly 10-15 hours for Jun-2024 -> Sep-2026 — run it overnight,
or in chunks with --from/--to.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
import zlib
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode, urlsplit

FETCHER_VERSION = "bse-offvm-1"

# ── Mirrors of production constants (drift is caught by test_bse_offvm.py) ──────
COARSE_URL_TMPL = (
    "https://api.bseindia.com/BseIndiaAPI/api/AnnGetData/w"
    "?pageno={page}&strCat=-1&strPrevDate={d}&strToDate={d}"
    "&strScrip=&strSearch=P&strType=C&subcategory=-1"
)
SUBCAT_URL = "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
COARSE_MAX_PAGES = 20
SUBCAT_MAX_PAGES = 10
# taxonomy.iter_slices(), in production order; empty subcategory = every filing in
# the category, each row carrying its real SUBCATNAME.
CATEGORIES = (
    "Company Update", "Result", "Board Meeting", "Corp. Action", "AGM/EGM",
    "Insider Trading / SAST", "New Listing", "Integrated Filing", "Others",
)
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/124.0.0.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Referer": "https://www.bseindia.com/corporates/ann.html",
}
RECORD_SEP = b"\x1e"


def coarse_url(d: str, page: int) -> str:
    return COARSE_URL_TMPL.format(d=d, page=page)


def subcat_url(category: str, subcategory: str, d: str, page: int) -> str:
    # Same keys, same order, same encoding as service._bse_subcat_url.
    return SUBCAT_URL + "?" + urlencode({
        "pageno": page, "strCat": category, "strPrevDate": d, "strToDate": d,
        "strscrip": "", "strSearch": "P", "strType": "C", "subcategory": subcategory,
    })


def coarse_page_is_last(body: bytes) -> bool:
    """BseAnnouncementsIngester.fetch's stop rule, verbatim."""
    return b'"Table":[]' in body or len(body) < 200


def subcat_page_is_last(body: bytes) -> bool:
    """BseSubcategoryAnnouncementsIngester.fetch's stop rule, verbatim."""
    return b'"Table":[]' in body or b'"Table": []' in body or len(body) < 200


_OPENER = urllib.request.build_opener()


def configure_proxy(proxy_url: str | None) -> str:
    """Route every request through proxy_url. Returns a MASKED description only."""
    global _OPENER
    if not proxy_url:
        _OPENER = urllib.request.build_opener()
        return "none (direct)"
    parts = urlsplit(proxy_url.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise SystemExit("proxy URL must look like http://USER:PASS@HOST:PORT")
    _OPENER = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": proxy_url.strip(), "https": proxy_url.strip()}))
    return f"{parts.scheme}://***@{parts.hostname}:{parts.port or '-'}"


def read_proxy(proxy_file: Path | None) -> str | None:
    if proxy_file:
        return proxy_file.read_text().strip().splitlines()[0].strip() or None
    return os.environ.get("BSE_PROXY_URL", "").strip() or None


def egress_ip() -> str:
    try:
        with _OPENER.open("https://api.ipify.org", timeout=30) as r:
            return r.read().decode().strip()
    except Exception as e:                                        # noqa: BLE001 — diagnostic only
        return f"unknown ({type(e).__name__})"


class Blocked(Exception):
    """HTTP 403 — this network is blocked as well. Never retry."""


def _decode(raw: bytes, encoding: str) -> bytes:
    enc = (encoding or "").lower()
    if enc == "gzip":
        return gzip.decompress(raw)
    if enc == "deflate":
        try:
            return zlib.decompress(raw)
        except zlib.error:
            return zlib.decompress(raw, -zlib.MAX_WBITS)
    return raw


def get(url: str, delay: float, tries: int = 4) -> tuple[bytes, int]:
    """GET with production's headers. Retries 429/5xx/network errors with backoff."""
    last_err: Exception | None = None
    for attempt in range(tries):
        time.sleep(delay if attempt == 0 else delay * (2 ** attempt))
        req = urllib.request.Request(url, headers=HEADERS)
        try:
            with _OPENER.open(req, timeout=60) as r:
                return _decode(r.read(), r.headers.get("Content-Encoding", "")), r.status
        except urllib.error.HTTPError as e:
            if e.code == 403:
                raise Blocked(url) from e
            if e.code in (429, 500, 502, 503, 504):
                last_err = e
                continue
            raise
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last_err = e
    raise RuntimeError(f"gave up after {tries} tries: {url}: {last_err}")


def fetch_coarse(d: str, delay: float) -> tuple[list[bytes], str, int]:
    pages, url, status = [], "", 0
    for page in range(1, COARSE_MAX_PAGES + 1):
        url = coarse_url(d, page)
        body, status = get(url, delay)
        pages.append(body)
        if coarse_page_is_last(body):
            break
    return pages, url, status


def fetch_subcat(d: str, delay: float) -> tuple[list[bytes], str, int]:
    # Production skips a failing slice and keeps the rest. For history that would
    # save a silently incomplete day, so here any failure fails the whole day and
    # the next run retries it.
    pages, url, status = [], "", 0
    for cat in CATEGORIES:
        for page in range(1, SUBCAT_MAX_PAGES + 1):
            url = subcat_url(cat, "", d, page)
            body, status = get(url, delay)
            pages.append(body)
            if subcat_page_is_last(body):
                break
    return pages, url, status


def _rows(pages: list[bytes]) -> int:
    n = 0
    for p in pages:
        try:
            n += len(json.loads(p).get("Table") or [])
        except (ValueError, AttributeError):
            pass
    return n


def save_day(out: Path, kind: str, day: date, pages: list[bytes], url: str, status: int) -> dict:
    d = out / kind
    d.mkdir(parents=True, exist_ok=True)
    body = RECORD_SEP.join(pages)
    meta = {
        "date": day.isoformat(), "kind": kind, "pages": len(pages), "rows": _rows(pages),
        "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(),
        "last_url": url, "last_status": status,
        "fetched_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "fetcher_version": FETCHER_VERSION,
    }
    tmp_bin, tmp_json = d / f".{day}.bin.tmp", d / f".{day}.json.tmp"
    tmp_bin.write_bytes(body)
    tmp_json.write_text(json.dumps(meta, indent=1))
    tmp_bin.replace(d / f"{day}.bin")             # .json last: its presence marks "complete"
    tmp_json.replace(d / f"{day}.json")
    return meta


def write_manifest(out: Path) -> int:
    files = []
    for kind in ("coarse", "subcat"):
        for j in sorted((out / kind).glob("*.json")) if (out / kind).exists() else []:
            files.append(json.loads(j.read_text()))
    (out / "manifest.json").write_text(json.dumps(
        {"fetcher_version": FETCHER_VERSION, "files": files}, indent=1))
    return len(files)


def shard_of(days: list, index: int, count: int) -> list:
    """Every day lands in exactly one shard. Cloud Run sets CLOUD_RUN_TASK_INDEX /
    CLOUD_RUN_TASK_COUNT, so parallel tasks split the range with no coordination."""
    if count < 1 or not (0 <= index < count):
        raise SystemExit(f"bad shard {index}/{count}")
    return [d for i, d in enumerate(days) if i % count == index]


def self_test(delay: float, via_proxy: bool = False) -> int:
    print(f"self-test: egress IP {egress_ip()} — one historical page from each endpoint (2024-06-03)")
    try:
        b1, s1 = get(coarse_url("20240603", 1), delay, tries=2)
        print(f"  coarse  AnnGetData            HTTP {s1}  {len(b1):>8,} bytes  {_rows([b1])} rows")
        b2, s2 = get(subcat_url("Company Update", "", "20240603", 1), delay, tries=2)
        print(f"  subcat  AnnSubCategoryGetData HTTP {s2}  {len(b2):>8,} bytes  {_rows([b2])} rows")
    except RuntimeError as e:
        # Connection-level failure, not a BSE answer: most often the proxy itself is
        # unreachable, refuses the credentials, or does not support HTTPS CONNECT.
        where = "the PROXY (host/port/credentials/CONNECT support)" if via_proxy else "the network"
        print(f"\n  Could not reach BSE at all — check {where}.\n  detail: {str(e)[:160]}")
        return 3
    except Blocked:
        if via_proxy:
            print("\n  HTTP 403 THROUGH THE PROXY — its exit IPs are blocked too. Datacenter "
                  "proxies will not work; use residential exits, ideally India-geolocated.")
        else:
            print("\n  HTTP 403 — this network is ALSO blocked by BSE. Try another network "
                  "(home broadband, mobile hotspot); cloud VMs will not work.")
        return 2
    if not (_rows([b1]) and _rows([b2])):
        print("\n  Reached BSE but got no rows. Paste the output above back — do not run the full fetch yet.")
        return 1
    print("\n  OK — this network can reach BSE history. Run the full fetch.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Fetch BSE announcement history (run OFF cloud networks).")
    ap.add_argument("--self-test", action="store_true", help="check this network can reach BSE, then exit")
    ap.add_argument("--from", dest="since", type=date.fromisoformat)
    ap.add_argument("--to", dest="until", type=date.fromisoformat)
    ap.add_argument("--out", type=Path, default=Path("bse_history"))
    ap.add_argument("--kinds", default="coarse,subcat", help="coarse,subcat (default both)")
    ap.add_argument("--delay", type=float, default=1.0, help="seconds between requests (default 1.0)")
    ap.add_argument("--proxy-file", type=Path,
                    help="file whose first line is the proxy URL (else env BSE_PROXY_URL; never argv)")
    return ap


def main() -> int:
    ap = build_parser()
    a = ap.parse_args()
    proxy_url = read_proxy(a.proxy_file)
    print(f"proxy: {configure_proxy(proxy_url)}")

    if a.self_test:
        return self_test(a.delay, via_proxy=bool(proxy_url))
    if not (a.since and a.until) or a.since > a.until:
        ap.error("--from and --to are required, with --from <= --to")

    kinds = [k.strip() for k in a.kinds.split(",") if k.strip()]
    fetchers = {"coarse": fetch_coarse, "subcat": fetch_subcat}
    days = [a.since + timedelta(n) for n in range((a.until - a.since).days + 1)]
    t_idx = int(os.environ.get("CLOUD_RUN_TASK_INDEX", "0"))
    t_cnt = int(os.environ.get("CLOUD_RUN_TASK_COUNT", "1"))
    days = shard_of(days, t_idx, t_cnt)
    if t_cnt > 1:
        print(f"shard {t_idx + 1}/{t_cnt}: {len(days)} days")
    todo = [(k, d) for d in days for k in kinds
            if not ((a.out / k / f"{d}.bin").exists() and (a.out / k / f"{d}.json").exists())]
    print(f"{len(days)} days x {len(kinds)} kinds; {len(todo)} to fetch, "
          f"{len(days) * len(kinds) - len(todo)} already done -> {a.out.resolve()}")

    done = failed = 0
    started = time.time()
    for i, (kind, day) in enumerate(todo, 1):
        try:
            pages, url, status = fetchers[kind](day.strftime("%Y%m%d"), a.delay)
            meta = save_day(a.out, kind, day, pages, url, status)
            done += 1
            eta = (time.time() - started) / i * (len(todo) - i) / 3600
            print(f"[{i}/{len(todo)}] {day} {kind:6s} {meta['pages']:3d} pages "
                  f"{meta['rows']:5d} rows   ETA {eta:.1f}h", flush=True)
        except Blocked as e:
            print(f"\nHTTP 403 on {e}\nThis network is blocked by BSE too. Stopping; "
                  f"{done} days saved and will be skipped on the next run.")
            write_manifest(a.out)
            return 2
        except Exception as e:                                   # noqa: BLE001 — retried next run
            failed += 1
            print(f"[{i}/{len(todo)}] {day} {kind:6s} FAILED ({type(e).__name__}: {e}) — will retry next run",
                  flush=True)
    n = write_manifest(a.out)
    print(f"\nDONE: {done} saved, {failed} failed, manifest lists {n} files. "
          f"{'Re-run the same command to retry failures. ' if failed else ''}"
          f"Then copy the whole '{a.out}' folder to nidp-stack-vm.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
