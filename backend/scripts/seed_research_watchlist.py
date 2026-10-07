#!/usr/bin/env python3
"""seed_research_watchlist.py — one-off load of the Research Watchlist content.

Reads `scripts/data/research_watchlist_seed.json` (41 research entries,
exported from the working research database) and upserts each into
`research_watchlist_picks`. For a symbol seen for the FIRST time, also
fetches its real current price from NIDP (via the DaaS client) and stamps
it as `published_price`/`published_date` — the fixed baseline every future
day's `change_since_published_pct` is measured against. Re-running this
script (e.g. to fix a typo in the research text) never resets that baseline
for a symbol that's already seeded — see
`services/research_watchlist_store.seed_pick`.

Usage:
    docker exec nivesh-staging-app-backend python -m scripts.seed_research_watchlist

Exit codes:
  0 — every symbol seeded (price fetch failures are logged, not fatal —
      a symbol with no resolvable price is seeded with published_price=None
      rather than a fabricated number, and is simply shown as
      "price unavailable" on the page until a later refresh resolves it).
  1 — could not even load the seed JSON / reach the DB.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

log = logging.getLogger("seed_research_watchlist")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

SEED_PATH = ROOT / "scripts" / "data" / "research_watchlist_seed.json"


async def run() -> dict:
    from services import research_watchlist_store as store  # noqa: E402
    from services.copilot_tools.daas_client import get_prices_latest_batch  # noqa: E402

    try:
        research = json.loads(SEED_PATH.read_text())
    except Exception as e:  # noqa: BLE001
        log.error("could not load seed file %s: %s", SEED_PATH, e)
        raise

    symbols = [r["symbol"] for r in research]
    today = date.today().isoformat()

    log.info("fetching live prices for %d symbols from NIDP DaaS...", len(symbols))
    prices = await get_prices_latest_batch(symbols)
    missing = [s for s in symbols if s not in prices]
    if missing:
        log.warning("no live price resolved for %d/%d symbols (will seed with published_price=None): %s",
                    len(missing), len(symbols), ", ".join(missing))

    seeded = 0
    for r in research:
        sym = r["symbol"]
        await store.seed_pick(r, published_price=prices.get(sym), published_date=today)
        seeded += 1
        log.info("seeded %s (price=%s)", sym, prices.get(sym, "unresolved"))

    return {"seeded": seeded, "priced": len(prices), "unpriced": len(missing), "symbols_unpriced": missing}


if __name__ == "__main__":
    result = asyncio.run(run())
    log.info("done: %s", result)
