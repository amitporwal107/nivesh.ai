"""python -m nidp.services.corporate_announcements --source nse|bse [--date YYYY-MM-DD] [--metrics]

Cloud Scheduler fires one job per source every 10 min during market
hours. Upserts on (announcement_id, source) are idempotent so re-runs
of the same window collapse to no-ops. For backfill, loop over dates
with --date YYYY-MM-DD.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import date as _date, datetime

from nidp.shared.logging_setup import setup_logging
from nidp.shared.metrics import start_metrics_server

from .service import run_once


def _parse_date(s: str) -> _date:
    return datetime.strptime(s, "%Y-%m-%d").date()


async def _main(args: argparse.Namespace) -> None:
    target = args.date or _date.today()
    sources = ("nse", "bse") if args.source == "both" else \
              ("nse", "bse", "bse_subcat") if args.source == "all" else (args.source,)
    for src in sources:
        await run_once(src, target)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--source", choices=("nse", "bse", "bse_subcat", "both", "all"), default="nse",
                   help="Which exchange feed to ingest. 'both' runs them sequentially.")
    p.add_argument("--date", type=_parse_date, default=None,
                   help="Trading date (yyyy-mm-dd). Defaults to today.")
    p.add_argument("--metrics", action="store_true")
    a = p.parse_args()
    setup_logging(service=f"corporate_announcements_{a.source}")
    if a.metrics:
        start_metrics_server()
    asyncio.run(_main(a))


if __name__ == "__main__":
    main()
