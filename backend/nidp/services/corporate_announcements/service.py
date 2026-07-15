"""nidp-corporate-announcements ingesters (NSE + BSE).

Two BaseIngester subclasses share the same destination table
(nidp.corporate_announcements) and are differentiated by SOURCE_NAME +
SERVICE_NAME. Each is invoked independently by Cloud Scheduler.

Classification (event_category / impact_score / sentiment) is filled
asynchronously by the announcement_classifier service. This module
ingests only the raw feed.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import Optional
from urllib.parse import urlencode

from nidp.shared.config import NSE_WWW
from nidp.shared.ingester_base import BaseIngester
from nidp.shared.metrics import SOURCE_FETCH, time_fetch
from nidp.shared.sources.nse_fetcher import fetch_bytes
from nidp.shared.storage.job_log import JobRun

from .parser import parse_nse_announcements
from .parser_bse import parse_bse_announcements
from .taxonomy import iter_slices
from .validators import validate_rows
from .writer import upsert_announcements

logger = logging.getLogger(__name__)

_NSE_ANN_URL_TMPL = (
    NSE_WWW + "/api/corporate-announcements"
    "?index=equities&from_date={d}&to_date={d}"
)
_BSE_ANN_URL_TMPL = (
    "https://api.bseindia.com/BseIndiaAPI/api/AnnGetData/w"
    "?pageno={page}&strCat=-1&strPrevDate={d}&strToDate={d}"
    "&strScrip=&strSearch=P&strType=C&subcategory=-1"
)
_BSE_PAGE_SIZE = 50
_BSE_MAX_PAGES = 20  # safety cap — typical day = 200–800 announcements

# Subcategory sweep (adopted from the BSE Announcements API suite). Uses a
# DIFFERENT endpoint that accepts a `subcategory` filter, letting us capture
# SUBCATNAME (transcripts, presentations, order-wins, M&A) the coarse strCat=-1
# sweep can't. Category/subcategory strings come from taxonomy.py.
_BSE_SUBCAT_URL = "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
_BSE_SUBCAT_MAX_PAGES = 10       # subcategory slices are narrow — few pages each
_BSE_SUBCAT_THROTTLE_S = 1.0     # ≥1 req/sec — be a polite guest (suite caveat 2)


def _bse_subcat_url(category: str, subcategory: str, d: str, page: int) -> str:
    """Build a URL-encoded AnnSubCategoryGetData/w request (category/subcategory
    strings contain spaces + '/', so they MUST be encoded)."""
    return _BSE_SUBCAT_URL + "?" + urlencode({
        "pageno": page,
        "strCat": category,
        "strPrevDate": d,
        "strToDate": d,
        "strscrip": "",
        "strSearch": "P",
        "strType": "C",
        "subcategory": subcategory or "-1",
    })


class NseAnnouncementsIngester(BaseIngester):
    SERVICE_NAME = "corporate_announcements_nse"
    SOURCE_NAME = "NSE_ANN"
    KAFKA_TOPIC = "nidp.corporate_announcements.v1"
    AVRO_SCHEMA = ""

    async def fetch(self, target_date: Optional[date]) -> tuple[bytes, str, int]:
        d = (target_date or date.today()).strftime("%d-%m-%Y")
        url = _NSE_ANN_URL_TMPL.format(d=d)
        with time_fetch(self.SOURCE_NAME):
            try:
                body, status = await fetch_bytes(url, referer=NSE_WWW + "/")
                SOURCE_FETCH.labels(source=self.SOURCE_NAME, status=str(status)).inc()
                return body, url, status
            except Exception:
                SOURCE_FETCH.labels(source=self.SOURCE_NAME, status="error").inc()
                raise

    def parse(self, body: bytes, target_date: Optional[date]) -> list[dict]:
        return parse_nse_announcements(body)

    def validate(self, rows: list[dict]) -> tuple[list[dict], int]:
        return validate_rows(rows)

    async def persist(self, rows: list[dict], run: JobRun) -> int:
        return await upsert_announcements(rows, run.run_id)


class BseAnnouncementsIngester(BaseIngester):
    SERVICE_NAME = "corporate_announcements_bse"
    SOURCE_NAME = "BSE_ANN"
    KAFKA_TOPIC = "nidp.corporate_announcements.v1"
    AVRO_SCHEMA = ""

    async def fetch(self, target_date: Optional[date]) -> tuple[bytes, str, int]:
        d = (target_date or date.today()).strftime("%Y%m%d")
        # BaseIngester archives the body of fetch() once, so we paginate
        # in-memory and concatenate into a synthetic bytes payload that
        # parse() will split. Each page is its own JSON document.
        all_pages: list[bytes] = []
        last_status = 0
        last_url = ""
        for page in range(1, _BSE_MAX_PAGES + 1):
            url = _BSE_ANN_URL_TMPL.format(d=d, page=page)
            last_url = url
            with time_fetch(self.SOURCE_NAME):
                try:
                    body, status = await fetch_bytes(
                        url, referer="https://www.bseindia.com/corporates/ann.html",
                    )
                    last_status = status
                    SOURCE_FETCH.labels(source=self.SOURCE_NAME, status=str(status)).inc()
                except Exception:
                    SOURCE_FETCH.labels(source=self.SOURCE_NAME, status="error").inc()
                    raise
            all_pages.append(body)
            # Cheap heuristic: page is "done" when row count looks short.
            # We let parse() decide truth; this just stops the fetch loop.
            if b'"Table":[]' in body or len(body) < 200:
                break
        # \x1e (record separator) joins pages — parser splits on it.
        joined = b"\x1e".join(all_pages)
        return joined, last_url, last_status

    def parse(self, body: bytes, target_date: Optional[date]) -> list[dict]:
        rows: list[dict] = []
        for page in body.split(b"\x1e"):
            if page:
                rows.extend(parse_bse_announcements(page))
        # BSE pagination can return overlapping rows on day boundaries;
        # de-dupe by announcement_id within a single run.
        seen: set[str] = set()
        out: list[dict] = []
        for r in rows:
            if r["announcement_id"] in seen:
                continue
            seen.add(r["announcement_id"])
            out.append(r)
        return out

    def validate(self, rows: list[dict]) -> tuple[list[dict], int]:
        return validate_rows(rows)

    async def persist(self, rows: list[dict], run: JobRun) -> int:
        return await upsert_announcements(rows, run.run_id)


class BseSubcategoryAnnouncementsIngester(BaseIngester):
    """Full BSE taxonomy sweep (category × subcategory) via AnnSubCategoryGetData/w.

    Adopted from the BSE Announcements API suite. Writes to the same table + source
    as the coarse strCat=-1 sweep (announcement_id dedupe makes them idempotent),
    but ALSO captures SUBCATNAME → subcategory, which the coarse sweep can't — this
    is what lets the document_parser tag concall transcripts / investor
    presentations as first-class corpus docs.

    ADDITIVE + graceful: the coarse `BseAnnouncementsIngester` is untouched, so a
    bad/blocked/renamed subcategory endpoint can never break the working feed. Each
    slice is fetched defensively; a failing slice is logged and skipped.

    ⚠️ The AnnSubCategoryGetData/w endpoint + SUBCATNAME field are UNVERIFIED from
    the build env (suite README caveat 1). Verify live on the VM (ann.html Network
    tab) — expect to adjust taxonomy.py strings and/or the field names.
    """

    SERVICE_NAME = "corporate_announcements_bse_subcat"
    SOURCE_NAME = "BSE_ANN"
    KAFKA_TOPIC = "nidp.corporate_announcements.v1"
    AVRO_SCHEMA = ""

    async def fetch(self, target_date: Optional[date]) -> tuple[bytes, str, int]:
        d = (target_date or date.today()).strftime("%Y%m%d")
        all_pages: list[bytes] = []
        last_status = 0
        last_url = ""
        for category, sub in iter_slices():
            for page in range(1, _BSE_SUBCAT_MAX_PAGES + 1):
                url = _bse_subcat_url(category, sub, d, page)
                last_url = url
                try:
                    with time_fetch(self.SOURCE_NAME):
                        body, status = await fetch_bytes(
                            url, referer="https://www.bseindia.com/corporates/ann.html",
                        )
                    last_status = status
                    SOURCE_FETCH.labels(source=self.SOURCE_NAME, status=str(status)).inc()
                except Exception as e:  # noqa: BLE001 — one slice/page must not abort the sweep
                    SOURCE_FETCH.labels(source=self.SOURCE_NAME, status="error").inc()
                    logger.warning("BSE subcat %s / %s p%d failed: %s", category, sub, page, e)
                    break  # give up this slice, continue the sweep
                all_pages.append(body)
                # Stop this slice when a short/empty page comes back.
                if b'"Table":[]' in body or b'"Table": []' in body or len(body) < 200:
                    break
                await asyncio.sleep(_BSE_SUBCAT_THROTTLE_S)
        if not all_pages:
            # Endpoint down/blocked for every slice → fail loudly (job marked failed
            # + alerted) rather than silently writing zero rows.
            raise RuntimeError(
                f"BSE subcategory sweep fetched no pages (last={last_url}, status={last_status})"
            )
        return b"\x1e".join(all_pages), last_url, last_status

    def parse(self, body: bytes, target_date: Optional[date]) -> list[dict]:
        rows: list[dict] = []
        for page in body.split(b"\x1e"):
            if page:
                rows.extend(parse_bse_announcements(page))
        seen: set[str] = set()
        out: list[dict] = []
        for r in rows:
            if r["announcement_id"] in seen:
                continue
            seen.add(r["announcement_id"])
            out.append(r)
        return out

    def validate(self, rows: list[dict]) -> tuple[list[dict], int]:
        return validate_rows(rows)

    async def persist(self, rows: list[dict], run: JobRun) -> int:
        return await upsert_announcements(rows, run.run_id)


async def run_once(source: str, target_date: Optional[date] = None) -> JobRun:
    if source == "nse":
        ing = NseAnnouncementsIngester()
    elif source == "bse":
        ing = BseAnnouncementsIngester()
    elif source == "bse_subcat":
        ing = BseSubcategoryAnnouncementsIngester()
    else:
        raise ValueError(f"unknown source: {source!r} (expected 'nse', 'bse', or 'bse_subcat')")
    return await ing.run(target_date=target_date)


async def run(target_date: Optional[date] = None) -> None:
    """Daily batch — NSE + coarse BSE (strCat=-1) + full BSE subcategory sweep.

    The coarse BSE sweep guarantees breadth (catches filings whose subcategory
    isn't in taxonomy.py yet); the subcategory sweep adds SUBCATNAME granularity
    on top. Each is independent so one failing doesn't lose the others.
    """
    for source in ("nse", "bse", "bse_subcat"):
        try:
            await run_once(source, target_date)
        except Exception as e:
            logger.error("corporate_announcements: daily %s failed: %s", source, e)


async def run_intraday(target_date: Optional[date] = None) -> dict:
    """1-min intraday poll: market hours guard → ingest NSE → classify new rows.

    Design:
    - Exits immediately outside 08:30–16:30 IST (cost = one Cloud Run cold start, ~$0)
    - NSE-only during intraday (BSE API is less real-time; run BSE in daily batch)
    - Immediately triggers announcement_classifier on any new rows so event
      intelligence latency is < 2 min from filing to classified signal
    - Writer uses ON CONFLICT DO NOTHING so 1-min re-runs are fully safe
    """
    from nidp.shared.market_hours import is_intraday_window
    if not is_intraday_window():
        logger.debug("corporate_announcements: outside intraday window — exiting")
        return {"skipped": "outside_market_hours"}

    stats: dict = {}

    # NSE only for intraday (fast JSON endpoint)
    try:
        job = await run_once("nse", target_date)
        stats["nse"] = {"status": job.status, "rows": getattr(job, "rows_inserted", 0)}
    except Exception as e:
        logger.error("corporate_announcements: intraday NSE failed: %s", e)
        stats["nse"] = {"error": str(e)}

    # Immediately classify any new unclassified rows (keeps latency < 2 min)
    try:
        from nidp.services.announcement_classifier.service import run_once as classify
        clf = await classify(limit=100)
        stats["classifier"] = clf
        if clf.get("processed", 0) > 0:
            logger.info(
                "corporate_announcements: intraday classified %d new announcements",
                clf["processed"],
            )
    except Exception as e:
        logger.warning("corporate_announcements: intraday classifier failed: %s", e)
        stats["classifier"] = {"error": str(e)}

    return stats
