"""python -m nidp.services.v3_scores_engine [--date YYYY-MM-DD] [--domain mf|stock|both]

Computes V3 Quality + Health composite scores for all schemes/symbols that
have primitives on the target date, and upserts into nidp.v3_mf_scores_daily
+ nidp.v3_stock_scores_daily.

Should run after mf_derived_refresh (MF derived columns) and after
fundamental_engine + technical_indicator_engine (stock primitives).
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import date, datetime

from nidp.services.v3_scores_engine.service import run
from nidp.shared.derived_run import run_with_job_log
from nidp.shared.logging_setup import setup_logging
from nidp.shared.storage.pg import close_pool

logger = logging.getLogger(__name__)


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


async def _main() -> None:
    p = argparse.ArgumentParser(description="V3 scores engine — persist Quality + Health")
    p.add_argument("--date", type=_parse_date, default=None, help="Target date (default: today)")
    p.add_argument(
        "--domain", choices=("mf", "stock", "both"), default="both",
        help="Which domain to score (default: both)",
    )
    args = p.parse_args()

    # run_with_job_log captures target_date for JobRun logging but does NOT forward it
    # to coro_fn. Wrap run() so the date is bound before passing to the wrapper.
    _target = args.date
    _domain = args.domain

    async def _run() -> dict:
        return await run(target_date=_target, domain=_domain)

    try:
        await run_with_job_log(
            "v3_scores_engine",
            _run,
            target_date=args.date,
            rows_inserted_attr="rows_written",
        )
    finally:
        await close_pool()


if __name__ == "__main__":
    setup_logging(service="v3_scores_engine")
    asyncio.run(_main())
