"""nidp-sebi-circulars ingester.

Reads SEBI's public pages and upserts circulars and master circulars by URL:

    rss      https://www.sebi.gov.in/sebirss.xml — the scheduled run (cron, every 3 h Mon-Sat).
             The feed holds about the latest 30 items of every kind, so a circular is caught
             only while it is still among them; the 3-hourly poll is what keeps that window.
    listing  page 1 of Legal > Circulars and Legal > Master Circulars (the 25 newest of each)
             — the backfill, `python -m nidp.services.sebi_circulars --source listing`.
             Later pages are a JavaScript form post, so there is no deeper backfill.

Everything outside /legal/circulars/ and /legal/master-circulars/ (enforcement orders, recovery
notices naming individuals with their PAN, press releases) is dropped and never stored: fetch()
hands BaseIngester a redacted copy of the feed (parser.redact_rss), so the raw archive holds only
the channel header and the circular items, and the parser keeps only those. A fetched feed with
no circulars in it is a SKIPPED run ("no rows in source"); a body that is not the RSS feed, an
HTTP error or an empty body fails the run.
"""
from __future__ import annotations

import logging
import uuid
from datetime import date
from typing import Callable, Optional

import aiohttp

from nidp.shared.config import HTTP_TIMEOUT_S
from nidp.shared.ingester_base import BaseIngester
from nidp.shared.metrics import SOURCE_FETCH, time_fetch
from nidp.shared.storage.job_log import JobRun

from .parser import SEBI_WWW, parse_listing, parse_rss, redact_rss
from .writer import SOURCE_NAME, upsert_circulars

logger = logging.getLogger(__name__)

SEBI_RSS_URL = f"{SEBI_WWW}/sebirss.xml"
SEBI_LISTING_URLS: dict[str, str] = {
    "circular":        f"{SEBI_WWW}/sebiweb/home/HomeAction.do?doListing=yes&sid=1&ssid=7&smid=0",
    "master_circular": f"{SEBI_WWW}/sebiweb/home/HomeAction.do?doListing=yes&sid=1&ssid=6&smid=0",
}
# Says who is asking. robots.txt (2026-10-14) disallows only /js and /css.
USER_AGENT = "Mozilla/5.0 (compatible; NiveshNIDP/1.0; research feed reader)"

SOURCES = ("rss", "listing", "all")


class SebiCircularsIngester(BaseIngester):
    """One page per run: the RSS feed, or one listing page."""

    SERVICE_NAME = "sebi_circulars"
    SOURCE_NAME = SOURCE_NAME
    KAFKA_TOPIC = "nidp.sebi_circulars.v1"
    AVRO_SCHEMA = ""   # no per-row stream; the table is read by DaaS only

    def __init__(self, url: str = SEBI_RSS_URL,
                 parser: Callable[[bytes], list[dict]] = parse_rss,
                 accept: str = "application/rss+xml, application/xml, text/xml",
                 redact: Optional[Callable[[bytes], bytes]] = redact_rss) -> None:
        self.url = url
        self._parser = parser
        self._accept = accept
        # Applied to the fetched bytes before BaseIngester archives them (raw_archive): the RSS
        # feed's recovery notices carry names and PANs, which must never be stored anywhere.
        self._redact = redact

    async def fetch(self, target_date: Optional[date]) -> tuple[bytes, str, int]:
        timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT_S)
        headers = {"User-Agent": USER_AGENT, "Accept": self._accept}
        with time_fetch(self.SOURCE_NAME):
            try:
                async with aiohttp.ClientSession(timeout=timeout, headers=headers) as s:
                    async with s.get(self.url) as resp:
                        body = await resp.read()
                        SOURCE_FETCH.labels(
                            source=self.SOURCE_NAME, status=str(resp.status),
                        ).inc()
                        # Fail loud: a SKIPPED run must only ever mean "read fine, no circular in it".
                        if resp.status != 200:
                            raise RuntimeError(f"SEBI answered HTTP {resp.status} for {self.url}")
                        if not body.strip():
                            raise RuntimeError(f"SEBI answered an empty body for {self.url}")
                        if self._redact is not None:
                            body = self._redact(body)   # SebiFeedError (not RSS) fails the run here, unarchived
                        return body, self.url, resp.status
            except Exception:
                SOURCE_FETCH.labels(source=self.SOURCE_NAME, status="error").inc()
                raise

    def parse(self, body: bytes, target_date: Optional[date]) -> list[dict]:
        rows = self._parser(body)
        logger.info("sebi_circulars parsed %d rows from %s", len(rows), self.url)
        return rows

    async def persist(self, rows: list[dict], run: JobRun) -> int:
        return await upsert_circulars(rows, run.run_id)


def ingesters_for(source: str) -> list[SebiCircularsIngester]:
    if source not in SOURCES:
        raise ValueError(f"source must be one of {SOURCES}, not {source!r}")
    out: list[SebiCircularsIngester] = []
    if source in ("rss", "all"):
        out.append(SebiCircularsIngester())
    if source in ("listing", "all"):
        out.extend(
            SebiCircularsIngester(url, parse_listing, "text/html", redact=None)   # circulars only; nothing personal
            for url in SEBI_LISTING_URLS.values()
        )
    return out


async def run(target_date: Optional[date] = None, source: str = "rss") -> uuid.UUID:
    """Runs each page's ingester in turn; returns the last run's id. target_date is accepted
    for the CLI's sake and ignored: both sources only ever show the newest items."""
    jobs = [await ing.run(None) for ing in ingesters_for(source)]
    return jobs[-1].run_id
