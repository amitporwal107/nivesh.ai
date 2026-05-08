"""nidp-mf-holdings orchestrator.

Walks per-AMC adapters for a target as_of_month (defaults to last
calendar month — SEBI mandates M+10 disclosure, so today's run targets
the previous month's portfolio).

Concurrency: one AMC at a time. Holdings ingest is monthly, not
latency-sensitive, and per-AMC sites differ in how fragile they are
under burst load.
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
from nidp.shared.validation import run_validation as _run_validation

from .amc_dispatch import ADAPTERS
from .writer import upsert_holdings

logger = logging.getLogger(__name__)

SERVICE_NAME = "mf_holdings"


def _previous_month_first(d: date) -> date:
    if d.month == 1:
        return date(d.year - 1, 12, 1)
    return date(d.year, d.month - 1, 1)


async def run(target_date: Optional[date] = None) -> uuid.UUID:
    """target_date semantics:
        - None             → last calendar month
        - first-of-month   → that month
        - any other date   → snapped to first-of-month
    """
    bind_context(service=SERVICE_NAME)
    if target_date is None:
        as_of_month = _previous_month_first(date.today())
    else:
        as_of_month = date(target_date.year, target_date.month, 1)

    async with JobRun(ingester=SERVICE_NAME, target_date=as_of_month) as run:
        bind_context(run_id=str(run.run_id))
        timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT_S)
        headers = {"User-Agent": DEFAULT_UA}

        all_rows: list[dict] = []
        adapters_missing = 0
        adapters_failed = 0

        with time_ingester(SERVICE_NAME):
            async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                for amc_id in MF_AMC_TOP10:
                    fn = ADAPTERS.get(amc_id)
                    if fn is None:
                        adapters_missing += 1
                        logger.warning("no adapter registered for amc_id=%s", amc_id)
                        continue
                    try:
                        rows = await fn(session, as_of_month)
                    except Exception as e:                              # noqa: BLE001
                        adapters_failed += 1
                        logger.warning("amc=%s adapter raised: %s: %s",
                                       amc_id, type(e).__name__, e)
                        continue
                    if not rows:
                        adapters_missing += 1
                        continue
                    all_rows.extend(rows)

            n = await upsert_holdings(all_rows, run.run_id)

            run.rows_fetched = len(all_rows)
            run.rows_inserted = n
            run.metadata["adapters_missing"] = adapters_missing
            run.metadata["adapters_failed"] = adapters_failed

            INGESTER_ROWS.labels(service=SERVICE_NAME, kind="fetched").inc(len(all_rows))
            INGESTER_ROWS.labels(service=SERVICE_NAME, kind="inserted").inc(n)

            # Validation runs against the persisted rows.
            validation = await _run_validation(
                ingester=SERVICE_NAME,
                target_date=as_of_month,
                job_run_id=run.run_id,
            )
            run.metadata["validation_status"] = validation.status
            run.metadata["findings_count"] = validation.findings_count
            run.metadata["has_block"] = validation.has_block

            partial = adapters_missing > 0 or adapters_failed > 0 or validation.has_block
            final = "PARTIAL" if partial else "OK"
            await run.finalize(final, error_message=(
                f"missing={adapters_missing} failed={adapters_failed} "
                f"validation={validation.status}" if partial else None
            ))
            INGESTER_RUNS.labels(service=SERVICE_NAME, status=final).inc()
            return run.run_id
