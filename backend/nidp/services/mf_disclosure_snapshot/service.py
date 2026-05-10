"""nidp-mf-disclosure-snapshot — orchestrator.

Walks the per-AMC adapter registry, accumulates snapshot rows, persists
them under (scheme_code, snapshot_date), and runs the diff to emit
mf_scheme_events. AMCs without an implemented adapter are skipped
with a warning; the run finalises PARTIAL when any adapter is missing
or fails.
"""
from __future__ import annotations

import logging
import uuid
from datetime import date
from typing import Optional

import aiohttp

from nidp.shared.config import DEFAULT_UA, HTTP_TIMEOUT_S, MF_AMC_TOP10
from nidp.shared.logging_setup import bind_context
from nidp.shared.metrics import (
    INGESTER_ROWS, INGESTER_RUNS, time_ingester,
)
from nidp.shared.storage.job_log import JobRun

from .amc_dispatch import ADAPTERS
from .diff import emit_events_from_snapshot
from .writer import upsert_snapshot

logger = logging.getLogger(__name__)

SERVICE_NAME = "mf_disclosure_snapshot"


async def run(target_date: Optional[date] = None) -> uuid.UUID:
    bind_context(service=SERVICE_NAME)
    snapshot_date = target_date or date.today()

    async with JobRun(ingester=SERVICE_NAME, target_date=snapshot_date) as run:
        bind_context(run_id=str(run.run_id))
        timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT_S)
        headers = {"User-Agent": DEFAULT_UA}

        all_rows: list[dict] = []
        adapters_missing = 0
        adapters_failed = 0

        with time_ingester(SERVICE_NAME):
            async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                from nidp.shared.archive import archive_raw
                import json as _json
                for amc_id in MF_AMC_TOP10:
                    fn = ADAPTERS.get(amc_id)
                    if fn is None:
                        adapters_missing += 1
                        logger.warning("no adapter registered for amc_id=%s", amc_id)
                        continue
                    try:
                        rows = await fn(session)
                    except Exception as e:                              # noqa: BLE001
                        adapters_failed += 1
                        logger.warning("amc=%s adapter raised: %s: %s",
                                       amc_id, type(e).__name__, e)
                        continue
                    if not rows:
                        # Stub adapters return [] — counted as missing.
                        adapters_missing += 1
                        continue
                    try:
                        archive_raw(SERVICE_NAME, snapshot_date,
                                    f"{amc_id}.parsed.json",
                                    _json.dumps(rows, default=str).encode("utf-8"))
                    except Exception:                                    # noqa: BLE001
                        pass
                    all_rows.extend(rows)

            n_rows = await upsert_snapshot(all_rows, snapshot_date, run.run_id)
            n_events = await emit_events_from_snapshot(snapshot_date, run.run_id)

            run.rows_fetched = len(all_rows)
            run.rows_inserted = n_rows
            run.metadata["events_emitted"] = n_events
            run.metadata["adapters_missing"] = adapters_missing
            run.metadata["adapters_failed"] = adapters_failed

            INGESTER_ROWS.labels(service=SERVICE_NAME, kind="fetched").inc(len(all_rows))
            INGESTER_ROWS.labels(service=SERVICE_NAME, kind="inserted").inc(n_rows)

            partial = adapters_missing > 0 or adapters_failed > 0
            final = "PARTIAL" if partial else "OK"
            await run.finalize(final, error_message=(
                f"missing={adapters_missing} failed={adapters_failed}" if partial else None
            ))
            INGESTER_RUNS.labels(service=SERVICE_NAME, status=final).inc()
            return run.run_id
