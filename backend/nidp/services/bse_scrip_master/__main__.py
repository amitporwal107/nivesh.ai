"""CLI for the point-in-time BSE scrip master (migration 153)."""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
from datetime import date, datetime

from nidp.shared.storage.pg import close_pool

from .service import run


def _d(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


async def _main(a: argparse.Namespace) -> None:
    try:
        rep = await run(target=a.date, start=a.from_date, end=a.to_date,
                        resume=not a.no_resume)
        print(json.dumps(rep, indent=1, default=str))
    finally:
        await close_pool()


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(prog="bse_scrip_master")
    p.add_argument("--date", type=_d, default=None, help="single trading day")
    p.add_argument("--from", dest="from_date", type=_d, default=None)
    p.add_argument("--to", dest="to_date", type=_d, default=None)
    p.add_argument("--no-resume", action="store_true",
                   help="refetch days already present")
    a = p.parse_args()
    if a.date is None and (a.from_date is None or a.to_date is None):
        p.error("pass --date, or both --from and --to")
    asyncio.run(_main(a))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
