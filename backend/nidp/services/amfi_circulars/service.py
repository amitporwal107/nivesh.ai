"""nidp-amfi-circulars ingester.

Polls the AMFI notices listing page and upserts rows by URL-hash.
Body-text extraction (PDF parse) is left as a follow-up — the URL +
title alone are enough for the lifecycle-event downstream to flag
relevant items for human review.
"""
from __future__ import annotations

import logging
import uuid
from datetime import date
from typing import Optional

import aiohttp

from nidp.shared.config import AMFI_CIRCULARS_URL, DEFAULT_UA, HTTP_TIMEOUT_S
from nidp.shared.ingester_base import BaseIngester
from nidp.shared.metrics import SOURCE_FETCH, time_fetch
from nidp.shared.storage.job_log import JobRun

from .parser import parse_circulars
from .writer import SOURCE_NAME, upsert_circulars

logger = logging.getLogger(__name__)


class AmfiCircularsIngester(BaseIngester):
    SERVICE_NAME = "amfi_circulars"
    SOURCE_NAME = SOURCE_NAME
    KAFKA_TOPIC = "nidp.mf_amfi_circulars.v1"
    AVRO_SCHEMA = "mf_amfi_circular_v1"

    async def fetch(self, target_date: Optional[date]) -> tuple[bytes, str, int]:
        url = AMFI_CIRCULARS_URL
        timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT_S)
        headers = {"User-Agent": DEFAULT_UA, "Accept": "text/html,*/*"}
        with time_fetch(self.SOURCE_NAME):
            try:
                async with aiohttp.ClientSession(timeout=timeout, headers=headers) as s:
                    async with s.get(url) as resp:
                        body = await resp.read()
                        SOURCE_FETCH.labels(
                            source=self.SOURCE_NAME, status=str(resp.status),
                        ).inc()
                        return body, url, resp.status
            except Exception:
                SOURCE_FETCH.labels(source=self.SOURCE_NAME, status="error").inc()
                raise

    def parse(self, body: bytes, target_date: Optional[date]) -> list[dict]:
        rows = parse_circulars(body)
        logger.info("amfi_circulars parsed %d rows", len(rows))
        return rows

    async def persist(self, rows: list[dict], run: JobRun) -> int:
        return await upsert_circulars(rows, run.run_id)


async def run(target_date: Optional[date] = None) -> uuid.UUID:
    job = await AmfiCircularsIngester().run(target_date)
    return job.run_id
