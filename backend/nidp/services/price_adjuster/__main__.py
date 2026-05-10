"""python -m nidp.services.price_adjuster [--since YYYY-MM-DD] [--symbols X,Y]

Daily Cloud Run job: defaults to last 30 days of incremental adjustment.
Pass --since 1900-01-01 for a full historical rebuild (one-shot only).
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import date, timedelta

from nidp.shared.derived_run import run_with_job_log
from nidp.shared.logging_setup import setup_logging
from nidp.shared.storage.pg import close_pool
from .service import run

DEFAULT_SINCE_DAYS = 30


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--since", help="ISO date; default = today - 30d. "
                                   "Pass 1900-01-01 for full rebuild.")
    p.add_argument("--symbols", help="comma-separated subset; default = all")
    p.add_argument("--no-dividends", action="store_true",
                   help="skip total-return calc (faster)")
    a = p.parse_args()
    setup_logging(service="price_adjuster")

    if a.since:
        since = date.fromisoformat(a.since)
    else:
        since = date.today() - timedelta(days=DEFAULT_SINCE_DAYS)

    symbols = [s.strip().upper() for s in a.symbols.split(",")] if a.symbols else None

    async def _run() -> object:
        try:
            return await run_with_job_log(
                "price_adjuster",
                run,
                since=since,
                symbols=symbols,
                include_dividends=not a.no_dividends,
                rows_inserted_attr="rows_written",
            )
        finally:
            await close_pool()

    report = asyncio.run(_run())
    print(report.as_dict())


if __name__ == "__main__":
    main()
