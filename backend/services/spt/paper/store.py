"""Slice C's Mongo access (DESIGN.md §3, D1, D7): spt_orders, spt_fills, spt_positions and the loop's spt_state row.

NO MULTI-DOCUMENT TRANSACTIONS (staging Mongo is one node). Every state change is ONE conditional update whose filter
names the state(s) it expects and the `version` it read; a writer that lost the race matches nothing and re-reads.
Fills are keyed `<order_id>:<seq>` with a unique (order_id, seq) index, so a replayed or concurrent round can never
record a fill twice: the second insert collides and is discarded. The fills are the truth; an order's filled figures and
a position's quantity are derived from them (orders.sync_order, positions.apply_order_fills) and can always be rebuilt.

Timestamps are UTC ISO strings; the IST trading day is kept as `day` / `session_day`.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time as dtime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

from services.spt import constants as C

logger = logging.getLogger(__name__)

ORDERS, FILLS, POSITIONS, STATE, EVENTS, PROPOSALS = C.ORDERS, C.FILLS, C.POSITIONS, C.STATE, C.EVENTS, C.PROPOSALS
STATE_ID = "spt_c"
SOURCE = "spt-paper"                                  # events.source_service of this slice

IST = timezone(timedelta(hours=5, minutes=30))
OPEN, CLOSE = dtime(9, 15), dtime(15, 30)

_indexed = False


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: Optional[datetime] = None) -> str:
    return (dt or utcnow()).astimezone(timezone.utc).isoformat()


def parse_ts(value: Any) -> Optional[datetime]:
    """An ISO stamp as an aware datetime (a naive stamp is IST: the feed's stamps are IST), or None."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=IST)
    if not value:
        return None
    try:
        d = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=IST)


def ist_day(now: datetime) -> date:
    return now.astimezone(IST).date()


def in_session(now: datetime) -> bool:
    """09:15–15:30 IST on a weekday. Holidays are not looked up here: on a holiday the feed is not live, so no quote is
    fresh and nothing fills (the same rule as services/kite_live_feed/day_quote.in_session)."""
    t = now.astimezone(IST)
    return t.weekday() < 5 and OPEN <= t.time() <= CLOSE


def session_day_for(now: datetime) -> date:
    """The session a DAY order created at `now` belongs to: today when it is a weekday before 15:30 IST, else the next
    weekday."""
    t = now.astimezone(IST)
    d = t.date()
    if t.weekday() < 5 and t.time() < CLOSE:
        return d
    d += timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def day_close(d: date) -> datetime:
    return datetime.combine(d, CLOSE, tzinfo=IST)


async def ensure_indexes(db) -> None:
    """Asked once per process; a failure is logged and asked again next call (the indexes are the uniqueness guarantee
    of fills and open positions, so the round that hits a failure still runs: Mongo then refuses nothing extra)."""
    global _indexed
    if _indexed:
        return
    try:
        await db[ORDERS].create_index("idempotency_key", unique=True)
        await db[ORDERS].create_index([("user_id", 1), ("created_at", -1)])
        await db[ORDERS].create_index([("state", 1), ("created_at", 1)])
        await db[ORDERS].create_index([("position_id", 1)])
        await db[ORDERS].create_index([("proposal_id", 1)])
        await db[FILLS].create_index([("order_id", 1), ("seq", 1)], unique=True)
        await db[FILLS].create_index([("user_id", 1), ("at", -1)])
        await db[FILLS].create_index([("position_id", 1)])
        await db[POSITIONS].create_index("entry_order_id", unique=True)
        await db[POSITIONS].create_index([("user_id", 1), ("symbol", 1), ("direction", 1)], unique=True,
                                         partialFilterExpression={"is_open": True})
        await db[POSITIONS].create_index([("user_id", 1), ("state", 1)])
        await db[POSITIONS].create_index([("state", 1)])
        _indexed = True
    except Exception as e:  # noqa: BLE001
        logger.warning("spt paper: indexes not created (%s)", type(e).__name__)


async def transition(db, coll: str, doc_id: str, *, expect_states: Iterable[str], expect_version: int,
                     to_state: Optional[str] = None, set_: Optional[Dict[str, Any]] = None,
                     inc: Optional[Dict[str, Any]] = None, push: Optional[Dict[str, Any]] = None,
                     unset: Optional[Dict[str, Any]] = None, now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """ONE conditional update: matches only while the document is in one of `expect_states` at `expect_version`.
    Returns the document after the update, or None when another writer got there first (the caller re-reads)."""
    fields: Dict[str, Any] = {"updated_at": iso(now)}
    if to_state is not None:
        fields["state"] = to_state
    fields.update(set_ or {})
    update: Dict[str, Any] = {"$set": fields, "$inc": {"version": 1, **(inc or {})}}
    if push:
        update["$push"] = push
    if unset:
        update["$unset"] = unset
    res = await db[coll].update_one({"_id": doc_id, "state": {"$in": list(expect_states)}, "version": expect_version},
                                    update)
    if not res.matched_count:
        return None
    return await db[coll].find_one({"_id": doc_id})


async def get_order(db, order_id: str) -> Optional[Dict[str, Any]]:
    return await db[ORDERS].find_one({"_id": order_id})


async def get_position(db, position_id: str) -> Optional[Dict[str, Any]]:
    return await db[POSITIONS].find_one({"_id": position_id})


async def fills_of(db, order_id: str) -> List[Dict[str, Any]]:
    rows = await db[FILLS].find({"order_id": order_id}).to_list(None)
    return sorted(rows, key=lambda f: int(f.get("seq") or 0))


async def live_orders(db, *, user_id: Optional[str] = None, purpose: Optional[str] = None,
                      position_id: Optional[str] = None, limit: int = 2000) -> List[Dict[str, Any]]:
    q: Dict[str, Any] = {"state": {"$in": list(C.ORD_LIVE_STATES)}}
    if user_id:
        q["user_id"] = user_id
    if purpose:
        q["purpose"] = purpose
    if position_id:
        q["position_id"] = position_id
    rows = await db[ORDERS].find(q).sort("created_at", 1).limit(limit).to_list(limit)
    return rows


async def open_positions(db, *, user_id: Optional[str] = None, limit: int = 2000) -> List[Dict[str, Any]]:
    q: Dict[str, Any] = {"state": {"$in": list(C.POS_OPEN_STATES)}}
    if user_id:
        q["user_id"] = user_id
    return await db[POSITIONS].find(q).sort("created_at", 1).limit(limit).to_list(limit)


async def write_state(db, fields: Dict[str, Any]) -> None:
    """The loop's row for the morning check: {_id: "spt_c", ...}. A failure is logged, never raised."""
    try:
        await db[STATE].update_one({"_id": STATE_ID}, {"$set": fields}, upsert=True)
    except Exception as e:  # noqa: BLE001
        logger.warning("spt paper: state row not written (%s)", type(e).__name__)


async def read_state(db) -> Dict[str, Any]:
    return await db[STATE].find_one({"_id": STATE_ID}) or {}


def r2(x: Optional[float]) -> Optional[float]:
    return None if x is None else round(float(x), 2)
