"""CLI entry point for the Technical Indicator Engine.

Usage examples:

  # Compute for yesterday (default)
  python -m nidp.services.technical_indicator_engine

  # Compute for a specific date
  python -m nidp.services.technical_indicator_engine --date 2026-05-11

  # Backfill last 30 trading days
  python -m nidp.services.technical_indicator_engine --backfill-days 30

  # Backfill a date range
  python -m nidp.services.technical_indicator_engine --from 2026-01-01 --to 2026-05-11

  # Only specific symbols (comma-separated)
  python -m nidp.services.technical_indicator_engine --date 2026-05-11 --symbols RELIANCE,TCS,INFY

Environment variables:
  NIDP_POSTGRES_URL   asyncpg DSN for the NIDP warehouse (required)
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
from .service import compute_date_range, compute_for_date, create_pool

logger = logging.getLogger(__name__)


def _yesterday() -> date:
    return date.today() - timedelta(days=1)


def _parse_date(s: str) -> date:
    return date.fromisoformat(s)


async def _main(args: argparse.Namespace) -> int:
    url = os.environ.get("NIDP_POSTGRES_URL") or os.environ.get("POSTGRES_URL")
    if not url:
        logger.error("NIDP_POSTGRES_URL environment variable is not set")
        return 1

    only = [s.strip().upper() for s in args.symbols.split(",")] if args.symbols else None

    pool = await create_pool(url)
    try:
        if args.backfill_days:
            to_date = args.date or _yesterday()
            from_date = to_date - timedelta(days=args.backfill_days)
            logger.info("ti_engine_backfill_range", from_date=str(from_date), to_date=str(to_date))
            reports = await compute_date_range(pool, from_date, to_date, only_symbols=only)
            summary = {
                "dates_processed": len(reports),
                "total_rows_upserted": sum(r.rows_upserted for r in reports),
                "total_errors": sum(len(r.errors) for r in reports),
                "reports": [r.as_dict() for r in reports if r.rows_upserted > 0],
            }
            print(json.dumps(summary, indent=2, default=str))
            return 0

        if args.from_date and args.to_date:
            reports = await compute_date_range(pool, args.from_date, args.to_date, only_symbols=only)
            summary = {
                "dates_processed": len(reports),
                "total_rows_upserted": sum(r.rows_upserted for r in reports),
                "total_errors": sum(len(r.errors) for r in reports),
            }
            print(json.dumps(summary, indent=2, default=str))
            return 0

        # Single date
        target = args.date or _yesterday()
        report = await run_with_job_log(
            "technical_indicator_engine",
            compute_for_date,
            pool, target,
            target_date=target,
            rows_inserted_attr="rows_upserted",
            only_symbols=only,
        )
        print(json.dumps(report.as_dict(), indent=2, default=str))
        return 0 if not report.errors else 2

    finally:
        await pool.close()
        await close_shared_pool()


def main() -> None:
    setup_logging(service="technical_indicator_engine")
    parser = argparse.ArgumentParser(description="Nivesh Technical Indicator Engine")
    parser.add_argument("--date", type=_parse_date, default=None,
                        help="Target date (YYYY-MM-DD). Default: yesterday.")
    parser.add_argument("--from", dest="from_date", type=_parse_date, default=None,
                        help="Start of date range (inclusive).")
    parser.add_argument("--to", dest="to_date", type=_parse_date, default=None,
                        help="End of date range (inclusive).")
    parser.add_argument("--backfill-days", type=int, default=0,
                        help="Backfill last N calendar days ending at --date (or yesterday).")
    parser.add_argument("--symbols", type=str, default=None,
                        help="Comma-separated list of symbols. Default: all EQ series.")
    parser.add_argument("--batch-size", type=int, default=100,
                        help="Symbols per DB batch. Default: 100.")
    args = parser.parse_args()

    sys.exit(asyncio.run(_main(args)))


if __name__ == "__main__":
    main()
