#!/usr/bin/env python3
"""refresh_research_watchlist_prices.py — daily price refresh for the
Research Watchlist (/watchlist). Mirrors `run_positional_engine.py`'s
cron-runner shape.

For every symbol already in `research_watchlist_picks`, fetches today's
real close from NIDP (DaaS price client) and updates `current_price` /
`current_price_date` / `change_since_published_pct` — never touches the
research text or the `published_price` baseline. A symbol the price feed
can't resolve today is left as `current_price=None` ("price unavailable"
on the page), never backfilled with a stale or guessed number.

Usage:
    docker exec nivesh-staging-app-backend python -m scripts.refresh_research_watchlist_prices

Exit codes:
  0 — ran (even if some individual symbols couldn't be priced; see log)
  1 — fatal error reaching the DB
"""
from __future__ import annotations

import asyncio
import logging
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

log = logging.getLogger("refresh_research_watchlist_prices")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


async def run() -> dict:
    from services import research_watchlist_store as store  # noqa: E402
    from services.copilot_tools.daas_client import get_prices_latest_batch  # noqa: E402

    symbols = await store.all_symbols()
    if not symbols:
        log.warning("no symbols in research_watchlist_picks — has the seed script run?")
        return {"updated": 0, "unresolved": 0}

    today = date.today().isoformat()
    prices = await get_prices_latest_batch(symbols)

    updated = 0
    unresolved = []
    for sym in symbols:
        price = prices.get(sym)
        await store.update_current_price(
            sym,
            current_price=price,
            current_price_date=today if price is not None else None,
        )
        if price is not None:
            updated += 1
        else:
            unresolved.append(sym)

    if unresolved:
        log.warning("no price resolved today for %d/%d symbols: %s",
                    len(unresolved), len(symbols), ", ".join(unresolved))
    return {"updated": updated, "unresolved": len(unresolved), "symbols_unresolved": unresolved}


if __name__ == "__main__":
    result = asyncio.run(run())
    log.info("done: %s", result)
