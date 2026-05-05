"""python -m nidp.services.fred_macro [--metrics]

Pulls 8 curated global macro series from FRED. Idempotent — re-runs
re-fetch full history but ON CONFLICT means only changed values write.
Suitable for daily refresh + initial backfill.
"""
from __future__ import annotations

import argparse
import asyncio

from nidp.shared.logging_setup import setup_logging
from nidp.shared.metrics import start_metrics_server

from .service import run


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--metrics", action="store_true")
    args = p.parse_args()
    setup_logging(service="fred_macro")
    if args.metrics:
        start_metrics_server()
    asyncio.run(run(None))


if __name__ == "__main__":
    main()
