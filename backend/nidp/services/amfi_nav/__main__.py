"""python -m nidp.services.amfi_nav [--date YYYY-MM-DD] [--metrics]

target_date is recorded on the JobRun row but doesn't drive the URL —
AMFI NAVAll is a current-snapshot file.
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


async def _main(args: argparse.Namespace) -> None:
    target = args.date or date.today()
    await run(target)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--date", type=_parse_date, default=None,
                   help="Run date for JobRun bookkeeping. Defaults to today.")
    p.add_argument("--metrics", action="store_true")
    args = p.parse_args()

    setup_logging(service="amfi_nav")
    if args.metrics:
        start_metrics_server()

    asyncio.run(_main(args))


if __name__ == "__main__":
    main()
