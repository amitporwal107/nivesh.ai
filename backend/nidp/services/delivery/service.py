"""nidp-delivery service."""
from __future__ import annotations

import logging
import uuid
from datetime import date
from typing import Optional

from nidp.shared.bus import get_bus
from nidp.shared.config import DELIVERY_URL, NSE_WWW, fmt_url
from nidp.shared.ingester_base import BaseIngester
from nidp.shared.metrics import SOURCE_FETCH, time_fetch
from nidp.shared.sources.nse_fetcher import fetch_bytes
from nidp.shared.storage.job_log import JobRun

from .parser import parse_delivery
from .writer import SOURCE_NAME, upsert_delivery

logger = logging.getLogger(__name__)


class DeliveryIngester(BaseIngester):
    SERVICE_NAME = "delivery"
    SOURCE_NAME = SOURCE_NAME
    KAFKA_TOPIC = "nidp.delivery.v1"
    AVRO_SCHEMA = "delivery_v1"

    async def fetch(self, target_date: Optional[date]) -> tuple[bytes, str, int]:
        if target_date is None:
            raise ValueError("delivery requires --date")
        url = fmt_url(DELIVERY_URL, target_date)
        with time_fetch(self.SOURCE_NAME):
            try:
                body, status = await fetch_bytes(url, referer=f"{NSE_WWW}/all-reports")
                SOURCE_FETCH.labels(source=self.SOURCE_NAME, status=str(status)).inc()
                return body, url, status
            except Exception:
                SOURCE_FETCH.labels(source=self.SOURCE_NAME, status="error").inc()
                raise

    def parse(self, body: bytes, target_date: Optional[date]) -> list[dict]:
        return parse_delivery(body)

    def validate(self, rows: list[dict]) -> tuple[list[dict], int]:
        kept, dropped = [], 0
        for r in rows:
            if not r["symbol"] or not r["series"] or not r["as_of_date"]:
                dropped += 1
                continue
            kept.append(r)
        return kept, dropped

    async def persist(self, rows: list[dict], run: JobRun) -> int:
        inserted = await upsert_delivery(rows, run.run_id)
        bus = get_bus()
        for r in rows:
            payload = {**r, "source": self.SOURCE_NAME, "source_run_id": str(run.run_id)}
            await bus.publish(
                self.KAFKA_TOPIC,
                key=f"{r['as_of_date']}|{r['symbol']}|{r['series']}",
                value=payload,
                schema_name=self.AVRO_SCHEMA,
            )
        return inserted


async def run(target_date: date) -> uuid.UUID:
    job = await DeliveryIngester().run(target_date)
    return job.run_id
