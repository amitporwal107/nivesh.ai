"""python -m nidp.services.snapshot_builder --date YYYY-MM-DD [--force] [--metrics]"""
from __future__ import annotations

import argparse
import asyncio
from datetime import date, datetime

from nidp.shared.logging_setup import setup_logging
from nidp.shared.metrics import start_metrics_server

from .service import run, status


def _d(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=False)

    p.add_argument("--date", type=_d, help="Build snapshot for this date.")
    p.add_argument("--force", action="store_true",
                   help="Build even if preflight fails (use with care).")
    p.add_argument("--metrics", action="store_true")
    p.add_argument("--status", action="store_true",
                   help="Print readiness for --date (or latest if omitted) and exit.")

    a = p.parse_args()
    setup_logging(service="snapshot_builder")
    if a.metrics:
        start_metrics_server()

    if a.status:
        async def _show():
            row = await status(a.date)
            if not row:
                print("(no snapshot row found)")
                return
            for k, v in row.items():
                print(f"  {k}: {v}")
        asyncio.run(_show())
        return

    if not a.date:
        p.error("--date is required (unless using --status)")

    asyncio.run(run(a.date, force=a.force))


if __name__ == "__main__":
    main()
