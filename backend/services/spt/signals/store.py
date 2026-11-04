"""The `spt_signal_events` collection: one immutable document per scanner observation (DESIGN.md §3).

`_id` = `signal_id` = `sig:<day>:<widget>:<SYMBOL>` for a list mark, `sig:<day>:strong:<SYMBOL>` for a strong signal. The
collection is INSERT-ONLY: nothing here updates a stored event, so its original score and timestamp can never be
overwritten (PRD §18 rule 7). A second delivery of the same mark hits the `_id` and is reported as a duplicate. Which
opportunity a signal joined is read from `spt_opportunities` (`signals.signal_id`), not written back here.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Optional, Set

from .. import constants as C

logger = logging.getLogger(__name__)

COLL = C.SIGNAL_EVENTS
MAX_LIMIT = 500
_indexed = False


def is_duplicate(exc: Exception) -> bool:
    return type(exc).__name__ == "DuplicateKeyError" or "duplicate key" in str(exc).lower()


async def ensure_indexes(db) -> None:
    global _indexed
    if _indexed:
        return
    c = db[COLL]
    await c.create_index([("day", 1), ("detected_at", 1)])
    await c.create_index([("symbol", 1), ("day", 1)])
    await c.create_index([("scanner_id", 1), ("day", 1)])
    await c.create_index([("status", 1), ("day", 1)])
    await c.create_index([("received_at", 1)])
    _indexed = True


async def insert(db, doc: Dict[str, Any]) -> bool:
    """True when stored, False when an event with this `_id` exists (a duplicate delivery). Other errors propagate."""
    await ensure_indexes(db)
    try:
        await db[COLL].insert_one(doc)
        return True
    except Exception as e:  # noqa: BLE001 — only a duplicate key is expected; anything else is re-raised
        if is_duplicate(e):
            return False
        raise


async def get(db, signal_id: str) -> Optional[Dict[str, Any]]:
    return await db[COLL].find_one({"_id": signal_id})


async def existing_ids(db, ids: Iterable[str]) -> Set[str]:
    """The ids of `ids` already stored (read in chunks of 500)."""
    ids = list(dict.fromkeys(ids))
    out: Set[str] = set()
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        docs = await db[COLL].find({"_id": {"$in": chunk}}, {"_id": 1}).to_list(length=None)
        out.update(d["_id"] for d in docs)
    return out


async def list_signals(db, *, day: Optional[str] = None, symbol: Optional[str] = None, scanner_id: Optional[str] = None,
                       category: Optional[str] = None, status: Optional[str] = None, days: Optional[List[str]] = None,
                       limit: int = MAX_LIMIT, newest_first: bool = True,
                       received_since: Optional[str] = None) -> List[Dict[str, Any]]:
    """Events matching every given filter, by detection time (newest first unless `newest_first` is False). limit 0 = all."""
    q: Dict[str, Any] = {}
    if received_since:
        q["received_at"] = {"$gte": received_since}
    if day:
        q["day"] = day
    elif days:
        q["day"] = {"$in": list(days)}
    if symbol:
        q["symbol"] = symbol
    if scanner_id:
        q["scanner_id"] = scanner_id
    if category:
        q["category"] = category
    if status:
        q["status"] = status
    cur = db[COLL].find(q).sort("detected_at", -1 if newest_first else 1)
    if limit:
        cur = cur.limit(int(limit))
    return await cur.to_list(length=None)
