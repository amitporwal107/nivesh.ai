"""macro_calendar service: collect US (FRED, Fed) and India (MoSPI, RBI) release rows and upsert them.

Safe to re-run (idempotent upsert). A source that fails is named in the run's metadata and the others still land:
all sources failing → FAILED, some → PARTIAL. A missing FRED key fails the run immediately."""
from __future__ import annotations

import logging
import os
import uuid
from datetime import date
from typing import List, Optional, Tuple

import aiohttp

from nidp.shared.config import DEFAULT_UA, HTTP_TIMEOUT_S
from nidp.shared.logging_setup import bind_context
from nidp.shared.metrics import INGESTER_ROWS, INGESTER_RUNS, time_ingester
from nidp.shared.storage.job_log import JobRun

from . import fred_us, india
from .writer import upsert_releases

logger = logging.getLogger(__name__)
SERVICE_NAME = "macro_calendar"


def fred_key() -> str:
    """FRED_API_KEY, or the first line of the file named by FRED_API_KEY_FILE (so a key need not sit in argv / env)."""
    key = os.environ.get("FRED_API_KEY", "").strip()
    path = os.environ.get("FRED_API_KEY_FILE", "").strip()
    if not key and path:
        with open(path, encoding="utf-8") as fh:
            key = fh.readline().strip()
    return key


def _need_key() -> str:
    key = fred_key()
    if not key:
        raise RuntimeError("FRED_API_KEY env var is required. Get a free key at "
                           "https://fredaccount.stlouisfed.org/apikeys and add it to the NIDP environment.")
    return key


def _session() -> aiohttp.ClientSession:
    return aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=HTTP_TIMEOUT_S * 2),
                                 headers={"User-Agent": DEFAULT_UA, "Accept": "*/*"})


async def collect(today: Optional[date] = None) -> Tuple[List[dict], List[str]]:
    """All rows and the failure lines, without touching the database (the dry run and the run both use this)."""
    today = today or date.today()
    key = _need_key()
    async with _session() as session:
        us_rows, us_fail = await fred_us.collect_us(session, key, today)
        in_rows, in_fail = await india.collect_india(session, today)
    return us_rows + in_rows, us_fail + in_fail


async def run(target_date: Optional[date] = None) -> uuid.UUID:
    bind_context(service=SERVICE_NAME)
    _need_key()                                    # fail fast, before a job_log row is opened
    async with JobRun(ingester=SERVICE_NAME, target_date=target_date) as run_:
        bind_context(run_id=str(run_.run_id))
        with time_ingester(SERVICE_NAME):
            rows, failures = await collect(target_date)
            inserted = await upsert_releases(rows, run_.run_id)
        run_.rows_fetched = len(rows)
        run_.rows_inserted = inserted
        run_.rows_skipped = len(failures)
        run_.metadata["failures"] = failures
        INGESTER_ROWS.labels(service=SERVICE_NAME, kind="inserted").inc(inserted)
        if failures and not rows:
            await run_.finalize("FAILED", error_message="; ".join(failures)[:500])
            INGESTER_RUNS.labels(service=SERVICE_NAME, status="FAILED").inc()
        elif failures:
            await run_.finalize("PARTIAL")
            INGESTER_RUNS.labels(service=SERVICE_NAME, status="PARTIAL").inc()
        else:
            await run_.finalize("OK")
            INGESTER_RUNS.labels(service=SERVICE_NAME, status="OK").inc()
        return run_.run_id
