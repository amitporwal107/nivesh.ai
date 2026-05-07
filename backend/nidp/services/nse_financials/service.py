"""nidp-nse-financials service.

Two-stage source flow:
  1. Fetch the rolling list of recent financial-results filings from
     NSE's JSON API (`/api/corporates-financial-results?...`).
  2. For each filing with an XBRL link, fetch the XBRL document
     (concurrent, bounded). Parse facts inline.

The combined payload (list JSON + every XBRL body, base64-encoded) is
returned from `fetch()` as one synthetic JSON blob — preserved in the
raw archive for full replay. parse() unwraps the blob and runs
`parse_xbrl_document` against each filing.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import uuid
from datetime import date
from typing import List, Optional

from nidp.shared.bus import get_bus
from nidp.shared.config import (
    NSE_FINANCIALS_LIST_URL_ANNUAL,
    NSE_FINANCIALS_LIST_URL_QUARTERLY,
    NSE_WWW,
)
from nidp.shared.ingester_base import BaseIngester
from nidp.shared.metrics import SOURCE_FETCH, time_fetch
from nidp.shared.sources.nse_fetcher import fetch_bytes
from nidp.shared.storage.job_log import JobRun

from .parser import parse_filing_list, parse_xbrl_document
from .writer import SOURCE_NAME, upsert_financials

logger = logging.getLogger(__name__)

# Bound concurrent XBRL downloads — NSE rate-limits aggressively.
_XBRL_FETCH_CONCURRENCY = 4
# Max filings to fetch per run. The list endpoint returns the rolling
# window; we cap to keep one run bounded. Filings older than the cap
# are picked up next day (PK ON CONFLICT means re-processing is safe).
_MAX_FILINGS_PER_RUN = 200


class NseFinancialsIngester(BaseIngester):
    SERVICE_NAME = "nse_financials"
    SOURCE_NAME = SOURCE_NAME
    KAFKA_TOPIC = "nidp.nse_financials.v1"
    AVRO_SCHEMA = "nse_financials_v1"

    async def fetch(self, target_date: Optional[date]) -> tuple[bytes, str, int]:
        # Pull both quarterly and annual rolling lists. NSE separates
        # them on the public site; we union them here.
        quarterly_url = NSE_FINANCIALS_LIST_URL_QUARTERLY
        annual_url = NSE_FINANCIALS_LIST_URL_ANNUAL

        quarterly_body, quarterly_status = await self._fetch_list(quarterly_url)
        annual_body, annual_status = await self._fetch_list(annual_url)

        manifests = (
            parse_filing_list(quarterly_body) + parse_filing_list(annual_body)
        )[:_MAX_FILINGS_PER_RUN]

        if not manifests:
            logger.warning("no XBRL filings in NSE list response")
            payload = {"manifests": [], "xbrl_docs": {}}
            return json.dumps(payload).encode("utf-8"), quarterly_url, quarterly_status

        # Concurrent XBRL fetches. URL-keyed cache so duplicates
        # (rare — a filing on both quarterly and annual lists) only
        # hit NSE once.
        sem = asyncio.Semaphore(_XBRL_FETCH_CONCURRENCY)
        unique_urls = sorted({m["xbrl_url"] for m in manifests if m.get("xbrl_url")})
        xbrl_docs: dict[str, str] = {}

        async def _one(url: str) -> None:
            async with sem:
                try:
                    body, status = await fetch_bytes(
                        url,
                        referer=f"{NSE_WWW}/companies-listing/corporate-filings-financial-results",
                    )
                    if status == 200 and body:
                        # base64 to keep the synthetic JSON portable
                        # across raw-archive backends (some treat the
                        # blob as text)
                        xbrl_docs[url] = base64.b64encode(body).decode("ascii")
                    SOURCE_FETCH.labels(source=self.SOURCE_NAME, status=str(status)).inc()
                except Exception as e:                                    # noqa: BLE001
                    logger.warning("XBRL fetch failed %s: %s", url, e)
                    SOURCE_FETCH.labels(source=self.SOURCE_NAME, status="error").inc()

        await asyncio.gather(*[_one(u) for u in unique_urls])

        payload = {"manifests": manifests, "xbrl_docs": xbrl_docs}
        return json.dumps(payload).encode("utf-8"), quarterly_url, quarterly_status

    async def _fetch_list(self, url: str) -> tuple[bytes, int]:
        with time_fetch(self.SOURCE_NAME):
            try:
                body, status = await fetch_bytes(
                    url,
                    referer=f"{NSE_WWW}/companies-listing/corporate-filings-financial-results",
                    extra_headers={"Accept": "application/json"},
                )
                SOURCE_FETCH.labels(source=self.SOURCE_NAME, status=str(status)).inc()
                return body, status
            except Exception:
                SOURCE_FETCH.labels(source=self.SOURCE_NAME, status="error").inc()
                raise

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
            # Drop rows with zero extracted facts at the gate, then
            # the WARN validator flags any that slipped through.
            if (r.get("revenue_from_ops_cr") is None
                    and r.get("pat_cr") is None
                    and r.get("eps_basic") is None
                    and r.get("interest_earned_cr") is None):
                dropped += 1
                continue
            kept.append(r)
        return kept, dropped

    async def persist(self, rows: list[dict], run: JobRun) -> int:
        inserted = await upsert_financials(rows, run.run_id)
        bus = get_bus()
        for r in rows:
            payload = {**r, "source": self.SOURCE_NAME, "source_run_id": str(run.run_id)}
            # broadcast_at is already an ISO string when present
            await bus.publish(
                self.KAFKA_TOPIC,
                key=f"{r['symbol']}|{r['period_end']}|{int(bool(r['consolidated']))}",
                value=payload,
                schema_name=self.AVRO_SCHEMA,
            )
        return inserted


async def run(target_date: Optional[date] = None) -> uuid.UUID:
    job = await NseFinancialsIngester().run(target_date)
    return job.run_id
