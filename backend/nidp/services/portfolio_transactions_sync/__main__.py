"""CLI runner for portfolio_transactions_sync.

Usage:
  python -m nidp.services.portfolio_transactions_sync              # latest
  python -m nidp.services.portfolio_transactions_sync --date 2026-05-12
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import date, datetime

from nidp.shared.derived_run import run_with_job_log
from nidp.shared.logging_setup import setup_logging
from nidp.shared.storage.pg import close_pool

from .service import run


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


async def _runner(target_date: date | None) -> None:
    try:
        result = await run_with_job_log(
            "portfolio_transactions_sync",
            run,
            target_date,
            target_date=target_date,
        )
        logging.getLogger(__name__).info("transactions sync complete: %s", result)
    finally:
        await close_pool()


def main() -> None:
    p = argparse.ArgumentParser(
        description="Sync raw CAS transactions from GCS → NIDP",
    )
    p.add_argument("--date", type=_parse_date, default=None,
                   help="Export-date to sync (YYYY-MM-DD). Default = latest.")
    args = p.parse_args()
    setup_logging(service="portfolio_transactions_sync")
    asyncio.run(_runner(args.date))


if __name__ == "__main__":
    main()
