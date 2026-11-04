"""What the exit watch keeps in Mongo (docs/paper_pnl_dashboard/EXIT_WATCH.md). Every read and write is scoped to one user.

exit_watch_levels   one document per user and watched position: the 2 × ATR trailing stop and how the position was
                    watched at the last round
                      {_id = "<user_id>|<key>", user_id, key, account_id, underlying, side, kind, method, stop, day, atr,
                       atr_pct, close, floor, history[], active, first_seen_at, updated_at}
                    `method` records the last round's method (atr_trail / put_floor / call_cap): a stored floor or cap
                    with the hedge gone from the book is how HEDGE_REMOVED is found.
exit_alerts         one document per fired alert; `_id` = sha1(user|key|kind|dedupe), so a second round inserts
                    nothing (duplicate key = it already fired)
                      {_id, user_id, key, account_id, account, underlying, kind, severity, day, at, price, level, source,
                       source_at, text, rule, seen, seen_at}
exit_watch_state    the watcher's own rounds, no user data: {_id: "live", at, users, positions, fired, stale, feed_why}
                    and {_id: "eod", day, at, pending[]}
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from pymongo.errors import DuplicateKeyError

logger = logging.getLogger(__name__)

LEVELS = "exit_watch_levels"
ALERTS = "exit_alerts"
STATE = "exit_watch_state"
ALERTS_SHOWN = 100

_indexed = False


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def ensure_indexes(db) -> None:
    global _indexed
    if _indexed:
        return
    await db[LEVELS].create_index([("user_id", 1), ("active", 1)])
    await db[ALERTS].create_index([("user_id", 1), ("day", -1)])
    await db[ALERTS].create_index([("user_id", 1), ("seen", 1)])
    _indexed = True


def level_id(user_id: str, key: str) -> str:
    return f"{user_id}|{key}"


def alert_id(user_id: str, key: str, kind: str, dedupe: str) -> str:
    return hashlib.sha1(f"{user_id}|{key}|{kind}|{dedupe}".encode()).hexdigest()


async def read_levels(db, user_id: str) -> Dict[str, Dict[str, Any]]:
    """{key: level doc} of the user's stored levels (active or not)."""
    return {d["key"]: d for d in await db[LEVELS].find({"user_id": user_id}).to_list(None)}


async def save_level(db, user_id: str, key: str, fields: Dict[str, Any], *, at: Optional[str] = None) -> None:
    at = at or now_iso()
    await db[LEVELS].update_one({"_id": level_id(user_id, key)},
                                {"$set": {**fields, "user_id": user_id, "key": key, "updated_at": at},
                                 "$setOnInsert": {"first_seen_at": at}}, upsert=True)


async def deactivate_missing(db, user_id: str, keys: Iterable[str], *, at: Optional[str] = None) -> int:
    """Mark the user's stored levels whose position is no longer in the book inactive. Returns how many."""
    keep = set(keys)
    n = 0
    for d in await db[LEVELS].find({"user_id": user_id, "active": True}).to_list(None):
        if d["key"] not in keep:
            await db[LEVELS].update_one({"_id": d["_id"], "user_id": user_id},
                                        {"$set": {"active": False, "updated_at": at or now_iso()}})
            n += 1
    return n


async def fire(db, user_id: str, key: str, kind: str, dedupe: str, doc: Dict[str, Any]) -> bool:
    """Insert one alert; False when it already fired (the same _id exists)."""
    body = {**doc, "_id": alert_id(user_id, key, kind, dedupe), "user_id": user_id, "key": key, "kind": kind,
            "seen": False, "at": doc.get("at") or now_iso()}
    try:
        await db[ALERTS].insert_one(body)
    except DuplicateKeyError:
        return False
    return True


async def recent_alerts(db, user_id: str, since_day: str, limit: int = ALERTS_SHOWN) -> List[Dict[str, Any]]:
    """The user's alerts from `since_day` on, newest first."""
    return await db[ALERTS].find({"user_id": user_id, "day": {"$gte": since_day}}).sort("at", -1).limit(limit).to_list(limit)


async def unseen_count(db, user_id: str) -> int:
    return await db[ALERTS].count_documents({"user_id": user_id, "seen": False})


async def mark_seen(db, user_id: str, ids: Optional[List[str]] = None) -> int:
    """Mark the user's unseen alerts seen (only those in `ids` when given). Returns how many changed."""
    q: Dict[str, Any] = {"user_id": user_id, "seen": False}
    if ids is not None:
        if not ids:
            return 0
        q["_id"] = {"$in": list(ids)}
    res = await db[ALERTS].update_many(q, {"$set": {"seen": True, "seen_at": now_iso()}})
    return int(getattr(res, "modified_count", 0) or 0)


async def read_state(db) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for name in ("live", "eod"):
        try:
            out[name] = await db[STATE].find_one({"_id": name}) or {}
        except Exception as e:  # noqa: BLE001 — the watcher line says unknown rather than failing the read
            logger.warning("exit_watch: state unreadable (%s)", type(e).__name__)
            out[name] = {}
    return out


async def write_state(db, name: str, fields: Dict[str, Any]) -> None:
    await db[STATE].update_one({"_id": name}, {"$set": fields}, upsert=True)
