"""nidp-bulk-deals service.

End-to-end:
    fetch → archive → parse → validate → persist → emit Kafka events
Driven by BaseIngester; the orchestration loop is in
nidp/shared/ingester_base.py.
"""
from __future__ import annotations

import logging
import uuid
from datetime import date
from typing import Optional

from nidp.shared.bus import get_bus
from nidp.shared.config import BULK_DEALS_URL, NSE_WWW
from nidp.shared.ingester_base import BaseIngester
from nidp.shared.metrics import SOURCE_FETCH, time_fetch
from nidp.shared.sources.nse_fetcher import fetch_bytes
from nidp.shared.storage.job_log import JobRun

from .parser import parse_bulk_deals
from .writer import SOURCE_NAME, upsert_bulk_deals

logger = logging.getLogger(__name__)


class BulkDealsIngester(BaseIngester):
    SERVICE_NAME = "bulk_deals"
    SOURCE_NAME = SOURCE_NAME
    KAFKA_TOPIC = "nidp.bulk_deals.v1"
    AVRO_SCHEMA = "bulk_deals_v1"

    async def fetch(self, target_date: Optional[date]) -> tuple[bytes, str, int]:
        url = BULK_DEALS_URL  # rolling file — `target_date` is informational
        with time_fetch(self.SOURCE_NAME):
            try:
                body, status = await fetch_bytes(
                    url, referer=f"{NSE_WWW}/report-detail/display-bulk-and-block-deals",
                )
                SOURCE_FETCH.labels(source=self.SOURCE_NAME, status=str(status)).inc()
                return body, url, status
            except Exception:
                SOURCE_FETCH.labels(source=self.SOURCE_NAME, status="error").inc()
                raise

    def parse(self, body: bytes, target_date: Optional[date]) -> list[dict]:
        rows = parse_bulk_deals(body)
        # When ingesting the rolling file, optionally narrow to the
        # requested date. If target_date is None, take everything.
        if target_date is not None:
            iso = target_date.isoformat()
            rows = [r for r in rows if r["as_of_date"] == iso]
        return rows

    def validate(self, rows: list[dict]) -> tuple[list[dict], int]:
        kept: list[dict] = []
        dropped = 0
        for r in rows:
            if r["quantity"] <= 0 or r["avg_price"] <= 0:
                dropped += 1
                continue
            kept.append(r)
        return kept, dropped

    async def persist(self, rows: list[dict], run: JobRun) -> int:
        inserted = await upsert_bulk_deals(rows, run.run_id)

        # Emit one Kafka event per row (downstream snapshot/feature
        # services consume these). LocalLogBus during dev — no
        # Kafka cluster needed.
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
    """Entry-point used by CLI and Airflow DAG."""
    ingester = BulkDealsIngester()
    job = await ingester.run(target_date)
    return job.run_id


async def run_intraday(target_date: Optional[date] = None) -> dict:
    """1-min intraday poll: market hours guard → ingest rolling bulk deals file.

    NSE publishes a single rolling CSV updated throughout the day.
    The writer uses ON CONFLICT so every 1-min re-run is safe — only
    genuinely new deals (new rows in the CSV) get inserted.
    Bulk deals tend to arrive in clusters around 9:30 and 14:00 IST.
    """
    from nidp.shared.market_hours import is_intraday_window
    if not is_intraday_window():
        logger.debug("bulk_deals: outside intraday window — exiting")
        return {"skipped": "outside_market_hours"}

    try:
        run_id = await run(target_date)
        logger.info("bulk_deals: intraday poll complete run_id=%s", run_id)
        return {"run_id": str(run_id)}
    except Exception as e:
        logger.error("bulk_deals: intraday poll failed: %s", e)
        return {"error": str(e)}
