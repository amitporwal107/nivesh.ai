"""python -m nidp.services.sebi_circulars [--source rss|listing|all] [--metrics]

    --source rss      the SEBI RSS feed (default; what cron runs)
    --source listing  page 1 of the Circulars and Master Circulars listings (one-off backfill)
    --source all      both
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import date, datetime

from nidp.shared.logging_setup import setup_logging
from nidp.shared.metrics import start_metrics_server

from .service import SOURCES, run


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--date", type=_parse_date, default=None,
                   help="accepted for the runner's sake and ignored: SEBI shows only the newest items")
    p.add_argument("--source", choices=SOURCES, default="rss")
    p.add_argument("--metrics", action="store_true")
    args = p.parse_args()

    setup_logging(service="sebi_circulars")
    if args.metrics:
        start_metrics_server()
    asyncio.run(run(args.date, source=args.source))


if __name__ == "__main__":
    main()
