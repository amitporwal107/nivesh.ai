"""python -m nidp.services.nse_financials_backfill [--symbols A,B] [--concurrency N]

Batch-backfills nidp.nse_financials_quarterly for all Nifty 500 symbols
(or a supplied list) using NSE XBRL comparator + Screener.in fallback.

Examples:
  # Full Nifty 500 backfill
  python -m nidp.services.nse_financials_backfill

  # Single symbol
  python -m nidp.services.nse_financials_backfill --symbols RELIANCE

  # Only symbols with fewer than 8 quarters already stored
  python -m nidp.services.nse_financials_backfill --only-missing

  # Faster (more concurrent, more likely to get throttled by NSE)
  python -m nidp.services.nse_financials_backfill --concurrency 8 --delay 1.5
"""
from __future__ import annotations

import argparse
import asyncio

from nidp.shared.logging_setup import setup_logging
from nidp.shared.metrics import start_metrics_server

from .service import DEFAULT_CONCURRENCY, PER_REQUEST_DELAY_S, run


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--symbols",
        help="Comma-separated NSE symbols. Default: latest Nifty 500.",
    )
    p.add_argument(
        "--concurrency", type=int, default=DEFAULT_CONCURRENCY,
        help=f"Parallel workers (default {DEFAULT_CONCURRENCY}). "
             "NSE throttles aggressively — keep ≤ 8.",
    )
    p.add_argument(
        "--delay", dest="per_request_delay",
        type=float, default=PER_REQUEST_DELAY_S,
        help=f"Polite sleep between requests (default {PER_REQUEST_DELAY_S}s).",
    )
    p.add_argument(
        "--only-missing", action="store_true",
        help="Skip symbols that already have ≥ 8 quarters stored.",
    )
    p.add_argument(
        "--metrics", action="store_true",
        help="Expose Prometheus /metrics on $NIDP_METRICS_PORT.",
    )
    args = p.parse_args()

    setup_logging(service="nse_financials_backfill")
    if args.metrics:
        start_metrics_server()

    symbols = None
    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]

    asyncio.run(run(
        symbols=symbols,
        concurrency=args.concurrency,
        per_request_delay=args.per_request_delay,
        only_missing=args.only_missing,
    ))


if __name__ == "__main__":
    main()
