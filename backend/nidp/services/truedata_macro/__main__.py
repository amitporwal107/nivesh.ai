"""python -m nidp.services.truedata_macro [--dry-run] [--series CODE,CODE]
python -m nidp.services.truedata_macro --rollback RUN_ID [--dry-run]

Appends the days since each TD_* series' last stored day to nidp.fred_macro (source 'truedata'); see service.py.
Scheduled by deploy/cloudpe/nidp/nidp-staging-truedata-macro.cron (00:15 IST daily, for the previous day).

  --dry-run          fetch and print what would be inserted; write nothing (no job_log row). At `current` it calls
                     nothing and reads nothing.
  --series           TrueData codes to refresh (default: all 24), e.g. "CRUDEOIL-I,INDIA VIX".
  --rollback RUN_ID  delete exactly that run's rows (the job never rewrites a stored day). Any switch position.

The market-data switch (backend/config/market_data_source.json): at `current` nothing calls TrueData and the run is
recorded as SKIPPED (SWITCHED_OFF). Needs TRUEDATA_USERNAME / TRUEDATA_PASSWORD (or TRUEDATA_CRED_FILE) and the NIDP
database environment.
Exit: 0 OK / SKIPPED / up to date, 1 a series failed (run_service.sh retries; a retry fetches only what is missing).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

from .service import SERIES, refresh, rollback


async def _main(args) -> dict:
    from nidp.shared.storage.pg import close_pool
    try:
        if args.rollback:
            return await rollback(args.rollback, dry_run=args.dry_run)
        codes = [c.strip() for c in args.series.split(",")] if args.series else None
        unknown = [c for c in codes or [] if c not in SERIES]
        if unknown:
            raise SystemExit(f"unknown series code(s): {unknown}; known: {sorted(SERIES)}")
        return await refresh(dry_run=args.dry_run, codes=codes)
    finally:
        await close_pool()


def main() -> int:
    p = argparse.ArgumentParser(description="TrueData TD_* macro series → nidp.fred_macro (new days only)")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--series")
    p.add_argument("--rollback", metavar="RUN_ID")
    args = p.parse_args()
    report = asyncio.run(_main(args))
    print(json.dumps(report, indent=2, default=str))
    return 1 if report.get("verdict") in ("FAILED", "PARTIAL") else 0


if __name__ == "__main__":
    sys.exit(main())
