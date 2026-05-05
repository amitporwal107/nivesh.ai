"""python -m nidp.services.yfinance_backfill --from YYYY-MM-DD --to YYYY-MM-DD [--symbols A,B,C] [--metrics]

Default range: last 20 years ending today. Default symbols: latest
Nifty 500 constituents from nidp.index_constituents.

Examples:
  # Backfill 20y for Nifty 500 (default)
  python -m nidp.services.yfinance_backfill

  # Backfill specific dates + specific symbols
  python -m nidp.services.yfinance_backfill \\
      --from 2010-01-01 --to 2024-12-31 \\
      --symbols RELIANCE,TCS,INFY,HDFCBANK

  # Backfill for one stock, full history
  python -m nidp.services.yfinance_backfill --symbols WIPRO
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import date, datetime, timedelta

from nidp.shared.logging_setup import setup_logging
from nidp.shared.metrics import start_metrics_server

from .service import run


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--from", dest="start", type=_parse_date,
                   default=date.today() - timedelta(days=365 * 20),
                   help="Start date (default: 20 years ago).")
    p.add_argument("--to", dest="end", type=_parse_date,
                   default=date.today(),
                   help="End date (default: today).")
    p.add_argument("--symbols",
                   help="Comma-separated NSE symbols. Default: latest Nifty 500 from nidp.index_constituents.")
    p.add_argument("--concurrency", type=int, default=4,
                   help="Concurrent yfinance requests (default 4; YF throttles aggressively).")
    p.add_argument("--per-request-delay", type=float, default=2.0,
                   help="Polite sleep between requests within a worker (default 2.0s).")
    p.add_argument("--metrics", action="store_true",
                   help="Expose Prometheus /metrics on $NIDP_METRICS_PORT.")
    args = p.parse_args()

    setup_logging(service="yfinance_backfill")
    if args.metrics:
        start_metrics_server()

    symbols = None
    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]

    asyncio.run(run(
        start=args.start,
        end=args.end,
        symbols=symbols,
        concurrency=args.concurrency,
        per_request_delay=args.per_request_delay,
    ))


if __name__ == "__main__":
    main()
