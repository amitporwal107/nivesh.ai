"""nidp-rbi-yields service.

Replaces the existing macro_ingester's incorrect `^TNX` proxy
(US 10Y) with the actual India 10Y G-Sec from RBI.
"""
from __future__ import annotations

import logging
import uuid
from datetime import date
from typing import Optional

import aiohttp

from nidp.shared.bus import get_bus
from nidp.shared.config import (
    DEFAULT_UA, HTTP_TIMEOUT_S, RBI_GSEC_URL, RBI_REF_RATE_URL,
)
from nidp.shared.ingester_base import BaseIngester
from nidp.shared.metrics import SOURCE_FETCH, time_fetch
from nidp.shared.storage.job_log import JobRun

from .parser import parse_rbi_yields
from .writer import SOURCE_NAME, upsert_rbi_yields

logger = logging.getLogger(__name__)


async def _rbi_get(url: str) -> tuple[bytes, int]:
    """RBI doesn't need NSE-style cookie priming — a generic UA suffices.
    Kept separate from the NSE fetcher because RBI's rate-limit profile
    and headers are different (no Referer, longer body)."""
    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=HTTP_TIMEOUT_S),
        headers={
            "User-Agent": DEFAULT_UA,
            "Accept": "text/html,*/*",
            "Accept-Language": "en-US,en;q=0.9",
        },
    ) as session:
        async with session.get(url) as resp:
            body = await resp.read()
            return body, resp.status


class RbiYieldsIngester(BaseIngester):
    SERVICE_NAME = "rbi_yields"
    SOURCE_NAME = SOURCE_NAME
    KAFKA_TOPIC = "nidp.rbi_yields.v1"
    AVRO_SCHEMA = "rbi_yields_v1"

    async def fetch(self, target_date: Optional[date]) -> tuple[bytes, str, int]:
        # Try the BS_NSDPDisplay (Daily Reference Rate) page first; if
        # it 4xx's, fall back to ReferenceRateArchive.
        for url in (RBI_GSEC_URL, RBI_REF_RATE_URL):
            with time_fetch(self.SOURCE_NAME):
                try:
                    body, status = await _rbi_get(url)
                    if status == 200 and body:
                        SOURCE_FETCH.labels(source=self.SOURCE_NAME, status=str(status)).inc()
                        return body, url, status
                    SOURCE_FETCH.labels(source=self.SOURCE_NAME, status=str(status)).inc()
                except Exception:                                  # noqa: BLE001
                    SOURCE_FETCH.labels(source=self.SOURCE_NAME, status="error").inc()
                    continue
        raise RuntimeError("RBI yields: all source URLs failed")

    def parse(self, body: bytes, target_date: Optional[date]) -> list[dict]:
        return parse_rbi_yields(body)

    def validate(self, rows: list[dict]) -> tuple[list[dict], int]:
        kept, dropped = [], 0
        for r in rows:
            if r["as_of_date"] and r["tenor"] and r["yield_pct"] is not None:
                kept.append(r)
            else:
                dropped += 1
        return kept, dropped

    async def persist(self, rows: list[dict], run: JobRun) -> int:
        inserted = await upsert_rbi_yields(rows, run.run_id)
        bus = get_bus()
        for r in rows:
            payload = {**r, "source": self.SOURCE_NAME, "source_run_id": str(run.run_id)}
            await bus.publish(
                self.KAFKA_TOPIC,
                key=f"{r['as_of_date']}|{r['tenor']}",
                value=payload,
                schema_name=self.AVRO_SCHEMA,
            )
        return inserted


async def run(target_date: Optional[date] = None) -> uuid.UUID:
    job = await RbiYieldsIngester().run(target_date)
    return job.run_id
