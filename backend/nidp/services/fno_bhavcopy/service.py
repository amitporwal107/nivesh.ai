"""nidp-fno-bhavcopy ingester.

Same NSE archive layout as the cash-bhavcopy ingester: ZIP wrapping a
single CSV, format auto-detected (pre/post-Jul-2024) by parser.
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
    NSE_FO_BHAVCOPY_FORMAT_CUTOVER_DATE,
    NSE_FO_BHAVCOPY_URL_NEW,
    NSE_FO_BHAVCOPY_URL_OLD,
    NSE_WWW,
    fmt_url,
)
from nidp.shared.ingester_base import BaseIngester
from nidp.shared.metrics import SOURCE_FETCH, time_fetch
from nidp.shared.sources.nse_fetcher import fetch_bytes
from nidp.shared.storage.job_log import JobRun

from .parser import parse_fno_bhavcopy
from .writer import SOURCE_NAME, upsert_fno_bhavcopy

logger = logging.getLogger(__name__)

_CUTOVER = datetime.strptime(NSE_FO_BHAVCOPY_FORMAT_CUTOVER_DATE, "%Y-%m-%d").date()


def _url_for(target_date: date) -> str:
    if target_date >= _CUTOVER:
        return fmt_url(NSE_FO_BHAVCOPY_URL_NEW, target_date)
    return fmt_url(NSE_FO_BHAVCOPY_URL_OLD, target_date)


def _unzip_first_csv(body: bytes) -> bytes:
    if not body[:2] == b"PK":
        return body
    with zipfile.ZipFile(io.BytesIO(body)) as zf:
        for name in zf.namelist():
            if name.lower().endswith(".csv"):
                return zf.read(name)
        biggest = max(zf.namelist(), key=lambda n: zf.getinfo(n).file_size)
        return zf.read(biggest)


class FnoBhavcopyIngester(BaseIngester):
    SERVICE_NAME = "fno_bhavcopy"
    SOURCE_NAME = SOURCE_NAME
    KAFKA_TOPIC = "nidp.fno_bhavcopy.v1"
    AVRO_SCHEMA = "fno_bhavcopy_v1"

    async def fetch(self, target_date: Optional[date]) -> tuple[bytes, str, int]:
        if target_date is None:
            raise ValueError("fno_bhavcopy requires --date (no rolling-file mode)")
        url = _url_for(target_date)
        with time_fetch(self.SOURCE_NAME):
            try:
                body, status = await fetch_bytes(
                    url,
                    referer=f"{NSE_WWW}/all-reports-derivatives",
                )
                SOURCE_FETCH.labels(source=self.SOURCE_NAME, status=str(status)).inc()
                return body, url, status
            except Exception:
                SOURCE_FETCH.labels(source=self.SOURCE_NAME, status="error").inc()
                raise

    def parse(self, body: bytes, target_date: Optional[date]) -> list[dict]:
        csv_bytes = _unzip_first_csv(body)
        rows = parse_fno_bhavcopy(csv_bytes)
        # Hard-pin all rows to the requested target_date as a guard
        # against blank TradDt cells.
        if target_date is not None:
            iso = target_date.isoformat()
            for r in rows:
                if not r.get("as_of_date"):
                    r["as_of_date"] = iso
        return rows

    def validate(self, rows: list[dict]) -> tuple[list[dict], int]:
        kept, dropped = [], 0
        for r in rows:
            if not (r.get("ticker_symbol") and r.get("expiry_date")
                    and r.get("instrument_type") and r.get("as_of_date")):
                dropped += 1
                continue
            kept.append(r)
        return kept, dropped

    async def persist(self, rows: list[dict], run: JobRun) -> int:
        inserted = await upsert_fno_bhavcopy(rows, run.run_id)
        bus = get_bus()
        for r in rows:
            payload = {**r, "source": self.SOURCE_NAME, "source_run_id": str(run.run_id)}
            await bus.publish(
                self.KAFKA_TOPIC,
                key=f"{r['as_of_date']}|{r['ticker_symbol']}|{r['expiry_date']}|{r.get('strike_price') or ''}|{r.get('option_type') or 'FUT'}",
                value=payload,
                schema_name=self.AVRO_SCHEMA,
            )
        return inserted


async def run(target_date: date) -> uuid.UUID:
    job = await FnoBhavcopyIngester().run(target_date)
    return job.run_id
