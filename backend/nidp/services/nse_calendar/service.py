"""nidp-nse-calendar service."""
from __future__ import annotations

import logging
import uuid
from datetime import date
from typing import Optional

from nidp.shared.bus import get_bus
from nidp.shared.config import NSE_HOLIDAY_URL, NSE_WWW
from nidp.shared.ingester_base import BaseIngester
from nidp.shared.metrics import SOURCE_FETCH, time_fetch
from nidp.shared.sources.nse_fetcher import fetch_bytes
from nidp.shared.storage.job_log import JobRun

from .parser import parse_calendar
from .writer import SOURCE_NAME, upsert_holidays

logger = logging.getLogger(__name__)


class NseCalendarIngester(BaseIngester):
    SERVICE_NAME = "nse_calendar"
    SOURCE_NAME = SOURCE_NAME
    KAFKA_TOPIC = "nidp.nse_calendar.v1"
    AVRO_SCHEMA = "nse_calendar_v1"

    async def fetch(self, target_date: Optional[date]) -> tuple[bytes, str, int]:
        url = NSE_HOLIDAY_URL
        with time_fetch(self.SOURCE_NAME):
            try:
                body, status = await fetch_bytes(
                    url,
                    referer=f"{NSE_WWW}/resources/exchange-communication-holidays",
                    extra_headers={"Accept": "application/json"},
                    archive_as=("nse_calendar", target_date, "nse_holidays.json"),
                )
                SOURCE_FETCH.labels(source=self.SOURCE_NAME, status=str(status)).inc()
                return body, url, status
            except Exception:
                SOURCE_FETCH.labels(source=self.SOURCE_NAME, status="error").inc()
                raise

    def parse(self, body: bytes, target_date: Optional[date]) -> list[dict]:
        return parse_calendar(body)

    def validate(self, rows: list[dict]) -> tuple[list[dict], int]:
        kept, dropped = [], 0
        for r in rows:
            if r["holiday_date"] and r["segment"]:
                kept.append(r)
            else:
                dropped += 1
        return kept, dropped

    async def persist(self, rows: list[dict], run: JobRun) -> int:
        inserted = await upsert_holidays(rows, run.run_id)
        bus = get_bus()
        for r in rows:
            payload = {**r, "source": self.SOURCE_NAME, "source_run_id": str(run.run_id)}
            await bus.publish(
                self.KAFKA_TOPIC,
                key=f"{r['holiday_date']}|{r['segment']}",
                value=payload,
                schema_name=self.AVRO_SCHEMA,
            )
        return inserted


async def run(target_date: Optional[date] = None) -> uuid.UUID:
    job = await NseCalendarIngester().run(target_date)
    return job.run_id
