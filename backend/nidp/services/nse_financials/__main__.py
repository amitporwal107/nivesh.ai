"""python -m nidp.services.nse_financials [--symbol SYM] [--date YYYY-MM-DD] [--metrics]"""
from __future__ import annotations
import argparse, asyncio
from datetime import date
from nidp.shared.logging_setup import setup_logging
from nidp.shared.metrics import start_metrics_server
from nidp.shared.storage.pg import close_pool
from .service import run


async def _runner(symbol=None, target_date=None) -> None:
    try:
        await run(target_date=target_date, symbol=symbol)
    finally:
        await close_pool()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--symbol", default=None, help="Run for a single NSE symbol")
    p.add_argument("--date", default=None, help="Target date YYYY-MM-DD (default: today)")
    p.add_argument("--metrics", action="store_true")
    a = p.parse_args()
    setup_logging(service="nse_financials")
    if a.metrics:
        start_metrics_server()
    target_date = date.fromisoformat(a.date) if a.date else None
    asyncio.run(_runner(symbol=a.symbol, target_date=target_date))


if __name__ == "__main__":
    main()
