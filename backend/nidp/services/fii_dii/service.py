"""nidp-fii-dii service."""
from __future__ import annotations

import logging
import uuid
from datetime import date
from typing import Optional

from nidp.shared.bus import get_bus
from nidp.shared.config import FII_DII_URL, NSE_WWW, fmt_url
from nidp.shared.ingester_base import BaseIngester
from nidp.shared.metrics import SOURCE_FETCH, time_fetch
from nidp.shared.sources.nse_fetcher import fetch_bytes
from nidp.shared.storage.job_log import JobRun

from .parser import parse_fii_dii
from .writer import SOURCE_NAME, upsert_fii_dii

logger = logging.getLogger(__name__)


class FiiDiiIngester(BaseIngester):
    SERVICE_NAME = "fii_dii"
    SOURCE_NAME = SOURCE_NAME
    KAFKA_TOPIC = "nidp.fii_dii.v1"
    AVRO_SCHEMA = "fii_dii_v1"

    async def fetch(self, target_date: Optional[date]) -> tuple[bytes, str, int]:
        if target_date is None:
            raise ValueError("fii_dii requires --date")
        url = fmt_url(FII_DII_URL, target_date)
        with time_fetch(self.SOURCE_NAME):
            try:
                body, status = await fetch_bytes(
                    url, referer=f"{NSE_WWW}/reports/fii-dii",
                )
                SOURCE_FETCH.labels(source=self.SOURCE_NAME, status=str(status)).inc()
                return body, url, status
            except Exception:
                SOURCE_FETCH.labels(source=self.SOURCE_NAME, status="error").inc()
                raise

    def parse(self, body: bytes, target_date: Optional[date]) -> list[dict]:
        if target_date is None:
            return []
        return parse_fii_dii(body, target_date.isoformat())

    def validate(self, rows: list[dict]) -> tuple[list[dict], int]:
        kept, dropped = [], 0
        for r in rows:
            if not (r["category"] and r["segment"] and r["as_of_date"]):
                dropped += 1
                continue
            kept.append(r)
        return kept, dropped

    async def persist(self, rows: list[dict], run: JobRun) -> int:
        inserted = await upsert_fii_dii(rows, run.run_id)
        bus = get_bus()
        for r in rows:
            payload = {**r, "source": self.SOURCE_NAME, "source_run_id": str(run.run_id)}
            await bus.publish(
                self.KAFKA_TOPIC,
                key=f"{r['as_of_date']}|{r['category']}|{r['segment']}",
                value=payload,
                schema_name=self.AVRO_SCHEMA,
            )
        return inserted


async def run(target_date: date) -> uuid.UUID:
    job = await FiiDiiIngester().run(target_date)
    return job.run_id
