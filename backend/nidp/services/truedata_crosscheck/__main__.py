"""python -m nidp.services.truedata_crosscheck [--date YYYY-MM-DD] [--evaluation]

Read only. Obeys the market-data switch: at `current` it prints verdict SWITCHED_OFF and touches nothing. --evaluation
runs it anyway as a manual trial measurement (read only, never scheduled). Prints one JSON report. Exit code: 0 every compared row equal, 1 differences found, 2 not compared (no NSE
rows for the date, or TrueData refused or failed the call). Needs TRUEDATA_USERNAME / TRUEDATA_PASSWORD (or
TRUEDATA_CRED_FILE) and the NIDP database environment. Not scheduled.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import date as _date, datetime

from .service import run


def _parse_date(s: str) -> _date:
    return datetime.strptime(s, "%Y-%m-%d").date()


async def _main(day, evaluation: bool = False) -> dict:
    from nidp.shared import market_data_source as mds
    if not evaluation and not mds.truedata_is_on():                 # switched off: no DB, no TrueData
        return await run(day or _date.today(), evaluation=False)
    if day is None:
        from nidp.shared.trading_day import last_market_close_date
        day = await last_market_close_date()
    try:
        return await run(day, evaluation=evaluation)
    finally:
        from nidp.shared.storage.pg import close_pool
        await close_pool()


def main() -> int:
    p = argparse.ArgumentParser(description="TrueData bhavcopy vs NSE files in the warehouse (read only)")
    p.add_argument("--date", type=_parse_date, default=None, help="trading date (default: last NSE close)")
    p.add_argument("--evaluation", action="store_true",
                   help="manual trial measurement: run even when the switch is on current (read only)")
    args = p.parse_args()
    report = asyncio.run(_main(args.date, args.evaluation))
    print(json.dumps(report, indent=2, default=str))
    return {"EQUAL": 0, "DIFFERENT": 1}.get(report["verdict"], 2)


if __name__ == "__main__":
    sys.exit(main())
