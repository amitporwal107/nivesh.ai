"""CLI runner for portfolio_holdings_sync.

Usage:
  python -m nidp.services.portfolio_holdings_sync              # sync latest
  python -m nidp.services.portfolio_holdings_sync --date 2026-05-12
  python -m nidp.services.portfolio_holdings_sync --date 2026-04-30 --run-intel

After syncing holdings into NIDP, optionally kick off portfolio_intelligence_sync
(the security-map + analytics pass) by passing --run-intel.
"""
from __future__ import annotations

import asyncio
import argparse
import logging
from datetime import date, datetime

from nidp.shared.derived_run import run_with_job_log
from nidp.shared.logging_setup import setup_logging
from nidp.shared.storage.pg import close_pool

from .service import run


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


async def _runner(target_date: date | None, run_intel: bool) -> None:
    try:
        result = await run_with_job_log(
            "portfolio_holdings_sync",
            run,
            target_date,
            target_date=target_date,
        )
        logging.getLogger(__name__).info("sync complete: %s", result)

        if run_intel and (result.get("synced", 0) > 0):
            from nidp.services.portfolio_intelligence_sync.service import run as run_intelligence
            intel = await run_intelligence(target_date=target_date)
            logging.getLogger(__name__).info("intelligence pass complete: %s", intel)

    finally:
        await close_pool()


def main() -> None:
    p = argparse.ArgumentParser(description="Sync Nivesh portfolio holdings → NIDP")
    p.add_argument("--date", type=_parse_date, default=None,
                   help="Snapshot date to sync (YYYY-MM-DD). Default = latest per client.")
    p.add_argument("--run-intel", action="store_true",
                   help="Also run portfolio_intelligence_sync after holdings are loaded.")
    args = p.parse_args()
    setup_logging(service="portfolio_holdings_sync")
    asyncio.run(_runner(args.date, args.run_intel))


if __name__ == "__main__":
    main()
