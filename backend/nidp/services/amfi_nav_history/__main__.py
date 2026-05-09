"""python -m nidp.services.amfi_nav_history [--from D] [--to D] [--scheme-codes csv] [--concurrency N]

Backfill historical NAVs from MFAPI.in. By default, walks every active
scheme in mf_scheme_master.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import date, datetime

from nidp.shared.logging_setup import setup_logging
from nidp.shared.metrics import start_metrics_server

from .service import DEFAULT_CONCURRENCY, run


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--date", type=_parse_date, default=None,
                   help="JobRun bookkeeping date (defaults to today).")
    p.add_argument("--from", dest="from_date", type=_parse_date, default=None,
                   help="Earliest nav_date to keep (default: unbounded).")
    p.add_argument("--to", dest="to_date", type=_parse_date, default=None,
                   help="Latest nav_date to keep (default: unbounded).")
    p.add_argument("--scheme-codes", type=str, default="",
                   help="Comma-separated scheme codes; default = all active.")
    p.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)
    p.add_argument("--only-stale-days", type=int, default=None,
                   help="Only refetch schemes whose latest known NAV is older "
                        "than this many days. Daily Cloud Run job uses 7 to "
                        "stay inside its 60min timeout. Default = full backfill.")
    p.add_argument("--metrics", action="store_true")
    args = p.parse_args()

    setup_logging(service="amfi_nav_history")
    if args.metrics:
        start_metrics_server()

    codes = [c.strip() for c in args.scheme_codes.split(",") if c.strip()] or None

    asyncio.run(run(
        target_date=args.date,
        scheme_codes=codes,
        from_date=args.from_date,
        to_date=args.to_date,
        concurrency=args.concurrency,
        only_stale_days=args.only_stale_days,
    ))


if __name__ == "__main__":
    main()
