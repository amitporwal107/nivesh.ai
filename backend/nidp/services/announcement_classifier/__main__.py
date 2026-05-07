"""python -m nidp.services.announcement_classifier [--limit N] [--dry-run] [--metrics]

Reads up to --limit unclassified rows from nidp.corporate_announcements
(filed in the last 30 days), classifies via Haiku, writes results back.
Idempotent — already-classified rows are skipped by the WHERE clause.

Cloud Scheduler fires every 10 min during market hours and once after
17:30 IST to clean up the day's late-evening filings.
"""
from __future__ import annotations

import argparse
import asyncio

from nidp.shared.logging_setup import setup_logging
from nidp.shared.metrics import start_metrics_server

from .service import run_once


async def _main(args: argparse.Namespace) -> None:
    await run_once(limit=args.limit, dry_run=args.dry_run)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=200,
                   help="Max rows to classify per invocation (default 200).")
    p.add_argument("--dry-run", action="store_true",
                   help="Run classifier and print results, but don't write to DB.")
    p.add_argument("--metrics", action="store_true")
    a = p.parse_args()
    setup_logging(service="announcement_classifier")
    if a.metrics:
        start_metrics_server()
    asyncio.run(_main(a))


if __name__ == "__main__":
    main()
