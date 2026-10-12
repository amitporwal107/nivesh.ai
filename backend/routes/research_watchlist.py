"""Research Watchlist API — powers the public /watchlist page.

No auth (`/api/public/...`, the established no-auth prefix — see
`routes/client_cas_invite.py`'s `public_router` for the precedent). This is
personal/internal equity research, not a recommendation the app pushes to
users: it is a static page you have to know the URL for, not linked from any
in-app navigation.

Lists are dated snapshots (`services/research_watchlist_store`): the default
response is the newest list, `?date=YYYY-MM-DD` returns an earlier one, and
`meta.available_dates` is what the page's list picker shows. Each item's
`earlier_list_dates` names the earlier lists that stock was also in.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from datetime import date

from fastapi import APIRouter, HTTPException, Query

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
async def get_research_watchlist(
    list_date: Optional[date] = Query(None, alias="date", description="List to show (YYYY-MM-DD); newest when omitted"),
) -> Dict[str, Any]:
    available = await store.list_dates()
    if list_date is None:
        selected = available[0]["list_date"] if available else None
    else:
        selected = list_date.isoformat()
        if not any(d["list_date"] == selected for d in available):
            raise HTTPException(status_code=404, detail=f"No research watchlist was published for {selected}")
    picks: List[Dict[str, Any]] = await store.list_picks(selected) if selected else []
    # Quotes are fetched for every list's symbols, not just this one's: the
    # live cache holds one batch for all callers, so a per-list fetch would
    # leave the other lists' stocks without a quote until the TTL lapsed.
    quotes = await live.get_live_quotes(await store.all_symbols()) if picks else {}
    items = [_overlay_live_quote(p, quotes.get(p["symbol"])) for p in picks]
    # Mark the picks that were already in an earlier list (the page badges them).
    earlier = await store.earlier_list_dates(selected) if picks else {}
    for item in items:
        item["earlier_list_dates"] = earlier.get(item["symbol"], [])
    return {
        "meta": {
            "count": len(items),
            "carried_over": sum(1 for item in items if item["earlier_list_dates"]),
            "list_date": selected,
            "available_dates": available,
            "disclaimer": DISCLAIMER,
            "live_quotes_source": "yahoo_finance",
        },
        "items": items,
    }
