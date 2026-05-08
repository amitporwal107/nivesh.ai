"""python -m nidp.services.mf_disclosure_snapshot [--date YYYY-MM-DD] [--metrics]"""
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
    p = argparse.ArgumentParser()
    p.add_argument("--date", type=_parse_date, default=None,
                   help="snapshot_date for this run (default: today).")
    p.add_argument("--metrics", action="store_true")
    args = p.parse_args()

    setup_logging(service="mf_disclosure_snapshot")
    if args.metrics:
        start_metrics_server()
    asyncio.run(run(args.date))


if __name__ == "__main__":
    main()
