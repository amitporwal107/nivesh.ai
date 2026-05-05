"""FRED macro ingester.

Iterates SERIES_CATALOG and fetches each series' CSV from FRED.
Multi-URL ingester pattern (similar to index_constituents): one
JobRun spans all series; per-series failures are isolated.

FRED's fredgraph.csv endpoint:
    https://fred.stlouisfed.org/graph/fredgraph.csv?id={SERIES_ID}
returns full history (no date params). We persist all of it
(append-only, ON CONFLICT no-op for already-stored dates).

Suitable for both initial backfill (one shot) and daily refresh
(re-fetches but only new dates change).
"""
from __future__ import annotations

import logging
import uuid
from datetime import date
from typing import Optional

import aiohttp

from nidp.shared.config import DEFAULT_UA, HTTP_TIMEOUT_S
from nidp.shared.logging_setup import bind_context
from nidp.shared.metrics import (
    INGESTER_ROWS, INGESTER_RUNS, SOURCE_FETCH, time_fetch, time_ingester,
)
from nidp.shared.storage.job_log import JobRun

from .parser import SERIES_CATALOG, parse_fred_csv
from .writer import SOURCE_NAME, upsert_fred

logger = logging.getLogger(__name__)

SERVICE_NAME = "fred_macro"
FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"


async def _fetch_series(session: aiohttp.ClientSession, series_id: str) -> tuple[Optional[bytes], int]:
    url = FRED_CSV_URL.format(series_id=series_id)
    try:
        with time_fetch(SOURCE_NAME):
            async with session.get(url) as resp:
                body = await resp.read()
                SOURCE_FETCH.labels(source=SOURCE_NAME, status=str(resp.status)).inc()
                if resp.status != 200:
                    return None, resp.status
                return body, resp.status
    except Exception:
        SOURCE_FETCH.labels(source=SOURCE_NAME, status="error").inc()
        return None, 0


async def run(target_date: Optional[date] = None) -> uuid.UUID:
    bind_context(service=SERVICE_NAME)
    series_ids = list(SERIES_CATALOG.keys())

    async with JobRun(ingester=SERVICE_NAME, target_date=target_date) as run_:
        bind_context(run_id=str(run_.run_id))
        total_inserted = 0
        total_failed = 0

        with time_ingester(SERVICE_NAME):
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=HTTP_TIMEOUT_S),
                headers={"User-Agent": DEFAULT_UA, "Accept": "text/csv"},
            ) as session:
                for sid in series_ids:
                    body, status = await _fetch_series(session, sid)
                    if not body:
                        logger.warning("FRED series %s: status=%s, skipping", sid, status)
                        total_failed += 1
                        continue
                    try:
                        rows = parse_fred_csv(body, series_id=sid)
                    except Exception as e:                                  # noqa: BLE001
                        logger.warning("FRED series %s parse failed: %s", sid, e)
                        total_failed += 1
                        continue
                    if not rows:
                        logger.info("FRED series %s: no rows", sid)
                        continue
                    inserted = await upsert_fred(rows, run_.run_id)
                    total_inserted += inserted
                    logger.info("  %s: %d rows inserted", sid, inserted)

        run_.rows_fetched = total_inserted + total_failed
        run_.rows_inserted = total_inserted
        run_.rows_skipped = total_failed
        INGESTER_ROWS.labels(service=SERVICE_NAME, kind="inserted").inc(total_inserted)

        if total_failed >= len(series_ids):
            await run_.finalize("FAILED", error_message=f"all {len(series_ids)} FRED series failed")
            INGESTER_RUNS.labels(service=SERVICE_NAME, status="FAILED").inc()
        elif total_failed > 0:
            await run_.finalize("PARTIAL")
            INGESTER_RUNS.labels(service=SERVICE_NAME, status="PARTIAL").inc()
        else:
            await run_.finalize("OK")
            INGESTER_RUNS.labels(service=SERVICE_NAME, status="OK").inc()
        return run_.run_id
