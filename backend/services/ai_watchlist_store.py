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


def run_start(list_date: str, earlier: List[str], stored_days: List[str]) -> str:
    """The first stored list day of the run that ends on `list_date` (the run run_of_days counts); `list_date` itself for
    an idea that is new on it."""
    on, start = set(earlier), list_date
    for d in sorted((x for x in stored_days if x < list_date), reverse=True):
        if d not in on:
            break
        start = d
    return start


# What a carry-forward tag needs of an earlier day's entry: its plan's levels, or the scanner's / the stored levels
# engine's on a day stored before plans. A projection, so a day's full plans are not read for a tag.
LEVEL_FIELDS = {"_id": 0, "list_date": 1,
                "cash.symbol": 1, "cash.trade_plan_id": 1, "cash.trade_plan.entry.price": 1, "cash.trade_plan.stop.price": 1,
                "cash.trade_plan.targets": 1, "cash.scanner.entry": 1, "cash.scanner.stop": 1, "cash.scanner.target": 1,
                "fno.underlying": 1, "fno.trade_plan_id": 1, "fno.trade_plan.entry.net_premium_rs": 1, "fno.trade_plan.stop.price": 1,
                "fno.trade_plan.targets": 1, "fno.net_premium": 1, "fno.strategy_levels.result.underlying.stop": 1,
                "fno.strategy_levels.result.underlying.target": 1}


async def days_for_levels(dates: List[str]) -> Dict[str, Dict[str, Any]]:
    """{list_date: that day's entries, projected to LEVEL_FIELDS} for the given stored days."""
    if not dates:
        return {}
    docs = await db[COL].find({"_id": {"$in": sorted(set(dates))}}, LEVEL_FIELDS).to_list(length=len(set(dates)))
    return {d["list_date"]: d for d in docs}


def entry_levels(e: Dict[str, Any], seg: str, list_date: str) -> Dict[str, Any]:
    """{list_date, entry, entry_kind, stop, target, plan_id, basis} of one stored entry, as stored that day (display
    only). Cash: the plan's entry, stop and primary target (else the scanner's). F&O: the plan's net premium and its
    underlying stop and target 1 (else the levels engine's answer stored with the day)."""
    tp = e.get("trade_plan") or {}
    prim = next((t for t in tp.get("targets") or [] if isinstance(t, dict) and t.get("primary")), None)
    if seg == "cash":
        if tp:
            return {"list_date": list_date, "entry": (tp.get("entry") or {}).get("price"), "entry_kind": "price",
                    "stop": (tp.get("stop") or {}).get("price"), "target": (prim or {}).get("price"),
                    "plan_id": e.get("trade_plan_id"), "basis": "trade_plan"}
        sc = e.get("scanner") or {}
        return {"list_date": list_date, "entry": sc.get("entry"), "entry_kind": "price", "stop": sc.get("stop"),
                "target": sc.get("target"), "plan_id": None, "basis": "scanner"}
    if tp:
        return {"list_date": list_date, "entry": (tp.get("entry") or {}).get("net_premium_rs"), "entry_kind": "net_premium",
                "stop": (tp.get("stop") or {}).get("price"), "target": (prim or {}).get("price"),
                "plan_id": e.get("trade_plan_id"), "basis": "trade_plan"}
    und = ((e.get("strategy_levels") or {}).get("result") or {}).get("underlying") or {}
    return {"list_date": list_date, "entry": e.get("net_premium"), "entry_kind": "net_premium", "stop": und.get("stop"),
            "target": und.get("target"), "plan_id": None, "basis": "strategy_levels" if und else "none"}

