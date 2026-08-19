"""nidp-fpi-sector-auc service.

Publishes fortnightly FPI sector-wise AUC and net investment.

Why NSDL and not NSE: this dataset has no NSE equivalent — sector-level FPI
custody is reported by the depository, not the exchange. It is also reachable
when NSE is not (NSDL is a plain WebForms host with no Akamai edge), which is
why nidp.shared.sources.nsdl_fetcher exists.

Cadence: NSDL publishes on the 15th/16th and the 1st/2nd of each month, for the
fortnight just ended. Running daily is harmless — the discovery step only fetches
reports whose fortnight end is newer than what the table already holds.
"""
from __future__ import annotations

import logging
import uuid
from datetime import date
from typing import Optional

from nidp.shared.ingester_base import BaseIngester
from nidp.shared.metrics import SOURCE_FETCH, time_fetch
from nidp.shared.sources.nsdl_fetcher import fetch_bytes as nsdl_fetch_bytes
from nidp.shared.storage.job_log import JobRun
from nidp.shared.storage.pg import get_pool

from .parser import parse_fortnight_index, parse_sector_report
from .writer import SOURCE_NAME, upsert_fpi_sector_auc

INDEX_URL = ("https://www.fpi.nsdl.co.in/web/Reports/"
             "FPI_Fortnightly_Selection.aspx")

logger = logging.getLogger(__name__)


class FpiSectorAucIngester(BaseIngester):
    SERVICE_NAME = "fpi_sector_auc"
    SOURCE_NAME = SOURCE_NAME
    KAFKA_TOPIC = "nidp.fpi_sector_auc.v1"
    AVRO_SCHEMA = "fpi_sector_auc_v1"

    # How many fortnights back to consider on a normal run. 8 ≈ 4 months, which
    # comfortably re-covers anything NSDL revised without re-fetching 14 years.
    lookback: int = 8
    # Set by fetch(); parse() needs the per-report URL for provenance.
    _reports: list[tuple[date, str]]
    _bodies: list[tuple[date, str, bytes]]

    def __init__(self, lookback: Optional[int] = None,
                 since: Optional[date] = None) -> None:
        super().__init__()
        if lookback is not None:
            self.lookback = lookback
        self.since = since
        self._reports = []
        self._bodies = []

    async def _already_loaded(self) -> set[date]:
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT DISTINCT report_date FROM nidp.fpi_sector_auc "
                "WHERE source = $1", SOURCE_NAME)
        return {r["report_date"] for r in rows}

    async def fetch(self, target_date: Optional[date]) -> tuple[bytes, str, int]:
        """Fetch the index, then every report we still need.

        Returns the index body so BaseIngester's content guard has something to
        inspect; the per-report bodies are carried on self._bodies.
        """
        with time_fetch(self.SOURCE_NAME):
            index_body, status = await nsdl_fetch_bytes(INDEX_URL)
            SOURCE_FETCH.labels(source=self.SOURCE_NAME,
                                status=str(status)).inc()

        self._reports = parse_fortnight_index(index_body)
        if not self._reports:
            logger.warning("fpi_sector_auc: index yielded no reports")
            return index_body, INDEX_URL, status

        have = await self._already_loaded()
        wanted = [(d, u) for d, u in self._reports
                  if (self.since is None or d >= self.since)]
        if self.since is None:
            wanted = wanted[:self.lookback]
        # A fortnight already in the table is re-fetched only if it is one of the
        # two most recent — those are the ones NSDL still revises.
        fresh = {d for d, _ in self._reports[:2]}
        todo = [(d, u) for d, u in wanted if d not in have or d in fresh]

        logger.info("fpi_sector_auc: %d report(s) in index, %d to fetch",
                    len(self._reports), len(todo))
        self._bodies = []
        for d, url in todo:
            try:
                body, st = await nsdl_fetch_bytes(url, referer=INDEX_URL)
                SOURCE_FETCH.labels(source=self.SOURCE_NAME, status=str(st)).inc()
                self._bodies.append((d, url, body))
            except Exception:  # noqa: BLE001
                # One bad fortnight must not sink the run — NSDL's older files
                # occasionally 404 behind a renamed path.
                SOURCE_FETCH.labels(source=self.SOURCE_NAME, status="error").inc()
                logger.exception("fpi_sector_auc: report fetch failed for %s", d)
        return index_body, INDEX_URL, status

    def parse(self, body: bytes, target_date: Optional[date]) -> list[dict]:
        rows: list[dict] = []
        for _d, url, report_body in self._bodies:
            rows.extend(parse_sector_report(report_body, url))
        return rows

    def validate(self, rows: list[dict]) -> tuple[list[dict], int]:
        kept, dropped = [], 0
        for r in rows:
            if not (r.get("report_date") and r.get("sector")
                    and r.get("asset_class")):
                dropped += 1
                continue
            kept.append(r)
        return kept, dropped

    async def persist(self, rows: list[dict], run: JobRun) -> int:
        return await upsert_fpi_sector_auc(rows, run.run_id)


async def run(target_date: Optional[date] = None,
              lookback: Optional[int] = None,
              since: Optional[date] = None) -> uuid.UUID:
    job = await FpiSectorAucIngester(lookback=lookback, since=since).run(
        target_date)
    return job.run_id
