"""CLI entry point for NSE pledge data ingester.

Usage:
    python -m nidp.services.nse_pledge_data
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys

from nidp.shared.logging_setup import setup_logging


async def main() -> int:
    setup_logging("nse_pledge_data")
    logger = logging.getLogger(__name__)

    from nidp.services.nse_pledge_data.service import run
    try:
        result = await run()
        logger.info("nse_pledge_data: result=%s", json.dumps(result))
        print(json.dumps(result, indent=2))
        return 0 if result.get("status") in ("OK", "SKIPPED") else 1
    except Exception:
        logger.exception("nse_pledge_data: unhandled error")
        return 1
    finally:
        from nidp.shared.sources.nse_fetcher import close
        await close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
