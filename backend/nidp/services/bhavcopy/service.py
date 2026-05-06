"""nidp-bhavcopy ingester.

NSE serves bhavcopy as a ZIP containing one CSV. We download the ZIP,
unzip in memory, parse, and persist. Format auto-detected
(pre/post-Jul-2024) by parser.
"""
from __future__ import annotations

import io
import logging
import uuid
import zipfile
from datetime import date, datetime
from typing import Optional

from nidp.shared.bus import get_bus
from nidp.shared.config import (
    BHAVCOPY_FORMAT_CUTOVER_DATE, BHAVCOPY_URL_NEW, BHAVCOPY_URL_OLD,
    NSE_WWW, fmt_url,
)
from nidp.shared.ingester_base import BaseIngester
from nidp.shared.metrics import SOURCE_FETCH, time_fetch
from nidp.shared.sources.nse_fetcher import fetch_bytes
from nidp.shared.storage.job_log import JobRun

from .parser import parse_bhavcopy
from .writer import SOURCE_NAME, upsert_bhavcopy

logger = logging.getLogger(__name__)

_CUTOVER = datetime.strptime(BHAVCOPY_FORMAT_CUTOVER_DATE, "%Y-%m-%d").date()


def _url_for(target_date: date) -> str:
    if target_date >= _CUTOVER:
        return fmt_url(BHAVCOPY_URL_NEW, target_date)
    return fmt_url(BHAVCOPY_URL_OLD, target_date)


def _unzip_first_csv(body: bytes) -> bytes:
    """Bhavcopy is a ZIP with one CSV inside. Extract & return the
    CSV bytes. If the body isn't a ZIP (rare — sometimes NSE serves
    plain CSV under maintenance), return as-is."""
    if not body[:2] == b"PK":
        return body
    with zipfile.ZipFile(io.BytesIO(body)) as zf:
        for name in zf.namelist():
            if name.lower().endswith(".csv"):
                return zf.read(name)
        # Fallback: take the largest member
        biggest = max(zf.namelist(), key=lambda n: zf.getinfo(n).file_size)
        return zf.read(biggest)


class BhavcopyIngester(BaseIngester):
    SERVICE_NAME = "bhavcopy"
    SOURCE_NAME = SOURCE_NAME
    KAFKA_TOPIC = "nidp.bhavcopy.v1"
    AVRO_SCHEMA = "bhavcopy_v1"
    # Bhavcopy is the authoritative "trading day is fully closed and
    # published" signal. A successful run bumps
    # nidp.market_session_state.last_close_date so downstream ingesters
    # (delivery T+1, snapshot_builder, etc.) and ad-hoc consumers can
    # read a single canonical answer.
    BUMPS_MARKET_SESSION = True

    async def fetch(self, target_date: Optional[date]) -> tuple[bytes, str, int]:
        if target_date is None:
            raise ValueError("bhavcopy requires --date (no rolling-file mode)")
        url = _url_for(target_date)
        with time_fetch(self.SOURCE_NAME):
            try:
                body, status = await fetch_bytes(
                    url,
                    referer=f"{NSE_WWW}/all-reports",
                )
                SOURCE_FETCH.labels(source=self.SOURCE_NAME, status=str(status)).inc()
                return body, url, status
            except Exception:
                SOURCE_FETCH.labels(source=self.SOURCE_NAME, status="error").inc()
                raise

    def parse(self, body: bytes, target_date: Optional[date]) -> list[dict]:
        csv_bytes = _unzip_first_csv(body)
        rows = parse_bhavcopy(csv_bytes)
        # Hard-pin all rows to the requested target_date — guards
        # against parser glitches (occasional blank TradDt cells).
        if target_date is not None:
            iso = target_date.isoformat()
            for r in rows:
                if not r.get("as_of_date"):
                    r["as_of_date"] = iso
        return rows

    def validate(self, rows: list[dict]) -> tuple[list[dict], int]:
        kept: list[dict] = []
        dropped = 0
        for r in rows:
            if not r["symbol"] or not r["series"]:
                dropped += 1
                continue
            if r.get("close_price") is None:
                dropped += 1
                continue
            if not r.get("as_of_date"):
                dropped += 1
                continue
            kept.append(r)
        return kept, dropped

    async def persist(self, rows: list[dict], run: JobRun) -> int:
        inserted = await upsert_bhavcopy(rows, run.run_id)

        # Emit Kafka events. For 30k rows we batch via
        # producer-side queue; LocalLogBus is fine for dev.
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
    ingester = BhavcopyIngester()
    job = await ingester.run(target_date)
    return job.run_id
