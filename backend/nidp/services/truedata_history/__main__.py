"""python -m nidp.services.truedata_history [--raw-dir DIR] [--overlap-dir DIR] [--symbols A,B | --symbols-file F]
                                            [--dry-run] [--replace] [--batch-size N]
python -m nidp.services.truedata_history --rollback RUN_ID [--dry-run]

One-off backfill of nidp.prices_eod_history (migration 191) from TrueData's adjusted daily bars, stitched to our basis
(see service.py / bars.py). Not scheduled.

  --raw-dir DIR      history from files written by the resumable raw fetch (gzip JSON per symbol); without it, history
                     is fetched from TrueData (one call per symbol, 2010-01-01..2024-03-31).
  --overlap-dir DIR  overlap bars from files of the same format; without it, one TrueData call per symbol.
  --dry-run          stitch and print the report; write nothing (no job_log row either).
  --replace          redo symbols already loaded (their earlier rows are deleted in the batch's transaction; a later
                     --rollback of this run then leaves them empty: re-run to restore).
  --rollback RUN_ID  delete exactly that run's rows and stitch records (with --dry-run: count them). Any switch position.

The market-data switch (backend/config/market_data_source.json): a load, or anything that would call TrueData, runs only
in shadow / truedata; at current it prints verdict SWITCHED_OFF and touches nothing. Needs TRUEDATA_USERNAME /
TRUEDATA_PASSWORD (or TRUEDATA_CRED_FILE) when TrueData is called, and the NIDP database environment.
Exit: 0 done (flagged symbols are in the report, not failures), 1 a symbol failed to fetch or the run failed,
2 usage / switched off.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

from .service import load, rollback


async def _main(args) -> dict:
    from nidp.shared.storage.pg import close_pool
    try:
        if args.rollback:
            return await rollback(args.rollback, dry_run=args.dry_run)
        symbols = None
        if args.symbols:
            symbols = args.symbols.split(",")
        elif args.symbols_file:
            symbols = open(args.symbols_file).read().split()
        return await load(symbols, raw_dir=args.raw_dir, overlap_dir=args.overlap_dir, dry_run=args.dry_run,
                          replace=args.replace, batch_size=args.batch_size)
    finally:
        await close_pool()


def main() -> int:
    p = argparse.ArgumentParser(description="TrueData long daily stock history → nidp.prices_eod_history")
    p.add_argument("--raw-dir")
    p.add_argument("--overlap-dir")
    p.add_argument("--symbols")
    p.add_argument("--symbols-file")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--replace", action="store_true")
    p.add_argument("--batch-size", type=int, default=25)
    p.add_argument("--rollback", metavar="RUN_ID")
    args = p.parse_args()
    report = asyncio.run(_main(args))
    print(json.dumps(report, indent=2, default=str))
    if args.rollback:
        return 0
    if report.get("verdict") == "SWITCHED_OFF":
        return 2
    return 1 if report.get("verdict") in ("FAILED", "PARTIAL") else 0


if __name__ == "__main__":
    sys.exit(main())
