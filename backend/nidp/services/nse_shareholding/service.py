"""nidp-nse-shareholding service.

Same fetch-list-then-fan-out pattern as nse_financials. Different
list endpoint, different XBRL taxonomy, single output row per filing.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import uuid
from datetime import date
from typing import Optional

from nidp.shared.bus import get_bus
from nidp.shared.config import (
    NSE_SHAREHOLDING_LIST_URL,
    NSE_WWW,
)
from nidp.shared.ingester_base import BaseIngester
from nidp.shared.metrics import SOURCE_FETCH, time_fetch
from nidp.shared.sources.nse_fetcher import fetch_bytes
from nidp.shared.storage.job_log import JobRun

from .parser import parse_filing_list, parse_xbrl_document
from .writer import SOURCE_NAME, upsert_shareholding

logger = logging.getLogger(__name__)

_XBRL_FETCH_CONCURRENCY = 4
_MAX_FILINGS_PER_RUN = 200


class NseShareholdingIngester(BaseIngester):
    SERVICE_NAME = "nse_shareholding"
    SOURCE_NAME = SOURCE_NAME
    KAFKA_TOPIC = "nidp.shareholding_pattern.v1"
    AVRO_SCHEMA = "shareholding_pattern_v1"

    async def fetch(self, target_date: Optional[date]) -> tuple[bytes, str, int]:
        list_url = NSE_SHAREHOLDING_LIST_URL
        with time_fetch(self.SOURCE_NAME):
            try:
                list_body, status = await fetch_bytes(
                    list_url,
                    referer=f"{NSE_WWW}/companies-listing/corporate-filings-shareholding-pattern",
                    extra_headers={"Accept": "application/json"},
                    archive_as=("nse_shareholding", target_date, "shareholding_index.json"),
                )
                SOURCE_FETCH.labels(source=self.SOURCE_NAME, status=str(status)).inc()
            except Exception:
                SOURCE_FETCH.labels(source=self.SOURCE_NAME, status="error").inc()
                raise

        manifests = parse_filing_list(list_body)[:_MAX_FILINGS_PER_RUN]
        if not manifests:
            payload = {"manifests": [], "xbrl_docs": {}}
            return json.dumps(payload).encode("utf-8"), list_url, status

        sem = asyncio.Semaphore(_XBRL_FETCH_CONCURRENCY)
        unique_urls = sorted({m["xbrl_url"] for m in manifests if m.get("xbrl_url")})
        xbrl_docs: dict[str, str] = {}

        async def _one(url: str) -> None:
            async with sem:
                try:
                    body, st = await fetch_bytes(
                        url,
                        referer=f"{NSE_WWW}/companies-listing/corporate-filings-shareholding-pattern",
                        archive_as=("nse_shareholding", target_date, f"xbrl/{url.rsplit('/', 1)[-1]}"),
                    )
                    if st == 200 and body:
                        xbrl_docs[url] = base64.b64encode(body).decode("ascii")
                    SOURCE_FETCH.labels(source=self.SOURCE_NAME, status=str(st)).inc()
                except Exception as e:                                    # noqa: BLE001
                    logger.warning("XBRL fetch failed %s: %s", url, e)
                    SOURCE_FETCH.labels(source=self.SOURCE_NAME, status="error").inc()

        await asyncio.gather(*[_one(u) for u in unique_urls])

        payload = {"manifests": manifests, "xbrl_docs": xbrl_docs}
        return json.dumps(payload).encode("utf-8"), list_url, status

    def parse(self, body: bytes, target_date: Optional[date]) -> list[dict]:
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            logger.error("synthetic blob decode failed: %s", e)
            return []

        manifests = payload.get("manifests", [])
        xbrl_docs = payload.get("xbrl_docs", {})

        rows: list[dict] = []
        for manifest in manifests:
            url = manifest.get("xbrl_url")
            if not url or url not in xbrl_docs:
                continue
            try:
                xbrl_bytes = base64.b64decode(xbrl_docs[url])
            except Exception:                                            # noqa: BLE001
                continue
            try:
                rows.extend(parse_xbrl_document(xbrl_bytes, manifest))
            except Exception:                                            # noqa: BLE001
                logger.exception("XBRL parse failed for %s", manifest.get("symbol"))
                continue
        return rows

    def validate(self, rows: list[dict]) -> tuple[list[dict], int]:
        kept, dropped = [], 0
        for r in rows:
            if not (r.get("symbol") and r.get("period_end")):
                dropped += 1
                continue
            # Drop rows with no percent facts
            if (r.get("promoter_pct") is None
                    and r.get("fii_pct") is None
                    and r.get("mf_pct") is None
                    and r.get("public_pct") is None):
                dropped += 1
                continue
            kept.append(r)
        return kept, dropped

    async def persist(self, rows: list[dict], run: JobRun) -> int:
        inserted = await upsert_shareholding(rows, run.run_id)
        bus = get_bus()
        for r in rows:
            payload = {**r, "source": self.SOURCE_NAME, "source_run_id": str(run.run_id)}
            await bus.publish(
                self.KAFKA_TOPIC,
                key=f"{r['symbol']}|{r['period_end']}",
                value=payload,
                schema_name=self.AVRO_SCHEMA,
            )
        return inserted


async def run(target_date: Optional[date] = None) -> uuid.UUID:
    job = await NseShareholdingIngester().run(target_date)
    return job.run_id
