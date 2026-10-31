"""What the positions workspace keeps in Mongo. Nothing here talks to a broker.

position_snapshots   one document per broker account each time its positions read CHANGES:
                       {_id, user_id, account_id, broker, read_at, last_seen_at, broker_as_of, rows_hash, row_count, rows}
                     `read_at` is when Nivesh read the broker. `broker_as_of` is the broker's own time for the book; the
                     position reads of the connected brokers send none, so it is null rather than Nivesh's clock under
                     the broker's name. A read identical to the account's latest snapshot only moves that snapshot's
                     `last_seen_at`, so a page refresh does not add a document.
position_levels      the user's own stop, target and trailing stop for one underlying of their broker positions, which
                     brokers never send:
                       {_id = "<user_id>|<UNDERLYING>", user_id, underlying, stop, target, trail_pct, peak, trough,
                        created_at, updated_at}
                     `peak` / `trough` are the highest / lowest underlying price seen since the trail was set (read
                     time), from which the trailing stop is worked out.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

SNAPSHOTS = "position_snapshots"
LEVELS = "position_levels"
MAX_TRAIL_PCT = 50.0

_indexed = False


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def ensure_indexes(db) -> None:
    global _indexed
    if _indexed:
        return
    await db[SNAPSHOTS].create_index([("user_id", 1), ("account_id", 1), ("read_at", -1)])
    await db[LEVELS].create_index([("user_id", 1), ("underlying", 1)], unique=True)
    _indexed = True


def rows_hash(rows: List[Dict[str, Any]]) -> str:
    return hashlib.sha256(json.dumps(rows, sort_keys=True, default=str).encode()).hexdigest()


async def record_snapshot(db, *, user_id: str, account_id: str, broker: str, read_at: str,
                          rows: List[Dict[str, Any]], broker_as_of: Optional[str] = None) -> str:
    """Store the read when it differs from the account's latest snapshot; return the snapshot id either way."""
    h = rows_hash(rows)
    last = await db[SNAPSHOTS].find_one({"user_id": user_id, "account_id": account_id}, {"_id": 1, "rows_hash": 1},
                                        sort=[("read_at", -1)])
    if last and last.get("rows_hash") == h:
        await db[SNAPSHOTS].update_one({"_id": last["_id"]}, {"$set": {"last_seen_at": read_at}})
        return last["_id"]
    sid = f"ps_{uuid.uuid4().hex[:16]}"
    await db[SNAPSHOTS].insert_one({"_id": sid, "user_id": user_id, "account_id": account_id, "broker": broker,
                                    "read_at": read_at, "last_seen_at": read_at, "broker_as_of": broker_as_of,
                                    "rows_hash": h, "row_count": len(rows), "rows": rows})
    return sid


# What a position IS (not what it is worth now): the fields that identify the contract and the size and cost held.
STRUCTURE_FIELDS = ("symbol", "exchange", "quantity", "avg_price", "product_raw", "instrument_type", "expiry", "strike")


def structure_hash(rows: List[Dict[str, Any]]) -> str:
    """A hash of what the rows hold, ignoring prices and P&L, so a quote tick does not look like a new book."""
    shape = sorted(([r.get(f) for f in STRUCTURE_FIELDS] for r in rows), key=lambda x: json.dumps(x, default=str))
    return hashlib.sha256(json.dumps(shape, default=str).encode()).hexdigest()


async def latest_snapshot(db, user_id: str, account_id: str) -> Optional[Dict[str, Any]]:
    """The account's newest stored read ({rows, read_at, last_seen_at, ...}) or None. Tenant-scoped on both ids."""
    return await db[SNAPSHOTS].find_one({"user_id": user_id, "account_id": account_id}, sort=[("read_at", -1)])


