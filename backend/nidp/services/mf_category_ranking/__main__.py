"""CLI entry point for the MF Category Ranking service.

Usage:
  python -m nidp.services.mf_category_ranking
  python -m nidp.services.mf_category_ranking --date 2026-05-31

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
from .config import ConfigurationError, load_config
from .service import create_pool, run

logger = logging.getLogger(__name__)


async def _main(args: argparse.Namespace) -> int:
    url = os.environ.get("NIDP_POSTGRES_URL") or os.environ.get("POSTGRES_URL")
    if not url:
        logger.error("NIDP_POSTGRES_URL not set")
        return 1

    # Validate config at startup (AC-14)
    try:
        config = load_config()
    except ConfigurationError as exc:
        logger.error("mf_category_ranking config error: %s", exc)
        return 1

    if args.date:
        rank_date = date.fromisoformat(args.date)
    else:
        rank_date = date.today() - timedelta(days=1)

    pool = await create_pool(url)
    try:
        report = await run(pool, rank_date, config=config)
    finally:
        await pool.close()

    print(json.dumps(report.as_dict(), indent=2))
    return 1 if report.errors else 0


def main() -> None:
    setup_logging(service="mf_category_ranking")
    parser = argparse.ArgumentParser(description="MF Category Ranking service")
    parser.add_argument("--date", help="Rank date YYYY-MM-DD (default: yesterday)")
    args = parser.parse_args()
    sys.exit(asyncio.run(_main(args)))


if __name__ == "__main__":
    main()
