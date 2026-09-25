"""CLI for the corporate-transaction lifecycle engine (migration 155)."""
from __future__ import annotations

import argparse
import asyncio
import json
import logging

from nidp.shared.storage.pg import close_pool

from .service import run


async def _main(a: argparse.Namespace) -> None:
    try:
        print(json.dumps(await run(report_only=a.report), indent=1, default=str))
    finally:
        await close_pool()


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(prog="event_lifecycle")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--build", action="store_true", help="classify, group and persist")
    g.add_argument("--report", action="store_true", help="per-family readiness only")
    asyncio.run(_main(p.parse_args()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
