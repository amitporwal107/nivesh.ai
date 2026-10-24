"""Execution modes and the per-user live-execution authorization.

MODES names every way a position could come into being, so the risk gate (services/risk_gate) can refuse one by
name instead of not knowing it:
    paper     a record the platform keeps (the desk, the journal, the AI trader's paper trades)
    shadow    a simulated order beside a real one; not built, refused by the gate's policy
    assisted  the user places the order at their own broker from a ticket the platform prepared
    live      the platform places the order through the user's own Kite Connect session; not built

LIVE_EXECUTION_AVAILABLE is a code constant and it is False: this system has no order path
(tests/test_order_path_guard.py fails on any order call outside services/oms/adapters/). It changes only in the
release that builds that adapter, through review. Nothing at runtime sets it: not the database, not an admin, not a
restart.

A live authorization is a grant an admin records for one user, with a reason. It is necessary, never sufficient:
`is_live_allowed` needs the constant AND the grant. Every change is appended to `risk_control_audit` (field
"live_authorization") before the grant is written, the same order as risk_controls.set_control, so a change can
never land without a trace of who made it.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from services import risk_controls as rc

logger = logging.getLogger(__name__)

MODES = ("paper", "shadow", "assisted", "live")
LIVE_EXECUTION_AVAILABLE = False
AUTHORIZATIONS = "live_authorizations"


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat()


def default_authorization(user_id: str) -> Dict[str, Any]:
    """What a user with no stored row has: not granted, said explicitly rather than implied."""
    return {"user_id": user_id, "granted": False, "granted_by": None, "reason": None, "at": None, "stored": False}


async def read_live_authorization(db, user_id: str) -> Dict[str, Any]:
    """The user's grant, or the not-granted default. A read failure is raised, never read as a grant."""
    doc = await db[AUTHORIZATIONS].find_one({"user_id": user_id})
    if not doc:
        return default_authorization(user_id)
    return {"user_id": user_id, "granted": bool(doc.get("granted")), "granted_by": doc.get("granted_by"),
            "reason": doc.get("reason"), "at": doc.get("at"), "stored": True}


async def set_live_authorization(db, user_id: str, granted: bool, reason: Any, actor: str,
                                 now: Optional[datetime] = None) -> Dict[str, Any]:
    """Grant or revoke, recording the change first. `granted_by` is whoever made the latest change, either way.
    Raises risk_controls.RiskControlError (a 422 for the caller) without writing anything on bad input."""
    if not isinstance(granted, bool):
        raise rc.RiskControlError("granted must be true or false")
    text = rc.clean_reason(reason, required=True)
    stamp = _iso(now or rc.utcnow())
    before = await read_live_authorization(db, user_id)
    await db[rc.AUDIT].insert_one({
        "_id": str(uuid.uuid4()),
        "user_id": user_id,
        "at": stamp,
        "actor": actor,
        "action": "set_live_authorization",
        "field": "live_authorization",
        "before": bool(before.get("granted")),
        "after": granted,
        "reason": text,
        "policy_version": rc.POLICY_VERSION,
    })
    await db[AUTHORIZATIONS].update_one(
        {"user_id": user_id},
        {"$set": {"granted": granted, "granted_by": actor, "reason": text, "at": stamp},
         "$setOnInsert": {"user_id": user_id}},
        upsert=True,
    )
    logger.warning("execution_modes: %s set live_authorization=%s for %s (%s)", actor, granted, user_id, text)
    return await read_live_authorization(db, user_id)


async def is_live_allowed(db, user_id: str) -> bool:
    """True only when live execution exists in this build AND the user holds a grant. An unreadable grant is False."""
    if not LIVE_EXECUTION_AVAILABLE:
        return False
    try:
        auth = await read_live_authorization(db, user_id)
    except Exception as e:  # noqa: BLE001 — fail closed: an unreadable grant is no grant
        logger.error("execution_modes: live authorization unreadable for %s (%s)", user_id, type(e).__name__)
        return False
    return bool(auth.get("granted"))
