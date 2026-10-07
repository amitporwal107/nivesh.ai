"""Research Watchlist API — powers the public /watchlist page.

No auth (`/api/public/...`, the established no-auth prefix — see
`routes/client_cas_invite.py`'s `public_router` for the precedent). This is
personal/internal equity research, not a recommendation the app pushes to
users: it is a static page you have to know the URL for, not linked from any
in-app navigation.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from datetime import date

from fastapi import APIRouter

from services import research_watchlist_live as live
from services import research_watchlist_store as store

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/public/research-watchlist", tags=["research-watchlist-public"])

DISCLAIMER = (
    "Personal / internal equity research only. Not investment advice, not a product "
    "recommendation, and not a buy or sell call. Figures are point-in-time and will "
    "drift — re-verify before acting on anything here."
)


def _overlay_live_quote(pick: Dict[str, Any], quote: Dict[str, Any] | None) -> Dict[str, Any]:
    """Overlay a live Yahoo Finance quote onto one stored pick. Never
    mutates the Mongo-backed fields in place — `pick` is already a plain
    dict from `list_picks()`. Falls back to the last cron-refreshed
    current_price when no live quote is available (cold cache / Yahoo down),
    so the page never shows a blank price, only a stale-but-honest one."""
    pick = dict(pick)
    if quote and quote.get("price") is not None:
        price = quote["price"]
        pick["current_price"] = price
        pick["current_price_date"] = date.today().isoformat()
        pick["day_change"] = quote.get("day_change")
        pick["day_change_pct"] = quote.get("day_change_pct")
        pick["is_live"] = True
        published_price = pick.get("published_price")
        if published_price:
            pick["change_since_published_pct"] = round((price / published_price - 1) * 100, 2)
    else:
        pick["day_change"] = None
        pick["day_change_pct"] = None
        pick["is_live"] = False
    return pick


@router.get("")
async def get_research_watchlist() -> Dict[str, Any]:
    picks: List[Dict[str, Any]] = await store.list_picks()
    symbols = [p["symbol"] for p in picks]
    quotes = await live.get_live_quotes(symbols)
    items = [_overlay_live_quote(p, quotes.get(p["symbol"])) for p in picks]
    return {
        "meta": {
            "count": len(items),
            "disclaimer": DISCLAIMER,
            "live_quotes_source": "yahoo_finance",
        },
        "items": items,
    }
