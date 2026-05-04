"""python -m nidp.services.bulk_deals [--date YYYY-MM-DD] [--metrics]"""
from __future__ import annotations

import argparse
import asyncio
from datetime import date

from nidp.shared.logging_setup import setup_logging
from nidp.shared.metrics import start_metrics_server

from .service import run


def _parse_date(s: str) -> date:
    from datetime import datetime
    return datetime.strptime(s, "%Y-%m-%d").date()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--date", type=_parse_date, default=None,
                   help="Logical AS-OF date; default = process whole rolling file.")
    p.add_argument("--metrics", action="store_true", help="Expose Prometheus /metrics on $NIDP_METRICS_PORT.")
    args = p.parse_args()

    setup_logging(service="bulk_deals")
    if args.metrics:
        start_metrics_server()

    asyncio.run(run(args.date))


if __name__ == "__main__":
    main()
