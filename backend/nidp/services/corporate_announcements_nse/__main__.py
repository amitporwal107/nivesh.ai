"""python -m nidp.services.corporate_announcements_nse [--date YYYY-MM-DD]

Thin wrapper around the shared `corporate_announcements` package that
pins source='nse' and registers run-status to nidp.job_log via JobRun
so the NIDP UI doesn't show "never ran".
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import date, datetime

from nidp.shared.derived_run import run_with_job_log
from nidp.shared.logging_setup import setup_logging
from nidp.shared.storage.pg import close_pool
from nidp.services.corporate_announcements.service import run_once


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


async def _runner(target: date) -> None:
    try:
        await run_with_job_log(
            "corporate_announcements_nse",
            run_once,
            "nse",
            target,
            target_date=target,
        )
    finally:
        await close_pool()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--date", type=_parse_date, default=None,
                   help="Trading date (yyyy-mm-dd). Defaults to today.")
    a = p.parse_args()
    setup_logging(service="corporate_announcements_nse")
    target = a.date or date.today()
    asyncio.run(_runner(target))


if __name__ == "__main__":
    main()
