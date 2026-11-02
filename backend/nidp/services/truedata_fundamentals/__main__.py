"""python -m nidp.services.truedata_fundamentals [--days N] [--symbols A,B] [--dry-run] [--offline] [--rollback RUN_ID]

Loads company balance sheets, fiscal-year cash flows and quarterly finance costs from TrueData's corporate API into
the warehouse (service.py has the whole flow). Obeys the market-data switch: at `current` nothing calls TrueData and
nothing is written except a SKIPPED job_log row. STAGING ONLY (owner, 3 Nov 2026): on production or an unknown
environment (nidp.shared.deploy_env) it calls nothing and writes no data either (verdict NOT_STAGING).

  --days N           load window: filings listed in the last N days (default 10)
  --anchor-days N    also make sure N days of result lists are cached, for the fiscal-year P&L that fixes each
                     company's unit (default 400; old days are fetched once)
  --symbols A,B      only these NSE symbols
  --dry-run          read the warehouse, plan, print counts; write nothing to the warehouse (no job_log row).
                     It still fetches missing raw answers into the raw cache unless --offline is given.
  --offline          no TrueData call: use the raw cache only (still obeys the switch)
  --no-finance-costs skip the quarter-only P&L pass
  --max-minutes M    stop fetching after M minutes and load what is cached (default 75)
  --raw-dir PATH     raw cache (default $NIDP_RAW_DIR/truedata_fundamentals, or TRUEDATA_FUNDAMENTALS_RAW_DIR)
  --rollback RUN_ID  undo one run exactly (deletes the rows it inserted, NULLs the columns it filled that still hold
                     its values); works whatever the switch says, in every environment

Return codes: 0 OK / PARTIAL / SKIPPED / dry run / rollback; 1 FAILED; 2 usage.
Needs TRUEDATA_USERNAME / TRUEDATA_PASSWORD and the NIDP database environment.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path

from .service import DEFAULT_ANCHOR_DAYS, DEFAULT_DAYS, DEFAULT_MAX_MINUTES, rollback, run


def _uuid(s: str) -> str:
    try:
        return str(uuid.UUID(s))
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a run id: {s!r}") from None


def _positive(s: str) -> int:
    v = int(s)
    if v < 0:
        raise argparse.ArgumentTypeError("must be >= 0")
    return v


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m nidp.services.truedata_fundamentals",
                                description="TrueData financial statements → NIDP warehouse (fill-only)")
    p.add_argument("--days", type=_positive, default=DEFAULT_DAYS)
    p.add_argument("--anchor-days", type=_positive, default=DEFAULT_ANCHOR_DAYS)
    p.add_argument("--symbols", default=None, help="comma-separated NSE symbols")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--offline", action="store_true")
    p.add_argument("--no-finance-costs", action="store_true")
    p.add_argument("--max-minutes", type=float, default=DEFAULT_MAX_MINUTES)
    p.add_argument("--raw-dir", type=Path, default=None)
    p.add_argument("--rollback", type=_uuid, default=None, metavar="RUN_ID")
    return p


async def _main(args: argparse.Namespace) -> dict:
    try:
        if args.rollback:
            return await rollback(args.rollback)
        symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()] if args.symbols else None
        return await run(days=args.days, anchor_days=args.anchor_days, symbols=symbols, dry_run=args.dry_run,
                         offline=args.offline, finance_costs=not args.no_finance_costs, max_minutes=args.max_minutes,
                         raw_root=args.raw_dir)
    finally:
        from nidp.shared.storage.pg import close_pool
        await close_pool()


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    from nidp.shared.logging_setup import setup_logging
    setup_logging("truedata_fundamentals")
    report = asyncio.run(_main(args))
    print(json.dumps(report, indent=2, default=str))
    return 1 if report.get("status") == "FAILED" else 0


if __name__ == "__main__":
    sys.exit(main())
