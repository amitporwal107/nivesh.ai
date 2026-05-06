"""python -m nidp.services.delivery [--date YYYY-MM-DD] [--metrics]

Default target_date: last NSE close from nidp.v_market_session.
"""
from __future__ import annotations
import argparse, asyncio
from datetime import date, datetime
from nidp.shared.logging_setup import setup_logging
from nidp.shared.metrics import start_metrics_server
from nidp.shared.trading_day import last_market_close_date
from .service import run


def _d(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


async def _main(args: argparse.Namespace) -> None:
    target = args.date or await last_market_close_date()
    await run(target)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--date", type=_d, default=None)
    p.add_argument("--metrics", action="store_true")
    a = p.parse_args()
    setup_logging(service="delivery")
    if a.metrics: start_metrics_server()
    asyncio.run(_main(a))


if __name__ == "__main__":
    main()
