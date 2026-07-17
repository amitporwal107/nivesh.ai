"""python -m nidp.services.filing_insights [--limit N] [--dry-run] [--metrics]

Selects up to --limit MATERIAL corporate announcements (last 30 days, classified,
event_category NOT IN regulatory/other, impact_score present) that have a parsed
document and no insight yet, generates one grounded insight each via OpenAI
function-calling, and upserts into nidp.corporate_event_signals
(signal_type='filing_insight').

Idempotent — the partial unique index (announcement_ref, announcement_source)
makes re-runs update in place. Cron fires this every ~30 min.
"""
from __future__ import annotations

import argparse
import asyncio

from nidp.shared.derived_run import run_with_job_log
from nidp.shared.logging_setup import setup_logging
from nidp.shared.metrics import start_metrics_server
from nidp.shared.storage.pg import close_pool

from .service import run_once


async def _main(args: argparse.Namespace) -> None:
    try:
        await run_with_job_log(
            "filing_insights",
            run_once,
            limit=args.limit,
            dry_run=args.dry_run,
            rows_inserted_attr="processed",
        )
    finally:
        await close_pool()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=100,
                   help="Max filings to process per invocation (default 100).")
    p.add_argument("--dry-run", action="store_true",
                   help="Generate insights and print them, but don't write to DB.")
    p.add_argument("--metrics", action="store_true")
    a = p.parse_args()
    setup_logging(service="filing_insights")
    if a.metrics:
        start_metrics_server()
    asyncio.run(_main(a))


if __name__ == "__main__":
    main()
