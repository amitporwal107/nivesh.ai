"""AI scanner watchlist API (signed in) — the daily Top 10 cash and Top 10 F&O ideas that scripts/build_ai_watchlist.py
stores after each AI scanner run (services/ai_watchlist_store). Powers the AI scanner block of /app/watchlist.

GET /api/desk/ai-watchlist              the newest stored day
GET /api/desk/ai-watchlist?date=YYYY-MM-DD   that day (404 not_stored when there is none; 422 for a malformed date)

The body is the day's lists as stored (every figure is what the routes answered that day), plus:
  available_dates      the dateline: every stored day, newest first, with how many cash and F&O ideas it holds
  earlier_list_dates   per entry, the earlier stored days within 30 days that it was also on (newest first)
  days_on_list         per entry, how many stored days in a row ending on this one it was on (1 = new that day)
With no stored day yet the answer is 200 with empty lists and `empty_reason`. Reads only. Ideas for review, not
recommendations; nothing places an order.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query, Request

from deps import get_current_user
from services import ai_watchlist_store as store

router = APIRouter(prefix="/api/desk/ai-watchlist", tags=["desk"])

NO_LIST_YET = ("No list is stored yet. The job runs each weekday at 22:45 IST, after the AI scanner's run and the "
               "day's NSE F&O bhavcopy, and keeps every day's list.")


def annotate(doc: Dict[str, Any], earlier: Dict[str, Dict[str, list]], stored_days: list) -> Dict[str, Any]:
    day = doc["list_date"]
    for seg, key in (("cash", "symbol"), ("fno", "underlying")):
        for e in doc.get(seg) or []:
            prev = earlier.get(seg, {}).get(e.get(key), [])
            e["earlier_list_dates"] = prev
            e["days_on_list"] = store.run_of_days(day, prev, stored_days)
    return doc


@router.get("")
async def get_ai_watchlist(request: Request,
                           day: Optional[str] = Query(None, alias="date", pattern=r"^\d{4}-\d{2}-\d{2}$")) -> Dict[str, Any]:
    await get_current_user(request)
    days = await store.dateline()
    if not days:
        return {"list_date": None, "available_dates": [], "cash": [], "fno": [], "notes": {}, "rules": {},
                "empty_reason": NO_LIST_YET, "read_only": True}
    doc = await store.get_day(day)
    if doc is None:
        raise HTTPException(status_code=404, detail={"code": "not_stored", "message": f"No AI scanner watchlist is stored for {day}."})
    earlier = await store.earlier_appearances(doc["list_date"])
    annotate(doc, earlier, [d["list_date"] for d in days])
    return {**doc, "available_dates": days, "read_only": True}
