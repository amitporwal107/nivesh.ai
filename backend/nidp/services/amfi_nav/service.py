"""nidp-amfi-nav ingester.

AMFI publishes a single pipe-delimited NAV file at ~22:30 IST daily.
We download, parse, and upsert into mf_nav_daily + mf_scheme_master in
one transaction (see writer.py).

Multi-output ingester (NAV + scheme_master), so we override
BaseIngester.run() rather than threading both outputs through the
single-list contract — same pattern as index_constituents.

AMFI is bot-friendly (unlike NSE archives), so this works from the
default sandbox.
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone
from typing import Optional

import aiohttp

from nidp.shared.bus import get_bus
from nidp.shared.config import AMFI_NAV_ALL_URL, DEFAULT_UA, HTTP_TIMEOUT_S
from nidp.shared.ingester_base import BaseIngester
from nidp.shared.logging_setup import bind_context
from nidp.shared.metrics import (
    INGESTER_ROWS, INGESTER_RUNS, SOURCE_FETCH, time_fetch, time_ingester,
)
from nidp.shared.write_target import upsert_target_problem
from nidp.shared.storage.job_log import JobRun
from nidp.shared.storage.raw_archive import store as store_raw
from nidp.shared.validation import run_validation as _run_validation

from .parser import parse_nav_all
from .writer import SOURCE_NAME, upsert_nav_and_master

logger = logging.getLogger(__name__)

SERVICE_NAME = "amfi_nav"


class AmfiNavIngester(BaseIngester):
    SERVICE_NAME = SERVICE_NAME
    SOURCE_NAME = SOURCE_NAME
    KAFKA_TOPIC = "nidp.mf_nav_daily.v1"
    AVRO_SCHEMA = "mf_nav_daily_v1"
    SCHEME_KAFKA_TOPIC = "nidp.mf_scheme_master.v1"
    SCHEME_AVRO_SCHEMA = "mf_scheme_master_v1"

    # Abstract methods are required by BaseIngester but unused — we
    # override run() with our own loop.
    # nidp.index_eod / nidp.mf_nav_daily are pass-through VIEWS over FDW
    # foreign tables in some environments, which no upsert can target.
    # Detect it up front and skip with a real reason instead of failing
    # identically forever. See nidp/shared/write_target.py.
    _write_target = "nidp.mf_nav_daily"
    _target_problem = None

    async def _check_write_target(self) -> bool:
        self._target_problem = await upsert_target_problem(self._write_target)
        if self._target_problem:
            logger.warning("%s: %s", self.SERVICE_NAME, self._target_problem)
            return False
        return True

    async def fetch(self, target_date): raise NotImplementedError("multi-output ingester")
    def parse(self, body, target_date): raise NotImplementedError("multi-output ingester")
    async def persist(self, rows, run): raise NotImplementedError("multi-output ingester")

    async def run(self, target_date: Optional[date] = None) -> JobRun:
        as_of = target_date or date.today()
        bind_context(service=self.SERVICE_NAME, target_date=as_of.isoformat())

        async with JobRun(ingester=self.SERVICE_NAME, target_date=as_of) as run:
            bind_context(run_id=str(run.run_id))

            # No write-target guard here any more. nidp.mf_nav_daily may still
            # be a pass-through VIEW over an FDW foreign table (no unique
            # constraint, so no upsert can target it), but writer.py now
            # resolves the NAV table at run time and falls back to
            # nidp.mf_nav_daily_local — a real table with the same columns and
            # the same (scheme_code, nav_date, source) primary key. Skipping
            # here would throw away a perfectly good AMFI fetch for a problem
            # the writer already handles.
            bus = get_bus()

            with time_ingester(self.SERVICE_NAME):
                # 1. Fetch
                url = AMFI_NAV_ALL_URL
                timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT_S)
                headers = {"User-Agent": DEFAULT_UA, "Accept": "text/plain,*/*"}
                with time_fetch(self.SOURCE_NAME):
                    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as s:
                        async with s.get(url) as resp:
                            body = await resp.read()
                            http_status = resp.status
                            SOURCE_FETCH.labels(
                                source=self.SOURCE_NAME, status=str(http_status),
                            ).inc()
                run.source_url = url

                if not body or http_status != 200:
                    await run.finalize("SKIPPED",
                                       error_message=f"empty body / HTTP {http_status}")
                    INGESTER_RUNS.labels(
                        service=self.SERVICE_NAME, status="SKIPPED",
                    ).inc()
                    return run

                # 2. Archive raw — both the legacy store_raw (DB-indexed,
                # backend-pluggable) AND the new flat-file archive
                # (/opt/nidp/archive/<ingester>/<date>/<filename>) that
                # the admin console exposes for download.
                from nidp.shared.archive import archive_raw as _archive_raw
                _archive_raw(self.SERVICE_NAME, as_of, "NAVAll.txt", body)
                await store_raw(
                    ingester=self.SERVICE_NAME,
                    target_date=as_of,
                    source_url=url,
                    body=body,
                    http_status=http_status,
                    content_type="text/plain",
                    metadata={"size": len(body)},
                )

                # 3. Parse
                nav_rows, scheme_rows = parse_nav_all(body)
                run.rows_fetched = len(nav_rows)
                INGESTER_ROWS.labels(
                    service=self.SERVICE_NAME, kind="fetched",
                ).inc(len(nav_rows))

                if not nav_rows:
                    await run.finalize("SKIPPED",
                                       error_message="no NAV rows parsed")
                    INGESTER_RUNS.labels(
                        service=self.SERVICE_NAME, status="SKIPPED",
                    ).inc()
                    return run

                # 4. Persist (single transaction inside writer)
                nav_n, scheme_n = await upsert_nav_and_master(
                    nav_rows, scheme_rows, run.run_id,
                )
                run.rows_inserted = nav_n
                INGESTER_ROWS.labels(
                    service=self.SERVICE_NAME, kind="inserted",
                ).inc(nav_n)

                # 5. Validate persisted facts
                validation = await _run_validation(
                    ingester=self.SERVICE_NAME,
                    target_date=as_of,
                    job_run_id=run.run_id,
                )
                run.metadata["validation_id"] = str(validation.validation_id)
                run.metadata["validation_status"] = validation.status
                run.metadata["findings_count"] = validation.findings_count
                run.metadata["has_block"] = validation.has_block
                run.metadata["scheme_master_upserted"] = scheme_n

                # 6. Emit completion event (suppressed on BLOCK)
                if not validation.has_block:
                    payload = {
                        "service": self.SERVICE_NAME,
                        "source": self.SOURCE_NAME,
                        "run_id": str(run.run_id),
                        "target_date": as_of.isoformat(),
                        "rows_inserted": nav_n,
                        "completed_at": datetime.now(timezone.utc).isoformat(),
                    }
                    await bus.publish(
                        self.INGESTION_COMPLETED_TOPIC,
                        key=str(run.run_id),
                        value=payload,
                        schema_name=self.INGESTION_COMPLETED_SCHEMA,
                        headers={"service": self.SERVICE_NAME},
                    )
                    await bus.flush(60.0)
                else:
                    logger.error(
                        "amfi_nav validation BLOCKED — completion event "
                        "SUPPRESSED (run_id=%s)", run.run_id,
                    )

                final = "PARTIAL" if validation.has_block else "OK"
                await run.finalize(final)
                INGESTER_RUNS.labels(
                    service=self.SERVICE_NAME, status=final,
                ).inc()
                return run


async def run(target_date: Optional[date] = None) -> uuid.UUID:
    job = await AmfiNavIngester().run(target_date)
    return job.run_id
