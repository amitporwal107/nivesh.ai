"""python -m nidp.services.feed_reconciler [--lookback N] [--feeds a,b,c] [--dry-run]

Detects and heals missed feed runs in a rolling window. Safe to run on
any cadence (idempotent). Intended for a morning cron slot after the
evening ingest window, so it catches anything that failed overnight.
"""
from __future__ import annotations

import argparse
import asyncio

from nidp.shared.logging_setup import setup_logging

from .service import reconcile


def main() -> None:
    p = argparse.ArgumentParser(prog="feed_reconciler")
    p.add_argument("--lookback", type=int, default=None,
                   help="Trading-day look-back window (default 7 / NIDP_RECONCILE_LOOKBACK_DAYS).")
    p.add_argument("--feeds", default=None,
                   help="Comma-separated feed subset (default NIDP_RECONCILE_FEEDS).")
    p.add_argument("--dry-run", action="store_true",
                   help="Detect and report gaps but do NOT heal.")
    args = p.parse_args()

    setup_logging(service="feed_reconciler")

    feeds = [f.strip() for f in args.feeds.split(",")] if args.feeds else None
    report = asyncio.run(reconcile(feeds=feeds, lookback_days=args.lookback, dry_run=args.dry_run))

    # Best-effort healer: exit 0 even with unhealed gaps (the JobRun status
    # + the email carry that signal). A genuine crash (e.g. DB down) raises
    # out of reconcile() and exits non-zero, so run_service.sh can retry.
    remaining = report.get("remaining") or []
    print(f"feed_reconciler: gaps={len(report.get('gaps_before') or [])} "
          f"healed={len(report.get('healed') or [])} remaining={len(remaining)}")


if __name__ == "__main__":
    main()
