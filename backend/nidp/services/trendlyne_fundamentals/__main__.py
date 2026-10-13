"""CLI for the Trendlyne fundamentals loader — see service.py."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

from nidp.shared.logging_setup import setup_logging
from nidp.shared.storage.pg import close_pool

from . import parse, service
from .client import TrendlyneError


def main() -> None:
    setup_logging("trendlyne_fundamentals")
    p = argparse.ArgumentParser(description="Fundamentals and sectors from the Trendlyne MCP server")
    sub = p.add_subparsers(dest="command", required=True)
    f = sub.add_parser("fetch", help="stage raw parameter values")
    f.add_argument("--pass", dest="pass_name", choices=sorted(parse.PASSES), required=True)
    f.add_argument("--max-calls", type=int, default=None)
    f.add_argument("--symbols", default=None, help="comma-separated NSE symbols")
    s = sub.add_parser("sectors", help="fill sector_master for rows without a sector")
    s.add_argument("--max-calls", type=int, default=None)
    s.add_argument("--symbols", default=None)
    b = sub.add_parser("build", help="build dated quarterly rows from the staged values")
    b.add_argument("--dry-run", action="store_true")
    b.add_argument("--symbols", default=None)
    sub.add_parser("daily", help="incomplete passes, build, then sectors — within today's call budget")
    a = p.parse_args()
    symbols = [x.strip().upper() for x in a.symbols.split(",")] if getattr(a, "symbols", None) else None

    async def _go() -> dict:
        try:
            if a.command == "daily":
                return await service.daily()
            if a.command == "fetch":
                return await service.fetch(a.pass_name, max_calls=a.max_calls, symbols=symbols)
            if a.command == "sectors":
                return await service.sectors(max_calls=a.max_calls, symbols=symbols)
            return await service.build(dry_run=a.dry_run, symbols=symbols)
        finally:
            await close_pool()

    try:
        print(json.dumps(asyncio.run(_go()), default=str))
    except TrendlyneError as exc:
        print(f"trendlyne_fundamentals FAILED: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
