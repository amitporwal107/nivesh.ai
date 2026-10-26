"""The kill switch and the trading halt: a store, so they can actually be set.

WHY THIS EXISTS
`risk_governor.Limits`/`Portfolio` have carried `kill_switch` and `halted` since the governor was
written, with the comment "set by a person", and `risk_governor.py:112-115` enforces them correctly.
Nothing ever set them: `routes/ai_trader.py` built its Portfolio without those fields, so they held
their dataclass defaults (False) on every evaluation. The enforcement was right and could never fire,
which is worse than absent — the field makes the control look present. See
docs/RISK_CONTROL_INVENTORY.md.

WHAT THIS DOES AND DOES NOT CLAIM
It blocks a user's position-creating paths: the AI-trader ticket flow, the desk paper trade and the
journal. It is NOT an order kill switch, because this system places no orders — a repository-wide
search for place_order/modify_order/cancel_order finds only a comment saying they are never called,
and the Kite wrapper exposes no order method. When execution is built, the gate belongs in front of
it and this store is what it should read.

It also does not touch positions that are already open. Blocking new risk and unwinding existing risk
are different decisions with different consequences; this implements the first and says so, rather
than assuming the second.

EVERY CHANGE IS RECORDED
Setting or clearing requires a reason and appends to an immutable log (`risk_control_audit`): who,
when, from what to what, and why. A control whose history can be overwritten cannot be relied on
afterwards by the person who set it or by anyone reviewing it.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

CONTROLS = "risk_controls"
AUDIT = "risk_control_audit"
#: Append-only record of every risk decision and every denial. Separate from AUDIT, which records
#: changes to the CONTROLS themselves: "who turned the switch on" and "what the governor decided"
#: are different questions and mixing them makes both harder to read.
DECISIONS = "risk_decisions"

#: Bumped when the meaning of a stored field changes, so an audit row can be read back correctly.
POLICY_VERSION = "risk-controls-v1"

MAX_REASON = 500
MAX_AUDIT_LISTED = 200

#: What a user is blocked from doing while the switch is on. Named so a caller can say which one it hit.
BLOCKED_ACTIONS = ("ai_trader_ticket", "desk_paper_trade", "journal_trade")


class RiskControlError(ValueError):
    """Bad input to a control change; the caller turns this into a 422."""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def session_actor(user: Dict[str, Any]) -> str:
    """Who is acting: the signed-in person (`_session_user_id`), not the client profile an advisor is acting for.
    An audit row that named the client would record the wrong person as having flipped the control."""
    return str(user.get("_session_user_id") or user.get("user_id") or "unknown")


_indexes_ready = False


async def ensure_indexes(db) -> None:
    """The indexes the controls, the audit, the decision log and the live grants are read by. Asked for once per
    process; a failure is logged and asked for again on the next call (the services/desk_trading.py pattern). They
    are an optimisation and a uniqueness guarantee on one row per user, so a failure never blocks a read."""
    global _indexes_ready
    if _indexes_ready:
        return
    from services.execution_modes import AUTHORIZATIONS        # that module imports this one
    try:
        await db[CONTROLS].create_index([("user_id", 1)], unique=True)
        await db[AUDIT].create_index([("user_id", 1), ("at", -1)])
        await db[DECISIONS].create_index([("user_id", 1), ("at", -1)])
        await db[DECISIONS].create_index([("correlation_id", 1)])
        await db[AUTHORIZATIONS].create_index([("user_id", 1)], unique=True)
        _indexes_ready = True
    except Exception as exc:  # noqa: BLE001
        logger.warning("risk_controls: the indexes could not be created: %r", exc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def clean_reason(value: Any, *, required: bool) -> Optional[str]:
    """A reason is mandatory for every change. 'Why' is the part that is useless to reconstruct later."""
    text = "" if value is None else str(value).strip()
    if not text:
        if required:
            raise RiskControlError("a reason is required")
        return None
    if len(text) > MAX_REASON:
        raise RiskControlError(f"the reason must be at most {MAX_REASON} characters")
    return text


def default_state(user_id: str) -> Dict[str, Any]:
    """What a user with no stored row has: nothing blocked, and said explicitly rather than implied."""
    return {
        "user_id": user_id,
        "kill_switch": False,
        "halted": False,
        "reason": None,
        "set_by": None,
        "set_at": None,
        "policy_version": POLICY_VERSION,
        "stored": False,
    }


def public_state(doc: Optional[Dict[str, Any]], user_id: str) -> Dict[str, Any]:
    if not doc:
        return default_state(user_id)
    out = {
        "user_id": user_id,
        "kill_switch": bool(doc.get("kill_switch")),
        "halted": bool(doc.get("halted")),
        "reason": doc.get("reason"),
        "set_by": doc.get("set_by"),
        "set_at": doc.get("set_at"),
        "policy_version": doc.get("policy_version") or POLICY_VERSION,
        "stored": True,
    }
    out["blocking"] = out["kill_switch"] or out["halted"]
    out["blocked_actions"] = list(BLOCKED_ACTIONS) if out["blocking"] else []
    return out


async def read(db, user_id: str) -> Dict[str, Any]:
    """The user's controls. A read failure is NOT treated as 'not blocked': the caller is told the
    state is unknown so it can fail closed, because an unreadable kill switch must never read as off."""
    try:
        doc = await db[CONTROLS].find_one({"user_id": user_id})
    except Exception as e:  # noqa: BLE001
        logger.error("risk_controls: state unreadable for %s (%s)", user_id, type(e).__name__)
        raise
    state = public_state(doc, user_id)
    if not state.get("blocking"):
        state.setdefault("blocking", False)
        state.setdefault("blocked_actions", [])
    return state


async def audit_rows(db, user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    cur = db[AUDIT].find({"user_id": user_id}).sort("at", -1).limit(min(limit, MAX_AUDIT_LISTED))
    rows = await cur.to_list(min(limit, MAX_AUDIT_LISTED))
    for r in rows:
        r.pop("_id", None)
    return rows


async def set_control(db, user_id: str, *, field: str, value: bool, reason: str, actor: str,
                      now: Optional[datetime] = None) -> Dict[str, Any]:
    """Set `kill_switch` or `halted`, recording the change. Returns the new public state.

    The audit row is written BEFORE the state changes: if the process dies between the two, the record
    shows an attempted change that may not have applied, which a reviewer can detect. The reverse
    order could change the control with no trace of who did it."""
    if field not in ("kill_switch", "halted"):
        raise RiskControlError("field must be kill_switch or halted")
    text = clean_reason(reason, required=True)
    moment = now or utcnow()
    before = await read(db, user_id)

    await db[AUDIT].insert_one({
        "_id": str(uuid.uuid4()),
        "user_id": user_id,
        "at": _iso(moment),
        "actor": actor,
        "action": f"set_{field}",
        "field": field,
        "before": bool(before.get(field)),
        "after": bool(value),
        "reason": text,
        "policy_version": POLICY_VERSION,
    })

    await db[CONTROLS].update_one(
        {"user_id": user_id},
        {"$set": {field: bool(value), "reason": text, "set_by": actor, "set_at": _iso(moment),
                  "policy_version": POLICY_VERSION},
         "$setOnInsert": {"user_id": user_id}},
        upsert=True,
    )
    logger.warning("risk_controls: %s set %s=%s for %s (%s)", actor, field, value, user_id, text)
    return await read(db, user_id)


async def assert_allowed(db, user_id: str, action: str) -> None:
    """Raise RiskBlocked when the user's controls block this action.

    Fails CLOSED: if the store cannot be read the action is refused, because a kill switch that
    silently reads as 'off' when the database is unreachable is not a kill switch."""
    try:
        state = await read(db, user_id)
    except Exception as e:  # noqa: BLE001
        raise RiskBlocked("risk controls could not be read, so new risk is refused",
                          state={"readable": False}) from e
    if state.get("kill_switch"):
        raise RiskBlocked("the kill switch is on; new positions are blocked", state=state)
    if state.get("halted"):
        raise RiskBlocked("trading is halted; new positions are blocked", state=state)


class RiskBlocked(RuntimeError):
    """A control blocks this action. Carries the state so the caller can say which control and why."""

    def __init__(self, message: str, state: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.state = state or {}

    def detail(self, action: str) -> Dict[str, Any]:
        return {
            "code": "risk_blocked",
            "action": action,
            "message": str(self),
            "reason": self.state.get("reason"),
            "set_by": self.state.get("set_by"),
            "set_at": self.state.get("set_at"),
            "kill_switch": self.state.get("kill_switch"),
            "halted": self.state.get("halted"),
            "note": "Positions already open are untouched. Clearing the control needs a reason and is recorded.",
        }


async def record_decision(db, user_id: str, *, action: str, outcome: str,
                          symbol: Optional[str] = None, requested_qty: Optional[int] = None,
                          approved_qty: Optional[int] = None,
                          reasons: Optional[List[Dict[str, Any]]] = None,
                          limits_version: Optional[str] = None,
                          correlation_id: Optional[str] = None,
                          detail: Optional[Dict[str, Any]] = None,
                          now: Optional[datetime] = None) -> Optional[str]:
    """Append one risk decision to `risk_decisions`. Returns the event id, or None if it could not be
    written.

    Why this exists: the governor's decision was previously kept only on the ticket document it
    produced, which is mutable and overwritten in place. A decision that can be rewritten cannot be
    reconstructed afterwards, nor PROVED to have been made — which matters as much to the operator as
    to the user (docs/RISK_CONTROL_INVENTORY.md).

    A failed write is logged at ERROR and returns None rather than raising. The caller is already
    writing its ticket or trade to the same database, so a log failure almost certainly means that
    write is about to fail too; refusing the trade here would add nothing but a confusing second
    error. The kill switch is the control that fails closed — this is the record of what happened.
    The F&O risk gate does NOT use this function: its decision is the authority for the write that
    follows, so services/risk_gate writes its own row and raises when it cannot (fail closed).
    """
    event_id = str(uuid.uuid4())
    row = {
        "_id": event_id,
        "user_id": user_id,
        "at": _iso(now or utcnow()),
        "action": action,
        "outcome": outcome,
        "symbol": symbol,
        "requested_qty": requested_qty,
        "approved_qty": approved_qty,
        "reasons": reasons or [],
        "limits_version": limits_version,
        "policy_version": POLICY_VERSION,
        "correlation_id": correlation_id,
        "detail": detail or {},
    }
    try:
        await db[DECISIONS].insert_one(row)
    except Exception as e:  # noqa: BLE001
        logger.error("risk_controls: decision NOT recorded for %s (%s): action=%s outcome=%s",
                     user_id, type(e).__name__, action, outcome)
        return None
    if outcome != "allowed":
        logger.warning("risk_controls: %s %s for %s (%s)", action, outcome, user_id, symbol or "-")
    return event_id


async def decision_rows(db, user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    # The decision snapshot is left out (projection, and popped for stores that ignore it): POST .../replay reads it.
    cur = db[DECISIONS].find({"user_id": user_id}, {"snapshot": 0}).sort("at", -1).limit(min(limit, MAX_AUDIT_LISTED))
    rows = await cur.to_list(min(limit, MAX_AUDIT_LISTED))
    for r in rows:
        r["event_id"] = r.pop("_id", None)
        r.pop("snapshot", None)
    return rows
