"""python -m nidp.services.fpi_sector_auc [--since YYYY-MM-DD] [--lookback N]

Default: the last 8 fortnights (~4 months). Use --since for a backfill, e.g.
    python -m nidp.services.fpi_sector_auc --since 2012-01-31
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import date, datetime

from nidp.shared.logging_setup import setup_logging

from .service import run


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


async def _main(args: argparse.Namespace) -> None:
    await run(lookback=args.lookback, since=args.since)


def main() -> None:
    p = argparse.ArgumentParser(prog="nidp.services.fpi_sector_auc")
    p.add_argument("--since", type=_parse_date, default=None,
                   help="Backfill every fortnight ending on/after this date.")
    p.add_argument("--lookback", type=int, default=None,
                   help="How many recent fortnights to consider (default 8).")
    args = p.parse_args()
    setup_logging(service="fpi_sector_auc")
    asyncio.run(_main(args))


if __name__ == "__main__":
    main()
