"""nidp-index-constituents service.

Iterates the configured INDEX_CONSTITUENT_URLS dict; one fetch+parse+
persist cycle per index. Each index's persist is its own transaction,
so a 4xx on one index doesn't block the others.
"""
from __future__ import annotations

import logging
import uuid
from datetime import date
from typing import Optional

from nidp.shared.bus import get_bus
from nidp.shared.config import INDEX_CONSTITUENT_URLS, NSE_WWW
from nidp.shared.ingester_base import BaseIngester
from nidp.shared.metrics import (
    INGESTER_ROWS, INGESTER_RUNS, SOURCE_FETCH, time_fetch, time_ingester,
)
from nidp.shared.logging_setup import bind_context
from nidp.shared.sources.nse_fetcher import fetch_bytes
from nidp.shared.storage.job_log import JobRun
from nidp.shared.storage.raw_archive import store as store_raw

from .parser import parse_constituents
from .writer import SOURCE_NAME, upsert_constituents

logger = logging.getLogger(__name__)

SERVICE_NAME = "index_constituents"


class IndexConstituentsIngester(BaseIngester):
    """Multi-URL ingester. Overrides BaseIngester.run() to iterate
    over the configured index list rather than a single URL."""

    SERVICE_NAME = SERVICE_NAME
    SOURCE_NAME = SOURCE_NAME
    KAFKA_TOPIC = "nidp.index_constituents.v1"
    AVRO_SCHEMA = "index_constituents_v1"

    # The base abstract methods exist but we run a multi-source loop;
    # provide no-op defaults so the contract is satisfied.
    async def fetch(self, target_date): raise NotImplementedError("multi-URL ingester")
    def parse(self, body, target_date): raise NotImplementedError("multi-URL ingester")
    async def persist(self, rows, run): raise NotImplementedError("multi-URL ingester")

    async def run(self, target_date: Optional[date] = None) -> JobRun:
        as_of = target_date or date.today()
        bind_context(service=self.SERVICE_NAME, target_date=as_of.isoformat())

        async with JobRun(ingester=self.SERVICE_NAME, target_date=as_of) as run:
            bind_context(run_id=str(run.run_id))
            bus = get_bus()
            total_inserted = 0
            total_skipped = 0
            total_fetched = 0
            partial = False

            with time_ingester(self.SERVICE_NAME):
                for index_name, url in INDEX_CONSTITUENT_URLS.items():
                    try:
                        with time_fetch(self.SOURCE_NAME):
                            body, status = await fetch_bytes(
                                url, referer=f"{NSE_WWW}/market-data/live-equity-market",
                            )
                            SOURCE_FETCH.labels(source=self.SOURCE_NAME, status=str(status)).inc()
                        await store_raw(
                            ingester=self.SERVICE_NAME,
                            target_date=as_of,
                            source_url=url,
                            body=body,
                            http_status=status,
                            content_type="text/csv",
                            metadata={"index_name": index_name},
                        )
                        rows = parse_constituents(body)
                        total_fetched += len(rows)
                        kept = [r for r in rows if r["symbol"]]
                        total_skipped += (len(rows) - len(kept))

                        inserted = await upsert_constituents(
                            kept, index_name=index_name, as_of=as_of, run_id=run.run_id,
                        )
                        total_inserted += inserted
                        for r in kept:
                            payload = {
                                "as_of_date": as_of.isoformat(),
                                "index_name": index_name,
                                **r,
                                "source": self.SOURCE_NAME,
                                "source_run_id": str(run.run_id),
                            }
                            await bus.publish(
                                self.KAFKA_TOPIC,
                                key=f"{as_of.isoformat()}|{index_name}|{r['symbol']}",
                                value=payload,
                                schema_name=self.AVRO_SCHEMA,
                            )
                    except Exception as e:                                  # noqa: BLE001
                        logger.warning("index_constituents %s failed: %s", index_name, e)
                        partial = True

                run.rows_fetched = total_fetched
                run.rows_inserted = total_inserted
                run.rows_skipped = total_skipped
                INGESTER_ROWS.labels(service=self.SERVICE_NAME, kind="fetched").inc(total_fetched)
                INGESTER_ROWS.labels(service=self.SERVICE_NAME, kind="inserted").inc(total_inserted)
                INGESTER_ROWS.labels(service=self.SERVICE_NAME, kind="skipped").inc(total_skipped)

                final = "PARTIAL" if partial else "OK"
                await run.finalize(final)
                INGESTER_RUNS.labels(service=self.SERVICE_NAME, status=final).inc()
                return run


async def run(target_date: Optional[date] = None) -> uuid.UUID:
    job = await IndexConstituentsIngester().run(target_date)
    return job.run_id
