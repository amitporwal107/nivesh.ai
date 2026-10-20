"""CLI entry point for the Fundamental Analytics Engine.

Usage:
  python -m nidp.services.fundamental_engine
  python -m nidp.services.fundamental_engine --date 2026-05-11
  python -m nidp.services.fundamental_engine --symbols RELIANCE,TCS,INFY
  python -m nidp.services.fundamental_engine --skip-populate   # if TI already ran populate_extended

Environment:
  NIDP_POSTGRES_URL   asyncpg DSN (required)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import date, timedelta

from nidp.shared.derived_run import run_with_job_log
from nidp.shared.logging_setup import setup_logging
from nidp.shared.storage.pg import close_pool as close_shared_pool
from .service import compute_for_date, create_pool

logger = logging.getLogger(__name__)


async def default_target_date(pool, today: date | None = None) -> date:
    """The date to compute when none is given: the latest date the indicator engine has loaded.

    This engine fills the rows nidp.stock_features_daily already holds, so calendar "yesterday"
    is wrong after a weekend or holiday (Monday 2026-10-19 targeted Sunday: "no rows", nothing
    filled, and the 16 and 19 Oct rows stayed blank). Falls back to yesterday when the table is
    empty or unreadable, and never returns a date after today.
    """
    today = today or date.today()
    try:
        latest = await pool.fetchval("SELECT MAX(as_of_date) FROM nidp.stock_features_daily")
    except Exception as exc:  # noqa: BLE001
        logger.warning("fund_engine_default_date_fallback error=%s", type(exc).__name__)
        latest = None
    if latest is None or latest > today:
        return today - timedelta(days=1)
    return latest


async def _main(args: argparse.Namespace) -> int:
    url = os.environ.get("NIDP_POSTGRES_URL") or os.environ.get("POSTGRES_URL")
    if not url:
        logger.error("NIDP_POSTGRES_URL not set")
        return 1

    only = [s.strip().upper() for s in args.symbols.split(",")] if args.symbols else None

    pool = await create_pool(url)
    try:
        target = args.date or await default_target_date(pool)
        report = await run_with_job_log(
            "fundamental_engine",
            compute_for_date,
            pool, target,
            target_date=target,
            rows_inserted_attr="rows_upserted",
            only_symbols=only,
            skip_populate=args.skip_populate,
        )
        print(json.dumps(report.as_dict(), indent=2, default=str))
        return 0 if not report.errors else 2
    finally:
        await pool.close()
        await close_shared_pool()


def main() -> None:
    setup_logging(service="fundamental_engine")
    parser = argparse.ArgumentParser(description="Nivesh Fundamental Analytics Engine")
    parser.add_argument("--date", type=date.fromisoformat, default=None,
                        help="Target date (YYYY-MM-DD). Default: the latest date in nidp.stock_features_daily.")
    parser.add_argument("--symbols", type=str, default=None,
                        help="Comma-separated symbol filter. Default: all.")
    parser.add_argument("--skip-populate", action="store_true",
                        help="Skip populate_stock_features_extended() call.")
    args = parser.parse_args()
    sys.exit(asyncio.run(_main(args)))


if __name__ == "__main__":
    main()
