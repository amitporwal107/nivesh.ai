"""nidp-index-close service."""
from __future__ import annotations

import logging
import uuid
from datetime import date
from typing import Optional

from nidp.shared.bus import get_bus
from nidp.shared.config import INDEX_CLOSE_URL, NSE_WWW, fmt_url
from nidp.shared.ingester_base import BaseIngester
from nidp.shared.metrics import SOURCE_FETCH, time_fetch
from nidp.shared.sources.nse_fetcher import fetch_bytes
from nidp.shared.write_target import upsert_target_problem
from nidp.shared.storage.job_log import JobRun

from .parser import parse_index_close
from .writer import SOURCE_NAME, upsert_index_close

logger = logging.getLogger(__name__)


class IndexCloseIngester(BaseIngester):
    SERVICE_NAME = "index_close"
    SOURCE_NAME = SOURCE_NAME
    KAFKA_TOPIC = "nidp.index_close.v1"
    AVRO_SCHEMA = "index_close_v1"

    # nidp.index_eod / nidp.mf_nav_daily are pass-through VIEWS over FDW
    # foreign tables in some environments, which no upsert can target.
    # Detect it up front and skip with a real reason instead of failing
    # identically forever. See nidp/shared/write_target.py.
    _write_target = "nidp.index_eod"
    _target_problem = None

    async def _check_write_target(self) -> bool:
        self._target_problem = await upsert_target_problem(self._write_target)
        if self._target_problem:
            logger.warning("%s: %s", self.SERVICE_NAME, self._target_problem)
            return False
        return True

    async def fetch(self, target_date: Optional[date]) -> tuple[bytes, str, int]:
        if not await self._check_write_target():
            return b"", self._write_target, 200
        if target_date is None:
            raise ValueError("index_close requires --date")
        url = fmt_url(INDEX_CLOSE_URL, target_date)
        with time_fetch(self.SOURCE_NAME):
            try:
                body, status = await fetch_bytes(
                    url,
                    referer=f"{NSE_WWW}/all-reports-indices",
                    archive_as=("index_close", target_date, url.rsplit("/", 1)[-1]),
                )
                SOURCE_FETCH.labels(source=self.SOURCE_NAME, status=str(status)).inc()
                return body, url, status
            except Exception:
                SOURCE_FETCH.labels(source=self.SOURCE_NAME, status="error").inc()
                raise

    def parse(self, body: bytes, target_date: Optional[date]) -> list[dict]:
        if self._target_problem:
            return []
        return parse_index_close(body)

    def validate(self, rows: list[dict]) -> tuple[list[dict], int]:
        kept, dropped = [], 0
        for r in rows:
            if not r["index_name"] or not r["as_of_date"]:
                dropped += 1
                continue
            if r.get("close_price") is None:
                dropped += 1
                continue
            kept.append(r)
        return kept, dropped

    async def persist(self, rows: list[dict], run: JobRun) -> int:
        inserted = await upsert_index_close(rows, run.run_id)
        bus = get_bus()
        for r in rows:
            payload = {**r, "source": self.SOURCE_NAME, "source_run_id": str(run.run_id)}
            await bus.publish(
                self.KAFKA_TOPIC,
                key=f"{r['as_of_date']}|{r['index_name']}",
                value=payload,
                schema_name=self.AVRO_SCHEMA,
            )
        return inserted


async def run(target_date: date) -> uuid.UUID:
    job = await IndexCloseIngester().run(target_date)
    return job.run_id
