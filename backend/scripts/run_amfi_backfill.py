#!/usr/bin/env python3
"""Wrapper that hydrates secrets from Mongo then runs the AMFI backfill.

Usage: python -m scripts.run_amfi_backfill [--years 5]
"""
from __future__ import annotations
import argparse
import asyncio
import logging
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402
load_dotenv(ROOT / ".env")

log = logging.getLogger("amfi_backfill_runner")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


async def main(years: int) -> None:
    from motor.motor_asyncio import AsyncIOMotorClient
    from helpers import secrets as _s
    mc = AsyncIOMotorClient(os.environ["MONGO_URL"])
    try:
        await _s.hydrate_from_db(mc[os.environ["DB_NAME"]])
    finally:
        mc.close()
    pg_url = _s.get("POSTGRES_URL")
    if pg_url:
        os.environ["POSTGRES_URL"] = pg_url
        log.info(f"Secrets hydrated. POSTGRES_URL configured.")
    else:
        log.error("POSTGRES_URL missing from secrets — aborting")
        return

    from scripts.backfill_amfi_nav_history import run
    end = date.today()
    start = end - timedelta(days=365 * years)
    log.info(f"Launching AMFI backfill: {start} → {end} ({years}y)")
    t0 = time.perf_counter()
    res = await run(start, end, step_days=30, dry_run=False)
    log.info(f"DONE in {time.perf_counter() - t0:.1f}s: {res}")

    # Chain analytics sweep + rescore
    log.info("Running NAV analytics sweep…")
    from services.nav_analytics_sweep import run_analytics_sweep, run_v3_rescore
    s1 = await run_analytics_sweep()
    log.info(f"analytics_sweep: {s1}")
    s2 = await run_v3_rescore()
    log.info(f"v3_rescore: {s2}")

    from services import pg_client
    await pg_client.close_pool()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--years", type=int, default=5)
    args = p.parse_args()
    asyncio.run(main(args.years))
