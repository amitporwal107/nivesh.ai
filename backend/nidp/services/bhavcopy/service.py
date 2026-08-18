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
from nidp.shared.sources.bse_fetcher import bhavcopy_url as bse_bhavcopy_url
from nidp.shared.sources.bse_fetcher import fetch_bytes as bse_fetch_bytes
from nidp.shared.sources.nse_fetcher import fetch_bytes
from nidp.shared.storage.job_log import JobRun

from .parser import parse_bhavcopy
from .writer import (
    BSE_SOURCE_NAME,
    SOURCE_NAME,
    dates_already_covered_by_nse,
    drop_bse_gapfill_for,
    upsert_bhavcopy,
    upsert_bse_gapfill,
)

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

    # True when NSE was unreachable and BSE supplied the day instead.
    _used_bse: bool = False
    # True when NSE was unreachable but the day is already stored, so
    # there is nothing to back-fill and the run is a legitimate no-op.
    _already_covered: bool = False

    async def fetch(self, target_date: Optional[date]) -> tuple[bytes, str, int]:
        if target_date is None:
            raise ValueError("bhavcopy requires --date (no rolling-file mode)")
        url = _url_for(target_date)
        self._used_bse = False
        self._already_covered = False
        with time_fetch(self.SOURCE_NAME):
            try:
                body, status = await fetch_bytes(
                    url,
                    referer=f"{NSE_WWW}/all-reports",
                    archive_as=("bhavcopy", target_date, url.rsplit("/", 1)[-1]),
                )
                SOURCE_FETCH.labels(source=self.SOURCE_NAME, status=str(status)).inc()
                return body, url, status
            except Exception as nse_exc:  # noqa: BLE001
                SOURCE_FETCH.labels(source=self.SOURCE_NAME, status="error").inc()
                logger.warning(
                    "bhavcopy: NSE fetch failed for %s (%s) — trying BSE",
                    target_date, nse_exc,
                )
                return await self._fetch_bse(target_date, nse_exc)

    async def _fetch_bse(self, target_date: date, nse_exc: BaseException
                         ) -> tuple[bytes, str, int]:
        """Fall back to BSE's SEBI-standard bhavcopy for the same day.

        BSE publishes the identical column layout, so `parse_bhavcopy`
        handles it unchanged. Re-raise the NSE error if BSE also fails —
        NSE is the primary source and the more actionable failure.
        """
        # If a previous NSE run already stored this day there is nothing
        # to back-fill. Returning empty lets BaseIngester finalize the run
        # as SKIPPED instead of BLOCKing validation on zero inserted rows
        # (which would mark a correct no-op as a feed failure and inflate
        # consecutive_failures), and it saves an ~850KB pointless download.
        if await dates_already_covered_by_nse([target_date]):
            logger.info(
                "bhavcopy: NSE unreachable for %s, but the day is already "
                "stored from NSE — nothing to back-fill", target_date,
            )
            self._already_covered = True
            return b"", bse_bhavcopy_url(target_date), 200

        url = bse_bhavcopy_url(target_date)
        with time_fetch(BSE_SOURCE_NAME):
            try:
                body, status = await bse_fetch_bytes(url)
                SOURCE_FETCH.labels(
                    source=BSE_SOURCE_NAME, status=str(status)).inc()
            except Exception:  # noqa: BLE001
                SOURCE_FETCH.labels(source=BSE_SOURCE_NAME, status="error").inc()
                logger.exception("bhavcopy: BSE fallback also failed for %s",
                                 target_date)
                raise nse_exc from None
        self._used_bse = True
        return body, url, status

    def parse(self, body: bytes, target_date: Optional[date]) -> list[dict]:
        if self._already_covered:
            return []
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
        if self._used_bse:
            # Gap-fill semantics: BSE only supplies days NSE has missed,
            # re-keyed onto NSE symbol/series via ISIN. See
            # writer.upsert_bse_gapfill for why both guards are needed.
            return await upsert_bse_gapfill(rows, run.run_id)

        inserted = await upsert_bhavcopy(rows, run.run_id)
        # NSE is authoritative: once the real bhavcopy lands, retire any
        # BSE stand-in rows for those days so no day carries two rows per
        # symbol (every downstream filter keys on series, not source).
        await drop_bse_gapfill_for(sorted({r["as_of_date"] for r in rows}))

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
