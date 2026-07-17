"""python -m nidp.services.corporate_announcements_bse_subcat [--date YYYY-MM-DD]

Thin wrapper pinning source='bse_subcat', mirroring the nse/bse wrappers, and
registering run-status to nidp.job_log via JobRun so the feed shows up in
v_feed_status instead of reading as "never ran".

Why this file exists at all: run_service.sh invokes `python -m
nidp.services.$SERVICE`, so a feed is only schedulable if a module of that exact
name exists. Wrappers were written for nse and bse but never for bse_subcat —
so the BSE sweep that actually WORKS had no way to be scheduled, and never was.

The cost of that omission, measured on staging 2026-07-17:

    corporate_announcements_bse  (coarse, scheduled)  ~41 rows/day, reports OK
    bse_subcat  (unscheduled, run only via backfill)  ~1,330 rows/day

The coarse strCat=-1 sweep returns "No Record Found!" and reports OK/SKIPPED —
so BSE looked merely quiet rather than broken, and the working feed sat unused.
Backfilling it took BSE_ANN from 2,111 rows to 76,520 (36x), overtaking NSE,
which is the correct shape: BSE lists more companies than NSE.

The subcategory sweep also captures SUBCATNAME -> subcategory, which the coarse
sweep cannot — that field is what lets document_parser type concall transcripts
and investor presentations as first-class corpus docs rather than generic
attachments.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import date, datetime

from nidp.shared.derived_run import run_with_job_log
from nidp.shared.logging_setup import setup_logging
from nidp.shared.storage.pg import close_pool
from nidp.services.corporate_announcements.service import run_once


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


async def _runner(target: date) -> None:
    try:
        await run_with_job_log(
            "corporate_announcements_bse_subcat",
            run_once,
            "bse_subcat",
            target,
            target_date=target,
        )
    finally:
        await close_pool()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--date", type=_parse_date, default=None,
                   help="Trading date (yyyy-mm-dd). Defaults to today.")
    a = p.parse_args()
    setup_logging(service="corporate_announcements_bse_subcat")
    target = a.date or date.today()
    asyncio.run(_runner(target))


if __name__ == "__main__":
    main()
