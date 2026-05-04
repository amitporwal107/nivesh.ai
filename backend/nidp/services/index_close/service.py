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
from nidp.shared.storage.job_log import JobRun

from .parser import parse_index_close
from .writer import SOURCE_NAME, upsert_index_close

logger = logging.getLogger(__name__)


class IndexCloseIngester(BaseIngester):
    SERVICE_NAME = "index_close"
    SOURCE_NAME = SOURCE_NAME
    KAFKA_TOPIC = "nidp.index_close.v1"
    AVRO_SCHEMA = "index_close_v1"

    async def fetch(self, target_date: Optional[date]) -> tuple[bytes, str, int]:
        if target_date is None:
            raise ValueError("index_close requires --date")
        url = fmt_url(INDEX_CLOSE_URL, target_date)
        with time_fetch(self.SOURCE_NAME):
            try:
                body, status = await fetch_bytes(url, referer=f"{NSE_WWW}/all-reports-indices")
                SOURCE_FETCH.labels(source=self.SOURCE_NAME, status=str(status)).inc()
                return body, url, status
            except Exception:
                SOURCE_FETCH.labels(source=self.SOURCE_NAME, status="error").inc()
                raise

    def parse(self, body: bytes, target_date: Optional[date]) -> list[dict]:
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
