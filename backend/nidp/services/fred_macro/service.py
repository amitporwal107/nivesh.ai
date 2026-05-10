"""FRED macro ingester.

Iterates SERIES_CATALOG and fetches each series from the authenticated
FRED API. Multi-URL ingester pattern (similar to index_constituents):
one JobRun spans all series; per-series failures are isolated.

Endpoint:
    https://api.stlouisfed.org/fred/series/observations
        ?series_id={SERIES_ID}&api_key={KEY}&file_type=json

We previously hit the unauthenticated `fredgraph.csv` graph-download
endpoint — FRED started returning HTML/302 to cloud-IP egress, so
every series failed and the validation "all 8 FRED series failed"
fired (job_log 2026-05-06 13:15:01 + 02:36:02). The supported API
endpoint requires an API key but is stable for programmatic use.

Suitable for both initial backfill (one shot) and daily refresh
(re-fetches but only changed values write — ON CONFLICT in writer).
"""
from __future__ import annotations

import logging
import os
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

from .parser import SERIES_CATALOG, parse_fred_observations
from .writer import SOURCE_NAME, upsert_fred

logger = logging.getLogger(__name__)

SERVICE_NAME = "fred_macro"
FRED_API_URL = "https://api.stlouisfed.org/fred/series/observations"


async def _fetch_series(
    session: aiohttp.ClientSession, series_id: str, api_key: str,
) -> tuple[Optional[bytes], int]:
    """Fetch one series. Returns (body, status). On exception, body=None and
    status=0; the exception is logged so failures are debuggable (we used
    to swallow them silently and surface only "all N failed")."""
    params = {"series_id": series_id, "api_key": api_key, "file_type": "json"}
    try:
        with time_fetch(SOURCE_NAME):
            async with session.get(FRED_API_URL, params=params) as resp:
                body = await resp.read()
                SOURCE_FETCH.labels(source=SOURCE_NAME, status=str(resp.status)).inc()
                if resp.status != 200:
                    logger.warning(
                        "FRED %s: HTTP %s, first 200 bytes: %r",
                        series_id, resp.status, body[:200],
                    )
                    return None, resp.status
                return body, resp.status
    except Exception as e:                                              # noqa: BLE001
        SOURCE_FETCH.labels(source=SOURCE_NAME, status="error").inc()
        logger.warning("FRED %s: %s: %s", series_id, type(e).__name__, e)
        return None, 0


async def run(target_date: Optional[date] = None) -> uuid.UUID:
    bind_context(service=SERVICE_NAME)
    api_key = os.environ.get("FRED_API_KEY", "").strip()
    if not api_key:
        # Fail fast — JobRun.__aexit__ records this as FAILED with the
        # exception message, which is far more actionable than "all N failed".
        raise RuntimeError(
            "FRED_API_KEY env var is required. Get a free key at "
            "https://fredaccount.stlouisfed.org/apikeys and store it in "
            "Secret Manager as FRED_API_KEY (mounted by deploy.sh)."
        )

    series_ids = list(SERIES_CATALOG.keys())

    async with JobRun(ingester=SERVICE_NAME, target_date=target_date) as run_:
        bind_context(run_id=str(run_.run_id))
        total_inserted = 0
        total_failed = 0

        with time_ingester(SERVICE_NAME):
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=HTTP_TIMEOUT_S),
                headers={"User-Agent": DEFAULT_UA, "Accept": "application/json"},
            ) as session:
                for sid in series_ids:
                    body, status = await _fetch_series(session, sid, api_key)
                    if not body:
                        total_failed += 1
                        continue
                    # Archive raw FRED JSON per series, per target_date
                    try:
                        from nidp.shared.archive import archive_raw
                        archive_raw(SERVICE_NAME, target_date, f"{sid}.json", body)
                    except Exception:                                          # noqa: BLE001
                        pass
                    try:
                        rows = parse_fred_observations(body, series_id=sid)
                    except Exception as e:                                  # noqa: BLE001
                        logger.warning("FRED %s parse failed: %s: %s",
                                       sid, type(e).__name__, e)
                        total_failed += 1
                        continue
                    if not rows:
                        logger.info("FRED %s: no rows", sid)
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
