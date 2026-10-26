"""AI scanner watchlist — the daily Top 10 cash and Top 10 F&O ideas, one stored list per scan day (MongoDB).

Written once a day by scripts/build_ai_watchlist.py after the AI scanner run, read by GET /api/desk/ai-watchlist
(signed in; the /app/watchlist page). Not the public research watchlist (services/research_watchlist_store): these are the
scanner's ideas, for signed-in users only.

  ai_watchlist_days — one document per `list_date` (the scan date, YYYY-MM-DD), `_id` = list_date:
      list_date, built_at, rules (where each list came from and by what rule), notes (the routes' ranking notes, caveats
      and data dates), cash: [...], fno: [...]. Each entry is a snapshot of what the route returned that day, so a later
      day's change in the scanner never rewrites an earlier list. A day is written once (`insert_day` refuses to replace).

Ideas for review, not recommendations; nothing here places an order.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from deps import db

COL = "ai_watchlist_days"
LOOKBACK_DAYS = 30


async def insert_day(doc: Dict[str, Any]) -> bool:
    """Store one day's lists. False when that day is already stored (it is never overwritten)."""
    from pymongo.errors import DuplicateKeyError

    try:
        await db[COL].insert_one({**doc, "_id": doc["list_date"]})
    except DuplicateKeyError:
        return False
    return True


async def has_day(list_date: str) -> bool:
    return await db[COL].find_one({"_id": list_date}, {"_id": 1}) is not None


async def get_day(list_date: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """That day's lists, or the newest day's when `list_date` is None."""
    if list_date:
        return await db[COL].find_one({"_id": list_date}, {"_id": 0})
    docs = await db[COL].find({}, {"_id": 0}).sort("list_date", -1).limit(1).to_list(length=1)
    return docs[0] if docs else None


async def dateline(limit: int = 120) -> List[Dict[str, Any]]:
    """Every stored day, newest first, with how many ideas each list holds (the page's dateline)."""
    rows = await db[COL].aggregate([
        {"$sort": {"list_date": -1}},
        {"$limit": limit},
        {"$project": {"_id": 0, "list_date": 1, "built_at": 1,
                      "cash": {"$size": {"$ifNull": ["$cash", []]}}, "fno": {"$size": {"$ifNull": ["$fno", []]}}}},
    ]).to_list(length=limit)
    return rows


async def earlier_appearances(list_date: str, lookback_days: int = LOOKBACK_DAYS) -> Dict[str, Dict[str, List[str]]]:
    """For each segment, symbol -> the earlier list dates (within `lookback_days`, newest first) it was on."""
    since = (date.fromisoformat(list_date) - timedelta(days=lookback_days)).isoformat()
    out: Dict[str, Dict[str, List[str]]] = {"cash": {}, "fno": {}}
    cursor = db[COL].find({"list_date": {"$lt": list_date, "$gte": since}},
                          {"_id": 0, "list_date": 1, "cash.symbol": 1, "fno.underlying": 1}).sort("list_date", -1)
    async for d in cursor:
        for e in d.get("cash") or []:
            if e.get("symbol"):
                out["cash"].setdefault(e["symbol"], []).append(d["list_date"])
        for e in d.get("fno") or []:
            if e.get("underlying"):
                out["fno"].setdefault(e["underlying"], []).append(d["list_date"])
    return out


def run_of_days(list_date: str, earlier: List[str], stored_days: List[str]) -> int:
    """How many stored list days in a row, ending on `list_date`, the symbol was on (1 = new today). A day with no stored
    list (a holiday, a missed run) does not break the run; only a stored day without the symbol does."""
    on = set(earlier)
    n = 1
    for d in sorted((x for x in stored_days if x < list_date), reverse=True):
        if d not in on:
            break
        n += 1
    return n
