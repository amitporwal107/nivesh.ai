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

from nidp.shared.logging_setup import setup_logging
from .service import compute_for_date, create_pool

logger = logging.getLogger(__name__)


def _yesterday() -> date:
    return date.today() - timedelta(days=1)


async def _main(args: argparse.Namespace) -> int:
    url = os.environ.get("NIDP_POSTGRES_URL") or os.environ.get("POSTGRES_URL")
    if not url:
        logger.error("NIDP_POSTGRES_URL not set")
        return 1

    target = args.date or _yesterday()
    only = [s.strip().upper() for s in args.symbols.split(",")] if args.symbols else None

    pool = await create_pool(url)
    try:
        report = await compute_for_date(
            pool, target,
            only_symbols=only,
            skip_populate=args.skip_populate,
        )
        print(json.dumps(report.as_dict(), indent=2, default=str))
        return 0 if not report.errors else 2
    finally:
        await pool.close()


def main() -> None:
    setup_logging()
    parser = argparse.ArgumentParser(description="Nivesh Fundamental Analytics Engine")
    parser.add_argument("--date", type=date.fromisoformat, default=None,
                        help="Target date (YYYY-MM-DD). Default: yesterday.")
    parser.add_argument("--symbols", type=str, default=None,
                        help="Comma-separated symbol filter. Default: all.")
    parser.add_argument("--skip-populate", action="store_true",
                        help="Skip populate_stock_features_extended() call.")
    args = parser.parse_args()
    sys.exit(asyncio.run(_main(args)))


if __name__ == "__main__":
    main()