async def record_book_snapshot(db, *, user_id: str, account_id: str, broker: str, read_at: str,
                               rows: List[Dict[str, Any]]) -> str:
    """Store a polled read: refresh the latest snapshot in place when the account still holds the same positions, else add a
    document. Returns the snapshot id."""
    s_hash, h = structure_hash(rows), rows_hash(rows)
    last = await latest_snapshot(db, user_id, account_id)
    if last and (last.get("structure_hash") or structure_hash(last.get("rows") or [])) == s_hash:
        await db[SNAPSHOTS].update_one({"_id": last["_id"]}, {"$set": {"rows": rows, "rows_hash": h, "structure_hash": s_hash,
                                                                       "last_seen_at": read_at, "row_count": len(rows)}})
        return last["_id"]
    sid = f"ps_{uuid.uuid4().hex[:16]}"
    await db[SNAPSHOTS].insert_one({"_id": sid, "user_id": user_id, "account_id": account_id, "broker": broker,
                                    "read_at": read_at, "last_seen_at": read_at, "broker_as_of": None, "rows_hash": h,
                                    "structure_hash": s_hash, "row_count": len(rows), "rows": rows})
    return sid


def level_id(user_id: str, underlying: str) -> str:
    return f"{user_id}|{underlying}"


async def read_levels(db, user_id: str) -> Dict[str, Dict[str, Any]]:
    return {d["underlying"]: d async for d in db[LEVELS].find({"user_id": user_id})}


def validate_levels(body: Dict[str, Any]) -> Dict[str, Optional[float]]:
    """{stop, target, trail_pct} from a request body, or ValueError with the reason. Every field is optional but at
    least one is required; a price is above zero; the trail is a percent in (0, 50]."""
    allowed = {"stop", "target", "trail_pct"}
    extra = set(body) - allowed
    if extra:
        raise ValueError(f"unknown field: {sorted(extra)[0]}")
    out: Dict[str, Optional[float]] = {}
    for k in allowed:
        v = body.get(k)
        if v is None:
            out[k] = None
            continue
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or v in (float("inf"), float("-inf")):
            raise ValueError(f"{k} must be a number")
        if v <= 0:
            raise ValueError(f"{k} must be above zero")
        out[k] = float(v)
    if all(v is None for v in out.values()):
        raise ValueError("set a stop, a target or a trailing stop")
    if out["trail_pct"] is not None and out["trail_pct"] > MAX_TRAIL_PCT:
        raise ValueError(f"trail_pct must be at most {MAX_TRAIL_PCT:g}")
    if out["stop"] is not None and out["target"] is not None and out["stop"] == out["target"]:
        raise ValueError("the stop and the target cannot be the same price")
    return out


async def save_levels(db, user_id: str, underlying: str, levels: Dict[str, Optional[float]]) -> Dict[str, Any]:
    at = now_iso()
    doc = {"user_id": user_id, "underlying": underlying, **levels, "updated_at": at}
    # A new or changed trail starts its peak / trough again from the next read.
    await db[LEVELS].update_one({"_id": level_id(user_id, underlying)},
                                {"$set": {**doc, "peak": None, "trough": None}, "$setOnInsert": {"created_at": at}},
                                upsert=True)
    return await db[LEVELS].find_one({"_id": level_id(user_id, underlying)})


async def delete_levels(db, user_id: str, underlying: str) -> bool:
    res = await db[LEVELS].delete_one({"_id": level_id(user_id, underlying)})
    return bool(res.deleted_count)


def effective_stop(levels: Dict[str, Any], price: Optional[float], direction: Optional[str]) -> Optional[float]:
    """The stop in force: the fixed stop, tightened by the trail from the best price seen (long: peak × (1 − trail);
    short: trough × (1 + trail)). The trail never loosens a fixed stop."""
    stop, trail = levels.get("stop"), levels.get("trail_pct")
    if not trail or direction not in ("long", "short"):
        return stop
    long = direction == "long"
    seen = [x for x in (levels.get("peak" if long else "trough"), price) if x]
    trailed = None
    if seen:
        trailed = max(seen) * (1 - trail / 100.0) if long else min(seen) * (1 + trail / 100.0)
    vals = [x for x in (stop, trailed) if x]
    if not vals:
        return None
    return max(vals) if long else min(vals)


async def track_extremes(db, levels: Dict[str, Any], price: Optional[float]) -> None:
    """Move a trailing stop's peak / trough with the price just read (only when a trail is set and the price is new)."""
    if not levels.get("trail_pct") or not price:
        return
    upd: Dict[str, float] = {}
    if levels.get("peak") is None or price > levels["peak"]:
        upd["peak"] = price
    if levels.get("trough") is None or price < levels["trough"]:
        upd["trough"] = price
    if upd:
        await db[LEVELS].update_one({"_id": levels["_id"]}, {"$set": upd})
        levels.update(upd)
