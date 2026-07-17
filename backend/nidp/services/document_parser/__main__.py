"""python -m nidp.services.document_parser [--discover-limit N] [--parse-limit N] [--concurrency N] [--metrics]

Two-phase loop: register pending attachments as documents, then download
+ parse + chunk a batch. Cron fires every 10 min during market hours and
hourly off-hours so concall-PDF arrivals don't queue indefinitely.
"""
from __future__ import annotations

import argparse
import asyncio
import json

from nidp.shared.derived_run import run_with_job_log
from nidp.shared.logging_setup import setup_logging
from nidp.shared.metrics import start_metrics_server
from nidp.shared.storage.pg import close_pool

from .service import run_once


async def _main(args: argparse.Namespace) -> None:
    try:
        summary = await run_with_job_log(
            "document_parser",
            run_once,
            discover_limit=args.discover_limit,
            parse_limit=args.parse_limit,
            concurrency=args.concurrency,
            embed_limit=args.embed_limit,
            shards=args.shards,
            shard=args.shard,
            from_date=args.from_date,
            to_date=args.to_date,
        )
    finally:
        await close_pool()
    print(json.dumps(summary, indent=2, default=str))


def _ymd(v: str):
    from datetime import datetime
    return datetime.strptime(v, "%Y-%m-%d").date()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--discover-limit", type=int, default=500,
                   help="Max announcements to register as documents per invocation.")
    p.add_argument("--parse-limit", type=int, default=50,
                   help="Max pending documents to actually download+parse per invocation.")
    p.add_argument("--concurrency", type=int, default=4,
                   help="Parallel PDF download/parse workers.")
    p.add_argument("--embed-limit", type=int, default=200,
                   help="Max chunks to embed (OpenAI) per invocation; backfills NULL embeddings.")
    # Backfill throughput: pypdf is pure Python, so one process is GIL-capped at
    # ~1 core no matter how high --concurrency goes. Run N processes with
    # --shards N --shard i to use N cores; each takes a disjoint hash slice of the
    # queue (it has no row claiming, so unsharded workers would duplicate work).
    p.add_argument("--shards", type=int, default=1,
                   help="Total number of parallel worker processes splitting the queue.")
    p.add_argument("--shard", type=int, default=0,
                   help="This worker's index, 0-based, must be < --shards.")
    # Month-by-month backfill. Months are naturally disjoint, so each worker can
    # own a month on any machine with no coordination and no hash sharding — and
    # every month is a checkpoint you can stop at and resume from. --to-date is
    # EXCLUSIVE so --from-date 2026-01-01 --to-date 2026-02-01 is exactly January
    # with no overlap into the next window.
    p.add_argument("--from-date", type=_ymd, default=None,
                   help="Only parse documents filed on/after this date (YYYY-MM-DD).")
    p.add_argument("--to-date", type=_ymd, default=None,
                   help="Only parse documents filed BEFORE this date (YYYY-MM-DD, exclusive).")
    p.add_argument("--metrics", action="store_true")
    a = p.parse_args()
    if not 0 <= a.shard < a.shards:
        p.error(f"--shard {a.shard} out of range for --shards {a.shards}")
    if a.from_date and a.to_date and a.from_date >= a.to_date:
        p.error(f"--from-date {a.from_date} must be before --to-date {a.to_date} (exclusive)")
    setup_logging(service="document_parser")
    if a.metrics:
        start_metrics_server()
    asyncio.run(_main(a))


if __name__ == "__main__":
    main()
