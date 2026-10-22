#!/usr/bin/env python3
"""seed_research_watchlist.py — load one dated Research Watchlist list.

Reads a research export (default `scripts/data/research_watchlist_seed.json`,
the 41-entry list first published 2026-10-06) and upserts each entry into
`research_watchlist_picks` under `--list-date`. Lists are dated snapshots:
seeding a new date adds a list and leaves every earlier one as it was (the
page's historical view). Documents written before lists were dated are
stamped with the first list's date on the way in.

For a symbol seen for the FIRST time in a list, also
fetches its real current price from NIDP (via the DaaS client) and stamps
it as `published_price`/`published_date` — the fixed baseline every future
day's `change_since_published_pct` is measured against. Re-running this
script (e.g. to fix a typo in the research text) never resets that baseline
for a (list, symbol) that's already seeded — see
`services/research_watchlist_store.seed_pick`.

Usage:
    docker exec nivesh-staging-app-backend python -m scripts.seed_research_watchlist
    docker exec nivesh-staging-app-backend python -m scripts.seed_research_watchlist \
        --file scripts/data/research_watchlist_20261012.json --list-date 2026-10-12

Exit codes:
  0 — every symbol seeded (price fetch failures are logged, not fatal —
      a symbol with no resolvable price is seeded with published_price=None
      rather than a fabricated number, and is simply shown as
      "price unavailable" on the page until a later refresh resolves it).
  1 — could not even load the seed JSON / reach the DB.
"""
from __future__ import annotations

import argparse
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
# The list in SEED_PATH was first published on this date (commit fb67ce55).
FIRST_LIST_DATE = "2026-10-06"


async def run(seed_path: Path = SEED_PATH, list_date: str = FIRST_LIST_DATE) -> dict:
    from services import research_watchlist_store as store  # noqa: E402
    from services.copilot_tools.daas_client import get_prices_latest_batch  # noqa: E402

    try:
        research = json.loads(seed_path.read_text())
    except Exception as e:  # noqa: BLE001
        log.error("could not load seed file %s: %s", seed_path, e)
        raise

    stamped = await store.backfill_list_date(FIRST_LIST_DATE)
    if stamped:
        log.info("stamped list_date=%s on %d pre-existing undated picks", FIRST_LIST_DATE, stamped)
    await store.ensure_indexes()

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
        await store.seed_pick(r, list_date=list_date, published_price=prices.get(sym), published_date=today)
        seeded += 1
        log.info("seeded %s (price=%s)", sym, prices.get(sym, "unresolved"))

    return {"list_date": list_date, "seeded": seeded, "priced": len(prices), "unpriced": len(missing), "symbols_unpriced": missing}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Load one dated Research Watchlist list")
    ap.add_argument("--file", type=Path, default=SEED_PATH, help="research export (JSON list)")
    ap.add_argument("--list-date", type=date.fromisoformat, default=date.fromisoformat(FIRST_LIST_DATE),
                    help="date of the list being loaded (YYYY-MM-DD)")
    args = ap.parse_args()
    result = asyncio.run(run(args.file, args.list_date.isoformat()))
    log.info("done: %s", result)
