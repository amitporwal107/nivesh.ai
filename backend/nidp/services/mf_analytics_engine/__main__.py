"""CLI entry point for the MF Analytics Engine.

Usage:
  python -m nidp.services.mf_analytics_engine
  python -m nidp.services.mf_analytics_engine --date 2026-05-11
  python -m nidp.services.mf_analytics_engine --schemes 119598,101206

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


async def _main(args: argparse.Namespace) -> int:
    url = os.environ.get("NIDP_POSTGRES_URL") or os.environ.get("POSTGRES_URL")
    if not url:
        logger.error("NIDP_POSTGRES_URL not set")
        return 1

    target = args.date or (date.today() - timedelta(days=1))
    only = [s.strip() for s in args.schemes.split(",")] if args.schemes else None

    pool = await create_pool(url)
    try:
        report = await compute_for_date(pool, target, only_schemes=only)
        print(json.dumps(report.as_dict(), indent=2, default=str))
        return 0 if not report.errors else 2
    finally:
        await pool.close()


def main() -> None:
    setup_logging(service="mf_analytics_engine")
    parser = argparse.ArgumentParser(description="Nivesh MF Analytics Engine")
    parser.add_argument("--date", type=date.fromisoformat, default=None,
                        help="Rank date (YYYY-MM-DD). Default: yesterday.")
    parser.add_argument("--schemes", type=str, default=None,
                        help="Comma-separated AMFI scheme codes. Default: all active.")
    args = parser.parse_args()
    sys.exit(asyncio.run(_main(args)))


if __name__ == "__main__":
    main()
