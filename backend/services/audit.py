"""Audit trail writer (DPDP compliance).

Writes immutable audit records for every data-access event. Backed by
MongoDB collection `audit_log`. Fields:
    _id (mongo)
    audit_id   : stable uuid
    user_id    : actor (empty for anonymous)
    action     : enum (login, logout, cas_upload, portfolio_view,
                 portfolio_refresh, pan_view, pan_update, plan_apply,
                 consent_grant, consent_withdraw, data_export,
                 data_delete, admin_override)
    resource   : target id (holding_id, plan_id, etc.)
    ip, ua     : source metadata (truncated)
    outcome    : success | denied | error
    details    : free-form dict (sanitised — never store PAN/password)
    ts         : UTC ISO8601

Index: (user_id, ts desc) for "my audit trail"; (action, ts) for admin.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

AUDIT_ACTIONS = {
    "login", "logout", "login_failed",
    "cas_upload", "cas_parse_failed",
    "portfolio_view", "portfolio_refresh",
    "pan_view", "pan_update", "pan_delete",
    "plan_generate", "plan_apply", "plan_skip",
    "consent_grant", "consent_withdraw",
    "data_export", "data_delete",
    "admin_override", "admin_impersonate",
    "broker_connect", "broker_sync", "broker_disconnect",
}


def _sanitise(details: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Strip anything that looks like PAN / password / token from details."""
    if not details:
        return None
    clean: Dict[str, Any] = {}
    for k, v in details.items():
        kl = k.lower()
        if any(bad in kl for bad in ("password", "pan_plain", "aadhaar", "otp", "token", "secret")):
            clean[k] = "[REDACTED]"
        elif isinstance(v, str) and len(v) > 500:
            clean[k] = v[:500] + "…"
        else:
            clean[k] = v
    return clean


async def record(
    *,
    user_id: str,
    action: str,
    resource: Optional[str] = None,
    ip: Optional[str] = None,
    ua: Optional[str] = None,
    outcome: str = "success",
    details: Optional[Dict[str, Any]] = None,
) -> str:
    """Write one audit row. Returns audit_id. Best-effort — never raises."""
    if action not in AUDIT_ACTIONS:
        logger.info("audit.record: unknown action %s", action)
    entry = {
        "audit_id": f"aud_{uuid.uuid4().hex[:12]}",
        "user_id": user_id or "",
        "action": action,
        "resource": resource,
        "ip": (ip or "")[:64],
        "ua": (ua or "")[:200],
        "outcome": outcome,
        "details": _sanitise(details),
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    try:
        from deps import db
        await db.audit_log.insert_one(entry)
        # Mongo mutates the input dict — strip _id for return.
        return entry["audit_id"]
    except Exception as e:  # noqa: BLE001
        logger.warning("audit write failed (action=%s): %s", action, e)
        return entry["audit_id"]


async def list_for_user(user_id: str, limit: int = 100) -> List[Dict[str, Any]]:
    """Return the user's own audit trail (most recent first)."""
    from deps import db
    cursor = db.audit_log.find(
        {"user_id": user_id}, {"_id": 0},
    ).sort("ts", -1).limit(limit)
    return await cursor.to_list(limit)


async def list_admin(
    action: Optional[str] = None, limit: int = 200,
) -> List[Dict[str, Any]]:
    """Admin view: recent activity across all users (audit team use)."""
    from deps import db
    query: Dict[str, Any] = {}
    if action:
        query["action"] = action
    cursor = db.audit_log.find(query, {"_id": 0}).sort("ts", -1).limit(limit)
    return await cursor.to_list(limit)
