"""nidp-block-deals service."""
from __future__ import annotations

import logging
import uuid
from datetime import date
from typing import Optional

from nidp.shared.bus import get_bus
from nidp.shared.config import BLOCK_DEALS_URL, NSE_WWW
from nidp.shared.ingester_base import BaseIngester
from nidp.shared.metrics import SOURCE_FETCH, time_fetch
from nidp.shared.sources.nse_fetcher import fetch_bytes
from nidp.shared.storage.job_log import JobRun

from .parser import parse_block_deals
from .writer import SOURCE_NAME, upsert_block_deals

logger = logging.getLogger(__name__)


class BlockDealsIngester(BaseIngester):
    SERVICE_NAME = "block_deals"
    SOURCE_NAME = SOURCE_NAME
    KAFKA_TOPIC = "nidp.block_deals.v1"
    AVRO_SCHEMA = "block_deals_v1"

    async def fetch(self, target_date: Optional[date]) -> tuple[bytes, str, int]:
        url = BLOCK_DEALS_URL
        with time_fetch(self.SOURCE_NAME):
            try:
                body, status = await fetch_bytes(
                    url, referer=f"{NSE_WWW}/report-detail/display-bulk-and-block-deals",
                    archive_as=("block_deals", target_date, url.rsplit("/", 1)[-1]),
                )
                SOURCE_FETCH.labels(source=self.SOURCE_NAME, status=str(status)).inc()
                return body, url, status
            except Exception:
                SOURCE_FETCH.labels(source=self.SOURCE_NAME, status="error").inc()
                raise

    def parse(self, body: bytes, target_date: Optional[date]) -> list[dict]:
        rows = parse_block_deals(body)
        if target_date is not None:
            iso = target_date.isoformat()
            rows = [r for r in rows if r["as_of_date"] == iso]
        return rows

    def validate(self, rows: list[dict]) -> tuple[list[dict], int]:
        kept, dropped = [], 0
        for r in rows:
            if r["quantity"] <= 0 or r["avg_price"] <= 0:
                dropped += 1
                continue
            kept.append(r)
        return kept, dropped

    async def persist(self, rows: list[dict], run: JobRun) -> int:
        inserted = await upsert_block_deals(rows, run.run_id)
        bus = get_bus()
        for r in rows:
            payload = {**r, "source": self.SOURCE_NAME, "source_run_id": str(run.run_id)}
            await bus.publish(
                self.KAFKA_TOPIC,
                key=f"{r['as_of_date']}|{r['symbol']}|{r['client_name']}|{r['deal_type']}|{r['deal_seq']}",
                value=payload,
                schema_name=self.AVRO_SCHEMA,
            )
        return inserted


async def run(target_date: Optional[date] = None) -> uuid.UUID:
    job = await BlockDealsIngester().run(target_date)
    return job.run_id
