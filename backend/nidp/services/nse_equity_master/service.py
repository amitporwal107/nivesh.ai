"""nidp-nse-equity-master service.

One CSV per run. After upsert, kicks off the index-membership-based
sector derivation pass — cheap UPDATE that fills sector/industry
columns for symbols that are members of sectoral indices we already
ingest (Bank Nifty, Nifty IT — extend as we add more).
"""
from __future__ import annotations

import logging
import uuid
from datetime import date
from typing import Optional

from nidp.shared.bus import get_bus
from nidp.shared.config import NSE_EQUITY_MASTER_URL, NSE_WWW
from nidp.shared.ingester_base import BaseIngester
from nidp.shared.metrics import SOURCE_FETCH, time_fetch
from nidp.shared.sources.nse_fetcher import fetch_bytes
from nidp.shared.storage.job_log import JobRun

from .parser import parse_equity_master
from .writer import (
    SOURCE_NAME,
    derive_sectors_from_index_membership,
    upsert_equity_master,
)

logger = logging.getLogger(__name__)


class NseEquityMasterIngester(BaseIngester):
    SERVICE_NAME = "nse_equity_master"
    SOURCE_NAME = SOURCE_NAME
    KAFKA_TOPIC = "nidp.sector_master.v1"
    AVRO_SCHEMA = ""   # No fact-stream avro for this — it's reference data

    async def fetch(self, target_date: Optional[date]) -> tuple[bytes, str, int]:
        url = NSE_EQUITY_MASTER_URL
        with time_fetch(self.SOURCE_NAME):
            try:
                body, status = await fetch_bytes(
                    url,
                    referer=f"{NSE_WWW}/market-data/securities-available-for-trading",
                )
                SOURCE_FETCH.labels(source=self.SOURCE_NAME, status=str(status)).inc()
                return body, url, status
            except Exception:
                SOURCE_FETCH.labels(source=self.SOURCE_NAME, status="error").inc()
                raise

    def parse(self, body: bytes, target_date: Optional[date]) -> list[dict]:
        return parse_equity_master(body)

    def validate(self, rows: list[dict]) -> tuple[list[dict], int]:
        kept, dropped = [], 0
        for r in rows:
            if not r.get("symbol"):
                dropped += 1
                continue
            kept.append(r)
        return kept, dropped

    async def persist(self, rows: list[dict], run: JobRun) -> int:
        inserted = await upsert_equity_master(rows, run.run_id)
        # Cheap follow-up pass — backfill sector from index membership
        try:
            await derive_sectors_from_index_membership(run.run_id)
        except Exception:                                                # noqa: BLE001
            # Sector derivation is opportunistic. Don't fail the run.
            logger.exception("sector derivation pass failed (continuing)")
        return inserted


async def run(target_date: Optional[date] = None) -> uuid.UUID:
    job = await NseEquityMasterIngester().run(target_date)
    return job.run_id
