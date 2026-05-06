"""python -m nidp.services.bhavcopy --date YYYY-MM-DD [--metrics]"""
from __future__ import annotations

import argparse
import asyncio
from datetime import date, datetime

from nidp.shared.logging_setup import setup_logging
from nidp.shared.metrics import start_metrics_server
from nidp.shared.trading_day import default_target_date

from .service import run


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--date", type=_parse_date, default=default_target_date(),
                   help="Trading date (yyyy-mm-dd). Defaults to yesterday IST.")
    p.add_argument("--metrics", action="store_true")
    args = p.parse_args()

    setup_logging(service="bhavcopy")
    if args.metrics:
        start_metrics_server()

    asyncio.run(run(args.date))


if __name__ == "__main__":
    main()
