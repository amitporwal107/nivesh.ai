"""nidp-delivery service."""
from __future__ import annotations

import logging
import uuid
from datetime import date
from typing import Optional

from nidp.shared.bus import get_bus
from nidp.shared.config import DELIVERY_URL, NSE_WWW, fmt_url
from nidp.shared.ingester_base import BaseIngester
from nidp.shared.metrics import SOURCE_FETCH, time_fetch
from nidp.shared.sources.bse_fetcher import bhavcopy_url as bse_bhavcopy_url
from nidp.shared.sources.bse_fetcher import delivery_url as bse_delivery_url
from nidp.shared.sources.bse_fetcher import fetch_bytes as bse_fetch_bytes
from nidp.shared.sources.nse_fetcher import fetch_bytes
from nidp.shared.storage.job_log import JobRun

from nidp.services.bhavcopy.parser import parse_bse_scrip_isin

from .bse_parser import parse_bse_delivery
from .parser import parse_delivery
from .writer import (
    BSE_SOURCE_NAME,
    SOURCE_NAME,
    dates_already_covered_by_nse,
    drop_bse_delivery_gapfill_for,
    propagate_to_prices_eod,
    upsert_bse_delivery_gapfill,
    upsert_delivery,
)

logger = logging.getLogger(__name__)


class DeliveryIngester(BaseIngester):
    SERVICE_NAME = "delivery"
    SOURCE_NAME = SOURCE_NAME
    KAFKA_TOPIC = "nidp.delivery.v1"
    AVRO_SCHEMA = "delivery_v1"

    # Set by fetch() when NSE was unreachable and BSE supplied the day.
    _used_bse: bool = False
    _already_covered: bool = False
    _scrip_to_isin: dict = {}

    async def fetch(self, target_date: Optional[date]) -> tuple[bytes, str, int]:
        if target_date is None:
            raise ValueError("delivery requires --date")
        url = fmt_url(DELIVERY_URL, target_date)
        self._used_bse = False
        self._already_covered = False
        self._scrip_to_isin = {}
        with time_fetch(self.SOURCE_NAME):
            try:
                body, status = await fetch_bytes(
                    url,
                    referer=f"{NSE_WWW}/all-reports",
                    archive_as=("delivery", target_date, url.rsplit("/", 1)[-1]),
                )
                SOURCE_FETCH.labels(source=self.SOURCE_NAME, status=str(status)).inc()
                return body, url, status
            except Exception as nse_exc:  # noqa: BLE001
                SOURCE_FETCH.labels(source=self.SOURCE_NAME, status="error").inc()
                logger.warning(
                    "delivery: NSE fetch failed for %s (%s) — trying BSE",
                    target_date, nse_exc,
                )
                return await self._fetch_bse(target_date, nse_exc)

    async def _fetch_bse(self, target_date: date, nse_exc: BaseException
                         ) -> tuple[bytes, str, int]:
        """Fall back to BSE's delivery-position file for the same day.

        Needs two BSE files: the delivery TXT (scrip-code keyed) and that
        day's BSE bhavcopy, which supplies the scrip_code -> ISIN bridge
        used to re-key rows onto NSE symbol/series.
        """
        if await dates_already_covered_by_nse([target_date]):
            logger.info(
                "delivery: NSE unreachable for %s, but the day is already "
                "stored from NSE — nothing to back-fill", target_date,
            )
            self._already_covered = True
            return b"", bse_delivery_url(target_date), 200

        url = bse_delivery_url(target_date)
        with time_fetch(BSE_SOURCE_NAME):
            try:
                body, status = await bse_fetch_bytes(url)
                SOURCE_FETCH.labels(
                    source=BSE_SOURCE_NAME, status=str(status)).inc()
            except Exception:  # noqa: BLE001
                SOURCE_FETCH.labels(source=BSE_SOURCE_NAME, status="error").inc()
                logger.exception("delivery: BSE fallback also failed for %s",
                                 target_date)
                raise nse_exc from None

        # Bridge file. Without it every row is unmappable, so a failure
        # here is as fatal as the delivery file itself failing.
        try:
            bhav, _ = await bse_fetch_bytes(bse_bhavcopy_url(target_date))
            self._scrip_to_isin = parse_bse_scrip_isin(bhav)
        except Exception:  # noqa: BLE001
            logger.exception(
                "delivery: BSE bhavcopy bridge unavailable for %s", target_date)
            raise nse_exc from None
        if not self._scrip_to_isin:
            logger.error("delivery: empty scrip->ISIN bridge for %s", target_date)
            raise nse_exc from None

        self._used_bse = True
        return body, url, status

    def parse(self, body: bytes, target_date: Optional[date]) -> list[dict]:
        if self._already_covered:
            return []
        if self._used_bse:
            return parse_bse_delivery(body)
        return parse_delivery(body)

    def validate(self, rows: list[dict]) -> tuple[list[dict], int]:
        kept, dropped = [], 0
        for r in rows:
            if self._used_bse:
                # BSE rows are scrip-code keyed; symbol/series are assigned
                # during persist via the ISIN bridge.
                if not r.get("scrip_code") or not r.get("as_of_date"):
                    dropped += 1
                    continue
            elif not r["symbol"] or not r["series"] or not r["as_of_date"]:
                dropped += 1
                continue
            kept.append(r)
        return kept, dropped

    async def persist(self, rows: list[dict], run: JobRun) -> int:
        if self._used_bse:
            inserted = await upsert_bse_delivery_gapfill(
                rows, self._scrip_to_isin, run.run_id)
            await propagate_to_prices_eod(
                sorted({r["as_of_date"] for r in rows}))
            return inserted

        inserted = await upsert_delivery(rows, run.run_id)
        # NSE is authoritative: retire BSE stand-ins for these days.
        await drop_bse_delivery_gapfill_for(
            sorted({r["as_of_date"] for r in rows}))
        # delivery_data and prices_eod share the (as_of_date, symbol, series)
        # grain; keep prices_eod's deliv_* columns in step so the readers
        # of those columns (snapshot_builder, sector_scoring's
        # deliv_pct_avg_20, DaaS /prices) see real figures.
        await propagate_to_prices_eod(sorted({r["as_of_date"] for r in rows}))
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
    job = await DeliveryIngester().run(target_date)
    return job.run_id
