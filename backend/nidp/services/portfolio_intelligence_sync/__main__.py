"""Run the portfolio→intelligence sync with JobRun tracking."""
from __future__ import annotations

import asyncio
import argparse
from datetime import date, datetime

from nidp.shared.derived_run import run_with_job_log
from nidp.shared.logging_setup import setup_logging
from nidp.shared.storage.pg import close_pool

from .service import run


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


async def _runner(target_date: date | None) -> None:
    try:
        await run_with_job_log(
            "portfolio_intelligence_sync",
            run,
            target_date,
            target_date=target_date,
        )
    finally:
        await close_pool()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--date", type=_parse_date, default=None,
                   help="Target snapshot_date (YYYY-MM-DD). Default = latest.")
    args = p.parse_args()
    setup_logging(service="portfolio_intelligence_sync")
    asyncio.run(_runner(args.date))


if __name__ == "__main__":
    main()
