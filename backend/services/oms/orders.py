"""The order store: one document per order, created at most once per `client_order_id`.

IDEMPOTENCY
The caller supplies `client_order_id`. A unique index on `(user_id, client_order_id)` makes the second
insert fail; the store then returns the order already there — provided the request is the same. The
same key with a different payload is a conflict, not a replay, and is refused: silently returning the
first order would hide a caller bug, and silently creating a second would double a position.

STATE CHANGES ARE COMPARE-AND-SET
`transition` writes only if the order is still in the state it read. If another writer moved it first,
nothing is written and StaleOrderState says so. Every change is appended to `history`.

MODES
Only `paper` and `shadow` orders can be created. `live` is refused: there is no broker adapter, and live
authorization lives with the risk controls, not here.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pymongo.errors import DuplicateKeyError

from . import states

ORDERS = "oms_orders"
CONTRACT_VERSION = "oms-contract-v1"

MODES = ("paper", "shadow", "assisted", "live")
CREATABLE_MODES = ("paper", "shadow")
MAX_CLIENT_ORDER_ID = 64


class InvalidOrder(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class IdempotencyConflict(RuntimeError):
    """The same client_order_id was sent with a different request."""


class StaleOrderState(RuntimeError):
    """The order changed state between the read and the write; nothing was written."""


class OrderNotFound(LookupError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def fingerprint(mode: str, legs: List[Dict[str, Any]]) -> str:
    """A stable hash of what was asked for, so a replay can be told apart from a different request."""
    body = json.dumps({"mode": mode, "legs": legs}, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(body.encode()).hexdigest()


async def ensure_indexes(db) -> None:
    await db[ORDERS].create_index([("user_id", 1), ("client_order_id", 1)], unique=True,
                                  name="user_client_order_unique")
    await db[ORDERS].create_index([("user_id", 1), ("created_at", -1)], name="user_created")
    await db[ORDERS].create_index("correlation_id", name="correlation")


def _validate(client_order_id: Any, mode: Any, legs: Any) -> str:
    if not isinstance(client_order_id, str) or not client_order_id.strip():
        raise InvalidOrder("client_order_id_required", "client_order_id is required")
    cid = client_order_id.strip()
    if len(cid) > MAX_CLIENT_ORDER_ID:
        raise InvalidOrder("client_order_id_too_long", f"client_order_id is longer than {MAX_CLIENT_ORDER_ID}")
    if mode == "live":
        raise InvalidOrder("live_not_available", "live orders cannot be created: no broker adapter exists")
    if mode not in CREATABLE_MODES:
        raise InvalidOrder("invalid_mode", f"mode must be one of {', '.join(CREATABLE_MODES)}")
    if not isinstance(legs, list) or not legs:
        raise InvalidOrder("legs_required", "an order needs at least one leg")
    return cid


async def create_order(db, *, user_id: str, client_order_id: str, mode: str, legs: List[Dict[str, Any]],
                       correlation_id: Optional[str], risk_decision_id: Optional[str],
                       actor_id: Optional[str] = None, source: Optional[str] = None) -> Dict[str, Any]:
    """Create the order, or return the one this key already made. Returns `{"order": doc, "created": bool}`."""
    cid = _validate(client_order_id, mode, legs)
    fp = fingerprint(mode, legs)
    at = _now()
    doc = {
        "_id": str(uuid.uuid4()),
        "user_id": user_id,
        "client_order_id": cid,
        "mode": mode,
        "legs": legs,
        "fingerprint": fp,
        "state": states.CREATED,
        "history": [{"state": states.CREATED, "at": at, "by": actor_id or user_id, "note": None}],
        "correlation_id": correlation_id,
        "risk_decision_id": risk_decision_id,
        "broker_order_id": None,
        "source": source,
        "contract_version": CONTRACT_VERSION,
        "created_at": at,
        "updated_at": at,
    }
    try:
        await db[ORDERS].insert_one(doc)
    except DuplicateKeyError:
        existing = await db[ORDERS].find_one({"user_id": user_id, "client_order_id": cid})
        if existing is None:                       # the duplicate vanished between insert and read
            raise
        if existing.get("fingerprint") != fp:
            raise IdempotencyConflict(f"client_order_id {cid} was already used for a different order")
        return {"order": existing, "created": False}
    return {"order": doc, "created": True}


async def transition(db, *, user_id: str, order_id: str, target: str, actor_id: Optional[str] = None,
                     note: Optional[str] = None, broker_order_id: Optional[str] = None) -> Dict[str, Any]:
    """Move one order to `target` if the state machine allows it and nobody moved it first."""
    order = await db[ORDERS].find_one({"_id": order_id, "user_id": user_id})
    if order is None:
        raise OrderNotFound(order_id)
    current = order["state"]
    states.check_transition(current, target)
    at = _now()
    change: Dict[str, Any] = {"state": target, "updated_at": at}
    if broker_order_id is not None:
        change["broker_order_id"] = broker_order_id
    entry = {"state": target, "at": at, "by": actor_id or user_id, "note": note}
    res = await db[ORDERS].update_one({"_id": order_id, "user_id": user_id, "state": current},
                                      {"$set": change, "$push": {"history": entry}})
    if not res.matched_count:
        raise StaleOrderState(f"order {order_id} is no longer {current}")
    return {**order, **change, "history": [*order.get("history", []), entry]}
