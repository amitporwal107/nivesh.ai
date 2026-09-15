"""python -m nidp.services.nse_reference_snapshot [--date YYYY-MM-DD]"""
from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from datetime import date

from nidp.shared.derived_run import run_with_job_log
from nidp.shared.logging_setup import setup_logging
from nidp.shared.storage.pg import close_pool

from .service import run


async def _main(args: argparse.Namespace) -> None:
    try:
        report = await run_with_job_log(
            "nse_reference_snapshot", run, args.date,
            target_date=args.date, rows_inserted_attr="rows_written",
        )
        print(json.dumps(asdict(report), default=str))
    finally:
        await close_pool()


def main() -> None:
    setup_logging(service="nse_reference_snapshot")
    p = argparse.ArgumentParser(description="Daily NSE price band / F&O / ETF snapshot")
    p.add_argument("--date", type=date.fromisoformat, default=None,
                   help="as_of_date to stamp (default: today, IST)")
    asyncio.run(_main(p.parse_args()))


if __name__ == "__main__":
    main()
