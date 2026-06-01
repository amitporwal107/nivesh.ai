"""python -m nidp.services.pra_engine [--date YYYY-MM-DD] [--user USER_ID] [--metrics]

--date      Target computation date (default: today's date or last trading day).
--user      Run for a single external_user_id only (for backfill / debug).
--metrics   Start Prometheus metrics server on port 9100.
--dry-run   Compute but do not write to DB.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import date, datetime

from nidp.shared.logging_setup import setup_logging
from nidp.shared.metrics import start_metrics_server

from .service import run


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def main() -> None:
    p = argparse.ArgumentParser(description="Portfolio Risk Analytics nightly engine")
    p.add_argument("--date",    type=_parse_date, default=None,
                   help="Computation date. Default: today.")
    p.add_argument("--user",    type=str, default=None,
                   help="Run for a single external_user_id only.")
    p.add_argument("--metrics", action="store_true")
    p.add_argument("--dry-run", action="store_true",
                   help="Compute but skip DB writes.")
    args = p.parse_args()

    setup_logging(service="pra_engine")
    if args.metrics:
        start_metrics_server()
    asyncio.run(run(
        target_date=args.date or date.today(),
        user_filter=args.user,
        dry_run=args.dry_run,
    ))


if __name__ == "__main__":
    main()
