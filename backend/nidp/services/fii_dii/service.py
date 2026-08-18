"""nidp-fii-dii service."""
from __future__ import annotations

import logging
import uuid
from datetime import date
from typing import Optional

from nidp.shared.bus import get_bus
from nidp.shared.config import FII_DII_URL, NSE_WWW, fmt_url
from nidp.shared.ingester_base import BaseIngester
from nidp.shared.metrics import SOURCE_FETCH, time_fetch
from nidp.shared.sources.nse_fetcher import fetch_bytes
from nidp.shared.sources.nsdl_fetcher import (
    NSDL_DII_LATEST,
    NSDL_FPI_LATEST,
)
from nidp.shared.sources.nsdl_fetcher import fetch_bytes as nsdl_fetch_bytes
from nidp.shared.storage.job_log import JobRun

from .nsdl_parser import parse_nsdl_dii, parse_nsdl_fpi
from .parser import parse_fii_dii
from .writer import SOURCE_NAME, upsert_fii_dii

NSDL_FPI_SOURCE = "NSDL_FPI"
NSDL_DII_SOURCE = "NSDL_DII"

logger = logging.getLogger(__name__)


class FiiDiiIngester(BaseIngester):
    SERVICE_NAME = "fii_dii"
    SOURCE_NAME = SOURCE_NAME
    KAFKA_TOPIC = "nidp.fii_dii.v1"
    AVRO_SCHEMA = "fii_dii_v1"

    # Set by fetch() so parse()/persist() know which source actually
    # answered. NSE is preferred (it is the provisional same-day print);
    # NSDL is the custodian-confirmed fallback used when NSE's edge
    # blocks this egress IP.
    _used_nsdl: bool = False
    _nsdl_dii_body: bytes = b""

    async def fetch(self, target_date: Optional[date]) -> tuple[bytes, str, int]:
        # New endpoint is a rolling JSON API — no date param needed.
        # The legacy XLS URL (with date) is preserved in config for
        # historical backfill but the live source is the JSON endpoint.
        url = FII_DII_URL
        self._used_nsdl = False
        self._nsdl_dii_body = b""
        with time_fetch(self.SOURCE_NAME):
            try:
                body, status = await fetch_bytes(
                    url,
                    referer=f"{NSE_WWW}/reports/fii-dii",
                    extra_headers={"Accept": "application/json"},
                    archive_as=("fii_dii", target_date, "fii_dii.json"),
                )
                SOURCE_FETCH.labels(source=self.SOURCE_NAME, status=str(status)).inc()
                return body, url, status
            except Exception as nse_exc:  # noqa: BLE001
                SOURCE_FETCH.labels(source=self.SOURCE_NAME, status="error").inc()
                logger.warning(
                    "fii_dii: NSE fetch failed (%s) — falling back to NSDL",
                    nse_exc,
                )
                return await self._fetch_nsdl(target_date, nse_exc)

    async def _fetch_nsdl(self, target_date: Optional[date],
                          nse_exc: BaseException) -> tuple[bytes, str, int]:
        """Fetch NSDL's FPI + DII daily trends as the fallback source.

        Both pages are required: FPI carries the foreign leg, DII the
        domestic one. If NSDL also fails, re-raise the *NSE* error — that
        is the primary source and the more actionable failure.
        """
        with time_fetch(NSDL_FPI_SOURCE):
            try:
                fpi_body, status = await nsdl_fetch_bytes(NSDL_FPI_LATEST)
                SOURCE_FETCH.labels(
                    source=NSDL_FPI_SOURCE, status=str(status)).inc()
            except Exception:  # noqa: BLE001
                SOURCE_FETCH.labels(source=NSDL_FPI_SOURCE, status="error").inc()
                logger.exception("fii_dii: NSDL FPI fallback also failed")
                raise nse_exc from None
        # The DII leg is best-effort: a missing DII page still leaves a
        # usable FPI-only day rather than failing the whole run.
        try:
            self._nsdl_dii_body, dii_status = await nsdl_fetch_bytes(
                NSDL_DII_LATEST)
            SOURCE_FETCH.labels(
                source=NSDL_DII_SOURCE, status=str(dii_status)).inc()
        except Exception:  # noqa: BLE001
            SOURCE_FETCH.labels(source=NSDL_DII_SOURCE, status="error").inc()
            logger.warning("fii_dii: NSDL DII leg unavailable — FPI only")
            self._nsdl_dii_body = b""
        self._used_nsdl = True
        return fpi_body, NSDL_FPI_LATEST, status

    def parse(self, body: bytes, target_date: Optional[date]) -> list[dict]:
        # Use today's date as fallback if response entries lack a date field.
        from datetime import date as _date
        fallback = (target_date or _date.today()).isoformat()
        if not self._used_nsdl:
            return parse_fii_dii(body, fallback)
        rows = [{**r, "source": NSDL_FPI_SOURCE}
                for r in parse_nsdl_fpi(body, fallback)]
        if self._nsdl_dii_body:
            rows += [{**r, "source": NSDL_DII_SOURCE}
                     for r in parse_nsdl_dii(self._nsdl_dii_body, fallback)]
        logger.info("fii_dii: parsed %d row(s) from NSDL", len(rows))
        return rows

    def validate(self, rows: list[dict]) -> tuple[list[dict], int]:
        kept, dropped = [], 0
        for r in rows:
            if not (r["category"] and r["segment"] and r["as_of_date"]):
                dropped += 1
                continue
            kept.append(r)
        return kept, dropped

    async def persist(self, rows: list[dict], run: JobRun) -> int:
        inserted = await upsert_fii_dii(rows, run.run_id)
        bus = get_bus()
        for r in rows:
            payload = {**r,
                       "source": r.get("source") or self.SOURCE_NAME,
                       "source_run_id": str(run.run_id)}
            await bus.publish(
                self.KAFKA_TOPIC,
                key=f"{r['as_of_date']}|{r['category']}|{r['segment']}",
                value=payload,
                schema_name=self.AVRO_SCHEMA,
            )
        return inserted


async def run(target_date: date) -> uuid.UUID:
    job = await FiiDiiIngester().run(target_date)
    return job.run_id
