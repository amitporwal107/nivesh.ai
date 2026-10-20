"""python -m nidp.services.corporate_actions [--metrics]"""
from __future__ import annotations
import argparse, asyncio
from datetime import date
from nidp.shared.logging_setup import setup_logging
from nidp.shared.metrics import start_metrics_server
from .service import backfill, run


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--metrics", action="store_true")
    p.add_argument("--backfill-from", type=date.fromisoformat, metavar="YYYY-MM-DD",
                   help="load historical actions (all NSE boards) from this date")
    p.add_argument("--backfill-to", type=date.fromisoformat, metavar="YYYY-MM-DD",
                   help="end of the backfill window (default: today)")
    a = p.parse_args()
    setup_logging(service="corporate_actions")
    if a.metrics: start_metrics_server()
    if a.backfill_from:
        print(asyncio.run(_backfill(a.backfill_from, a.backfill_to or date.today())))
        return
    asyncio.run(run(None))


async def _backfill(start: date, end: date) -> dict:
    from nidp.shared.sources import nse_fetcher
    from nidp.shared.storage.pg import close_pool
    try:
        return await backfill(start, end)
    finally:
        await nse_fetcher.close()
        await close_pool()


if __name__ == "__main__":
    main()
