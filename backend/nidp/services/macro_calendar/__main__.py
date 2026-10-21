"""python -m nidp.services.macro_calendar [--dry-run] [--metrics]

Collects India / US macro releases from FRED, the Fed, MoSPI and RBI and upserts nidp.macro_releases.
--dry-run reads every source, prints the rows it WOULD write and touches no database.
"""
from __future__ import annotations

import argparse
import asyncio

from nidp.shared.logging_setup import setup_logging
from nidp.shared.metrics import start_metrics_server

from .service import collect, run


async def _dry() -> None:
    rows, failures = await collect()
    for r in sorted(rows, key=lambda x: (x["release_date"], x["indicator_code"])):
        print(f"{r['release_date']} {r['indicator_code']:<18} period={r['period']!s:<22} previous={r['previous']!s:<9} "
              f"actual={r['actual']!s:<9} {r['release_time'] or '-':<5} {r['source_url']}")
    print(f"ROWS {len(rows)}  FAILURES {len(failures)}")
    for f in failures:
        print("FAILED:", f)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--metrics", action="store_true")
    args = p.parse_args()
    setup_logging(service="macro_calendar")
    if args.dry_run:
        asyncio.run(_dry())
        return
    if args.metrics:
        start_metrics_server()
    asyncio.run(run(None))


if __name__ == "__main__":
    main()
