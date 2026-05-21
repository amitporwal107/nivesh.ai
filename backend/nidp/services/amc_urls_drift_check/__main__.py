"""python -m nidp.services.amc_urls_drift_check

Pings every AMC + AMFI URL candidate used by mf_holdings + amfi_central.
Marks the JobRun FAILED if ANY AMC has zero healthy candidates so the
existing job_log → alert pipeline catches URL rot the next morning.

No side effects beyond HTTP GETs and job_log writes.
"""
from __future__ import annotations

import asyncio
import logging

from nidp.services.amc_urls_drift_check.service import run
from nidp.shared.derived_run import run_with_job_log
from nidp.shared.logging_setup import setup_logging
from nidp.shared.storage.pg import close_pool

logger = logging.getLogger(__name__)


async def _main() -> None:
    try:
        await run_with_job_log(
            "amc_urls_drift_check",
            run,
            rows_inserted_attr="healthy_count",
        )
    finally:
        await close_pool()


if __name__ == "__main__":
    setup_logging(service="amc_urls_drift_check")
    asyncio.run(_main())
