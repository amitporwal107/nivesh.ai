"""Results week — the nightly point-in-time snapshot (MongoDB).

  results_week_days — one document per date (YYYY-MM-DD), `_id` = date: the GET /api/desk/results-week body as built
      that night by scripts/build_results_week.py, without the per-user Chartink column (joined at read time for the
      signed-in user). Written once (`insert_day` refuses to replace): a stored day is never rewritten, so the
      validation study (docs/EARNINGS_SURPRISE_TRACKER.md §7) reads what was known that night.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

COL = "results_week_days"


def _db():
    from deps import db
    return db


async def insert_day(doc: Dict[str, Any], db=None) -> bool:
    """Store one day. False when that day is already stored (it is never overwritten)."""
    from pymongo.errors import DuplicateKeyError

    db = db if db is not None else _db()
    try:
        await db[COL].insert_one({**doc, "_id": doc["date"]})
    except DuplicateKeyError:
        return False
    return True


async def has_day(day: str, db=None) -> bool:
    db = db if db is not None else _db()
    return await db[COL].find_one({"_id": day}, {"_id": 1}) is not None


async def get_day(day: str, db=None) -> Optional[Dict[str, Any]]:
    db = db if db is not None else _db()
    return await db[COL].find_one({"_id": day}, {"_id": 0})
