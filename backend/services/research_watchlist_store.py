"""Research Watchlist — MongoDB store.

Backs the public, no-auth `/watchlist` page: a curated list of Indian-equity
research picks (symbol, sector, tier, thesis, and per-company fundamental /
technical notes), each tracked against the real market price on the day it
was added to the list.

Storage model (one collection, keyed by symbol):

  research_watchlist_picks — one document per symbol. `published_price` /
    `published_date` are stamped once, at seed time, from a real DaaS price
    fetch and never overwritten. `current_price` / `current_price_date` /
    `change_since_published_pct` are refreshed daily by
    `scripts.refresh_research_watchlist_prices` (see that file) and are
    `None` until the first refresh has run.

This is personal/internal equity research, not investment advice — see the
page's own disclaimer. Nothing here is a recommendation the app "serves" as
advice; it is a static research note with a price tracker.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from deps import db

logger = logging.getLogger(__name__)

COL = "research_watchlist_picks"

# Fields seeded from the research itself; never touched by the price-refresh cron.
_RESEARCH_FIELDS = (
    "symbol", "company_name", "sector", "tier", "rank", "source_label",
    "thesis", "stage_full", "balance_sheet_notes", "order_book", "capex_plans",
    "management_notes", "technical_notes", "revenue_cagr_3y", "eps_cagr_3y",
    "cagr_window", "roce_pct", "cfo_pat_ratio_3y", "debt_to_ebitda",
    "pledge_pct_of_promoter", "promoter_pct", "market_cap_cr", "pe_ttm",
    "sector_pe_median", "pct_from_52w_high", "px_vs_dma200_pct", "ret_6m_pct",
    "latest_q_end", "latest_q_rev_yoy", "latest_q_pat_yoy", "trend_cagr_used",
    "trend_label", "deep_dive_status",
)


async def list_picks() -> List[Dict[str, Any]]:
    """All picks, ordered by rank. Mongo's own `_id` is dropped (symbol is the key)."""
    cursor = db[COL].find({}, {"_id": 0}).sort("rank", 1)
    return [doc async for doc in cursor]


async def get_pick(symbol: str) -> Optional[Dict[str, Any]]:
    return await db[COL].find_one({"symbol": symbol}, {"_id": 0})


async def seed_pick(research: Dict[str, Any], *, published_price: Optional[float],
                     published_date: str) -> None:
    """Insert or refresh the research content for one symbol.

    Only the research fields + the (write-once) published_price/published_date
    are set here — never `current_price` etc., so re-running the seed script
    to fix a typo in the research text can never clobber the live price track.
    `published_price`/`published_date` are set with `$setOnInsert` semantics
    (via a plain `update_one(..., upsert=True)` that only writes them the
    first time a symbol is seen) so a re-seed never resets the baseline.
    """
    symbol = research["symbol"]
    research_doc = {k: research.get(k) for k in _RESEARCH_FIELDS}
    existing = await db[COL].find_one({"symbol": symbol}, {"published_price": 1, "published_date": 1})
    update: Dict[str, Any] = {"$set": research_doc}
    if existing is None:
        update["$set"]["published_price"] = published_price
        update["$set"]["published_date"] = published_date
        update["$set"]["current_price"] = published_price
        update["$set"]["current_price_date"] = published_date
        update["$set"]["change_since_published_pct"] = 0.0 if published_price is not None else None
        update["$set"]["price_updated_at"] = None
    await db[COL].update_one({"symbol": symbol}, update, upsert=True)


async def update_current_price(symbol: str, *, current_price: Optional[float],
                                current_price_date: Optional[str]) -> None:
    """Called by the daily cron. Never touches published_price/published_date
    or any research field — a price-feed outage degrades gracefully to
    `current_price=None`, it never fabricates a stale-but-confident number."""
    doc = await db[COL].find_one({"symbol": symbol}, {"published_price": 1})
    if doc is None:
        logger.warning("update_current_price: unknown symbol %s, skipping", symbol)
        return
    published_price = doc.get("published_price")
    change_pct = None
    if current_price is not None and published_price:
        change_pct = round((current_price / published_price - 1) * 100, 2)
    await db[COL].update_one(
        {"symbol": symbol},
        {"$set": {
            "current_price": current_price,
            "current_price_date": current_price_date,
            "change_since_published_pct": change_pct,
            "price_updated_at": datetime.now(timezone.utc).isoformat(),
        }},
    )


async def all_symbols() -> List[str]:
    cursor = db[COL].find({}, {"_id": 0, "symbol": 1})
    return [doc["symbol"] async for doc in cursor]
