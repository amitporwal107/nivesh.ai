"""python -m nidp.services.truedata_crosscheck [--date YYYY-MM-DD] [--record] [--evaluation]

TrueData's bhavcopy against NSE's files in the warehouse. Obeys the market-data switch: at `current` TrueData is not
called and the warehouse is not read (verdict SWITCHED_OFF).

  (no flag)     prints one JSON report and writes nothing. Exit 0 every compared row equal, 1 differences, 2 not compared.
  --record      the scheduled form (deploy/cloudpe/nidp/nidp-staging-truedata.cron, weekdays 22:45 IST): also writes the
                run to nidp.job_log / validation_runs / validation_findings and alerts on ERROR or CRITICAL findings.
                At `current` it records a SKIPPED run (SWITCHED_OFF) and nothing else. Exit 0 unless the job failed
                (TrueData's call failed on a day NSE has data): the findings, not the exit code, carry the differences.
  --evaluation  manual trial measurement: runs even when the switch is on `current`. Never scheduled.

Needs TRUEDATA_USERNAME / TRUEDATA_PASSWORD (or TRUEDATA_CRED_FILE) and the NIDP database environment.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import date as _date, datetime

from .service import record, run


def _parse_date(s: str) -> _date:
    return datetime.strptime(s, "%Y-%m-%d").date()


async def _main(day, evaluation: bool = False, do_record: bool = False) -> dict:
    from nidp.shared import market_data_source as mds
    switched_off = not evaluation and not mds.truedata_is_on()
    if switched_off and not do_record:                               # no DB, no TrueData
        return await run(day or _date.today(), evaluation=False)
    try:
        if day is None:
            from nidp.shared.trading_day import last_market_close_date
            day = await last_market_close_date()
        report = await run(day, evaluation=evaluation)
        if do_record:
            report["recorded"] = await record(report, day)
        return report
    finally:
        from nidp.shared.storage.pg import close_pool
        await close_pool()


def main() -> int:
    p = argparse.ArgumentParser(description="TrueData bhavcopy vs NSE files in the warehouse")
    p.add_argument("--date", type=_parse_date, default=None, help="trading date (default: last NSE close)")
    p.add_argument("--record", action="store_true", help="write the run and its findings to the DQ tables; alert")
    p.add_argument("--evaluation", action="store_true",
                   help="manual trial measurement: run even when the switch is on current")
    args = p.parse_args()
    report = asyncio.run(_main(args.date, args.evaluation, args.record))
    print(json.dumps(report, indent=2, default=str))
    if args.record:
        return 1 if (report.get("recorded") or {}).get("job_status") == "FAILED" else 0
    return {"EQUAL": 0, "DIFFERENT": 1}.get(report["verdict"], 2)


if __name__ == "__main__":
    sys.exit(main())
