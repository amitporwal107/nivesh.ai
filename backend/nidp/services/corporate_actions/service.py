"""nidp-corporate-actions service."""
from __future__ import annotations

import logging
import uuid
from datetime import date
from typing import Optional

from nidp.shared.bus import get_bus
from nidp.shared.config import CORPORATE_ACTIONS_URL_ROLLING, NSE_WWW
from nidp.shared.ingester_base import BaseIngester
from nidp.shared.metrics import SOURCE_FETCH, time_fetch
from nidp.shared.sources.nse_fetcher import fetch_bytes
from nidp.shared.storage.job_log import JobRun

from .parser import parse_corporate_actions
from .writer import SOURCE_NAME, upsert_corporate_actions

logger = logging.getLogger(__name__)


class CorporateActionsIngester(BaseIngester):
    SERVICE_NAME = "corporate_actions"
    SOURCE_NAME = SOURCE_NAME
    KAFKA_TOPIC = "nidp.corporate_actions.v1"
    AVRO_SCHEMA = "corporate_actions_v1"

    async def fetch(self, target_date: Optional[date]) -> tuple[bytes, str, int]:
        url = CORPORATE_ACTIONS_URL_ROLLING
        with time_fetch(self.SOURCE_NAME):
            try:
                body, status = await fetch_bytes(
                    url,
                    referer=f"{NSE_WWW}/companies-listing/corporate-filings-actions",
                )
                SOURCE_FETCH.labels(source=self.SOURCE_NAME, status=str(status)).inc()
                return body, url, status
            except Exception:
                SOURCE_FETCH.labels(source=self.SOURCE_NAME, status="error").inc()
                raise

    def parse(self, body: bytes, target_date: Optional[date]) -> list[dict]:
        return parse_corporate_actions(body)

    def validate(self, rows: list[dict]) -> tuple[list[dict], int]:
        kept, dropped = [], 0
        for r in rows:
            if not (r["symbol"] and r["ex_date"] and r["action_type"]):
                dropped += 1
                continue
            kept.append(r)
        return kept, dropped

    async def persist(self, rows: list[dict], run: JobRun) -> int:
        inserted = await upsert_corporate_actions(rows, run.run_id)
        bus = get_bus()
        for r in rows:
            payload = {**r, "source": self.SOURCE_NAME, "source_run_id": str(run.run_id)}
            await bus.publish(
                self.KAFKA_TOPIC,
                key=f"{r['symbol']}|{r['action_type']}|{r['ex_date']}",
                value=payload,
                schema_name=self.AVRO_SCHEMA,
            )
        return inserted


async def run(target_date: Optional[date] = None) -> uuid.UUID:
    job = await CorporateActionsIngester().run(target_date)
    return job.run_id
