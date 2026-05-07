"""nidp-corporate-announcements ingesters (NSE + BSE).

Two BaseIngester subclasses share the same destination table
(nidp.corporate_announcements) and are differentiated by SOURCE_NAME +
SERVICE_NAME. Each is invoked independently by Cloud Scheduler.

Classification (event_category / impact_score / sentiment) is filled
asynchronously by the announcement_classifier service. This module
ingests only the raw feed.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from nidp.shared.config import NSE_WWW
from nidp.shared.ingester_base import BaseIngester
from nidp.shared.metrics import SOURCE_FETCH, time_fetch
from nidp.shared.sources.nse_fetcher import fetch_bytes
from nidp.shared.storage.job_log import JobRun

from .parser import parse_nse_announcements
from .parser_bse import parse_bse_announcements
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


async def run_once(source: str, target_date: Optional[date] = None) -> JobRun:
    if source == "nse":
        ing = NseAnnouncementsIngester()
    elif source == "bse":
        ing = BseAnnouncementsIngester()
    else:
        raise ValueError(f"unknown source: {source!r} (expected 'nse' or 'bse')")
    return await ing.run(target_date=target_date)
