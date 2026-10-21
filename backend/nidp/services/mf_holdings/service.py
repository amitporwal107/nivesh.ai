"""nidp-mf-holdings orchestrator.

Walks per-AMC adapters for a target as_of_month (defaults to last
calendar month — SEBI mandates M+10 disclosure, so today's run targets
the previous month's portfolio).

Concurrency: one AMC at a time. Holdings ingest is monthly, not
latency-sensitive, and per-AMC sites differ in how fragile they are
under burst load.

Each AMC is written and ledgered as it is fetched (see ingest.ingest_amc), rather than
accumulated into one end-of-run batch. That makes a partial month explicit in
nidp.mf_holdings_coverage instead of hiding behind a single "PARTIAL" job_log row, and lets
backfill.py reuse exactly the same unit of work.
"""
from __future__ import annotations

import logging
import uuid
from datetime import date
from typing import Optional, Sequence

import aiohttp

from nidp.shared.config import DEFAULT_UA, HTTP_TIMEOUT_S, MF_AMC_TOP10, MF_AMC_TIER2, MF_AMC_TIER3
from nidp.shared.logging_setup import bind_context
from nidp.shared.metrics import (
    INGESTER_ROWS, INGESTER_RUNS, time_ingester,
)
from nidp.shared.storage.job_log import JobRun
from nidp.shared.validation import run_validation as _run_validation

from .ingest import ingest_amc

logger = logging.getLogger(__name__)

SERVICE_NAME = "mf_holdings"

ALL_AMCS: tuple[str, ...] = (*MF_AMC_TOP10, *MF_AMC_TIER2, *MF_AMC_TIER3)


def _previous_month_first(d: date) -> date:
    if d.month == 1:
        return date(d.year - 1, 12, 1)
    return date(d.year, d.month - 1, 1)


async def run(
    target_date: Optional[date] = None,
    amcs: Optional[Sequence[str]] = None,
) -> uuid.UUID:
    """target_date semantics:
        - None             → last calendar month
        - first-of-month   → that month
        - any other date   → snapped to first-of-month

    amcs: restrict the run to these adapter keys (default: every configured AMC).
    """
    bind_context(service=SERVICE_NAME)
    if target_date is None:
        as_of_month = _previous_month_first(date.today())
    else:
        as_of_month = date(target_date.year, target_date.month, 1)

    amc_list = list(amcs) if amcs else list(ALL_AMCS)

    async with JobRun(ingester=SERVICE_NAME, target_date=as_of_month) as run:
        bind_context(run_id=str(run.run_id))
        timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT_S)
        headers = {"User-Agent": DEFAULT_UA}

        rows_written = 0
        adapters_empty = 0
        adapters_failed = 0
        adapters_ok = 0

        with time_ingester(SERVICE_NAME):
            async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                for amc_id in amc_list:
                    res = await ingest_amc(session, amc_id, as_of_month, run.run_id)
                    if res.ok:
                        adapters_ok += 1
                        rows_written += res.rows_written
                    elif res.status == "EMPTY":
                        adapters_empty += 1
                    else:
                        adapters_failed += 1

            run.rows_fetched = rows_written
            run.rows_inserted = rows_written
            run.metadata["adapters_ok"] = adapters_ok
            run.metadata["adapters_empty"] = adapters_empty
            run.metadata["adapters_failed"] = adapters_failed

            INGESTER_ROWS.labels(service=SERVICE_NAME, kind="fetched").inc(rows_written)
            INGESTER_ROWS.labels(service=SERVICE_NAME, kind="inserted").inc(rows_written)

            # Validation runs against the persisted rows.
            validation = await _run_validation(
                ingester=SERVICE_NAME,
                target_date=as_of_month,
                job_run_id=run.run_id,
            )
            run.metadata["validation_status"] = validation.status
            run.metadata["findings_count"] = validation.findings_count
            run.metadata["has_block"] = validation.has_block

            # Status decision (2026-05-21 reclassification):
            #   OK       — every adapter delivered AND validation green
            #   PARTIAL  — some adapters delivered, some empty/failed
            #   FAILED   — zero rows produced. Reflects reality instead of
            #              silently saying "PARTIAL/PASSED" while writing 0 rows
            #              (the AMC-URL-rot loophole that hid mf_holdings being
            #              empty for weeks — see project_amc_scrapers_broken.md).
            # Which AMC-months are absent is now in nidp.mf_holdings_coverage, and
            # backfill.py --only-missing is what heals them.
            if rows_written == 0:
                final = "FAILED"
            elif adapters_empty or adapters_failed or validation.has_block:
                final = "PARTIAL"
            else:
                final = "OK"
            await run.finalize(final, error_message=(
                f"ok={adapters_ok}/{len(amc_list)} empty={adapters_empty} "
                f"failed={adapters_failed} rows={rows_written} "
                f"validation={validation.status}"
                if final != "OK" else None
            ))
            INGESTER_RUNS.labels(service=SERVICE_NAME, status=final).inc()
            return run.run_id
