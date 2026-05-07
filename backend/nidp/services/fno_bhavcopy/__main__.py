"""python -m nidp.services.fno_bhavcopy [--date YYYY-MM-DD] [--metrics]

Default target_date: last NSE close from nidp.v_market_session
(DB-backed canonical answer; honours holidays + 18:30 IST cutoff).
Mirrors bhavcopy's behaviour so Cloud Scheduler can fire the job
without arguments and always get the most-recent published file.
"""
from __future__ import annotations
import argparse, asyncio
from datetime import date as _date, datetime

from nidp.shared.logging_setup import setup_logging
from nidp.shared.metrics import start_metrics_server
from nidp.shared.trading_day import last_market_close_date

from .service import run


def _parse_date(s: str) -> _date:
    return datetime.strptime(s, "%Y-%m-%d").date()


async def _main(args: argparse.Namespace) -> None:
    target = args.date or await last_market_close_date()
    await run(target)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--date", type=_parse_date, default=None,
                   help="Trading date (yyyy-mm-dd). Defaults to last NSE close.")
    p.add_argument("--metrics", action="store_true")
    a = p.parse_args()
    setup_logging(service="fno_bhavcopy")
    if a.metrics:
        start_metrics_server()
    asyncio.run(_main(a))


if __name__ == "__main__":
    main()
