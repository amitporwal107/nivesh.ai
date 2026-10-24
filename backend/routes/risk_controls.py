"""Risk controls: the kill switch and the trading halt (services/risk_controls.py), the live-execution grant
(services/execution_modes.py) and the F&O risk policy (services/risk_gate).

    GET  /api/risk/status          the signed-in user's controls, what they block, who may clear them, the live grant,
                                   the execution modes and whether the F&O risk gate is on for this user
    PUT  /api/risk/kill-switch     set or clear the kill switch; a reason is required; clearing needs an admin
    PUT  /api/risk/halt            set or clear the trading halt; a reason is required; clearing needs an admin
    GET  /api/risk/audit           the append-only record of every control change
    GET  /api/risk/decisions       the append-only record of every risk decision and denial
    GET  /api/risk/policy          the F&O risk policy's version, limits and this user's usage against them

    PUT  /api/admin/risk/{user_id}/kill-switch         admin only: {enabled: bool, reason: str}
    PUT  /api/admin/risk/{user_id}/halt                admin only: {enabled: bool, reason: str}
    PUT  /api/admin/risk/{user_id}/live-authorization  admin only: {granted: bool, reason: str}

Authority. Anyone may turn a control ON for their own account; clearing one is a reset and needs an admin (403
{"code": "admin_required"}), because a switch the person under pressure can flip back off is not much of a switch.
"Admin" and the audit actor are the SIGNED-IN person: when an advisor acts for a client, the control lands on the
client and the record names the advisor.

Scope, stated because the name invites a bigger reading: this blocks a user's position-CREATING paths (AI-trader
tickets, desk paper trades, journal trades). It is not an order kill switch — this system places no orders
(docs/RISK_CONTROL_INVENTORY.md). It does not close or unwind anything already open: blocking new risk and unwinding
existing risk are different decisions, and only the first is implemented.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Tuple

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request

from deps import _is_role, db, get_current_user, require_role
from services import execution_modes as modes
from services import risk_controls as rc
from services import risk_gate
from services.risk_gate import policy as risk_policy

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/risk", tags=["risk"])

_require_admin = require_role("admin")
admin_router = APIRouter(prefix="/api/admin/risk", tags=["risk-admin"], dependencies=[Depends(_require_admin)])

_ADMIN_REQUIRED = {"code": "admin_required",
                   "message": "Only an admin can clear a risk control. Ask an admin to review it and clear it."}


async def _body(request: Request) -> Any:
    try:
        return json.loads(await request.body())
    except ValueError:
        raise HTTPException(status_code=422, detail="invalid_body")


def _uid(user: Dict[str, Any]) -> str:
    return str(user.get("user_id") or "unknown")


async def _is_admin_session(user: Dict[str, Any]) -> bool:
    """Is the SIGNED-IN person an admin? Under impersonation `user` is the client, so the session owner is read."""
    owner = user.get("_session_user_id")
    if owner and owner != user.get("user_id"):
        doc = await db.users.find_one({"user_id": owner}, {"_id": 0, "role": 1, "is_admin": 1})
        return bool(doc) and _is_role(doc, "admin")
    return _is_role(user, "admin")


def _switch_body(body: Any, key: str) -> Tuple[bool, Any]:
    if not isinstance(body, dict) or key not in body:
        raise HTTPException(status_code=422, detail={"code": "invalid_input",
                                                     "message": f"{key} (true/false) is required"})
    value = body.get(key)
    if not isinstance(value, bool):
        raise HTTPException(status_code=422, detail={"code": "invalid_input",
                                                     "message": f"{key} must be true or false"})
    return value, body.get("reason")


def _invalid(e: rc.RiskControlError) -> HTTPException:
    # Clearing without a reason is refused on purpose: the record is the point.
    return HTTPException(status_code=422, detail={"code": "invalid_input", "message": str(e)})


@router.get("/status")
async def status(request: Request) -> Dict[str, Any]:
    """What is blocked for this user right now, who set it, who may clear it, and the gate's state."""
    user = await get_current_user(request)
    uid = _uid(user)
    await rc.ensure_indexes(db)
    state = await rc.read(db, uid)
    return {
        **state,
        "scope": "blocks new positions on the AI-trader ticket, desk paper-trade and journal paths",
        "not_in_scope": "no order is placed anywhere in this system, and open positions are untouched",
        "policy_version": rc.POLICY_VERSION,
        "can_reset": await _is_admin_session(user),
        "live_authorization": await modes.read_live_authorization(db, uid),
        "modes": list(modes.MODES),
        "live_execution_available": modes.LIVE_EXECUTION_AVAILABLE,
        "gate": {"enabled": await risk_gate.enabled_for(db, user), "policy_version": risk_policy.POLICY_VERSION},
    }


async def _set(request: Request, field: str) -> Dict[str, Any]:
    user = await get_current_user(request)
    enabled, reason = _switch_body(await _body(request), "enabled")
    if not enabled and not await _is_admin_session(user):
        raise HTTPException(status_code=403, detail=_ADMIN_REQUIRED)
    await rc.ensure_indexes(db)
    try:
        state = await rc.set_control(db, _uid(user), field=field, value=enabled,
                                     reason=reason, actor=rc.session_actor(user))
    except rc.RiskControlError as e:
        raise _invalid(e)
    return {**state, "policy_version": rc.POLICY_VERSION}


@router.put("/kill-switch")
async def kill_switch(request: Request) -> Dict[str, Any]:
    """Body: {enabled: bool, reason: str}. The reason is required in BOTH directions — turning a
    control off without saying why is the change most worth having on record. Off needs an admin."""
    return await _set(request, "kill_switch")


@router.put("/halt")
async def halt(request: Request) -> Dict[str, Any]:
    """Body: {enabled: bool, reason: str}. Off needs an admin."""
    return await _set(request, "halted")


@router.get("/audit")
async def audit(request: Request, limit: int = Query(50, ge=1, le=rc.MAX_AUDIT_LISTED)) -> Dict[str, Any]:
    """Every change, newest first. Append only: nothing here is updated or deleted."""
    user = await get_current_user(request)
    rows = await rc.audit_rows(db, _uid(user), limit)
    return {"events": rows, "count": len(rows), "append_only": True,
            "policy_version": rc.POLICY_VERSION}


@router.get("/decisions")
async def decisions(request: Request, limit: int = Query(50, ge=1, le=rc.MAX_AUDIT_LISTED)) -> Dict[str, Any]:
    """Every risk decision and denial, newest first.

    Separate from /audit on purpose: "who turned the switch on" and "what the governor decided" are
    different questions, and one stream would bury the other."""
    user = await get_current_user(request)
    rows = await rc.decision_rows(db, _uid(user), limit)
    return {"decisions": rows, "count": len(rows), "append_only": True,
            "policy_version": rc.POLICY_VERSION}


@router.get("/policy")
async def policy(request: Request) -> Dict[str, Any]:
    """The F&O risk policy and this user's open desk structures against it (capital at risk is the maximum loss at
    expiry, the figure the gate's cap uses; null when any open structure's figure cannot be worked out)."""
    user = await get_current_user(request)
    return {"policy_version": risk_policy.POLICY_VERSION, "limits": risk_policy.limits(),
            "usage": await risk_gate.usage(db, _uid(user))}


# ── admin ────────────────────────────────────────────────────────────────────
_TARGET = Path(..., min_length=1, max_length=64)


async def _target(request: Request, admin: Dict[str, Any], user_id: str, key: str) -> Tuple[bool, Any]:
    """The validated body for a change to another user's controls. Refuses an admin role that is only borrowed
    from an impersonated client profile, and an unknown user (a typo must not create controls for nobody)."""
    if not await _is_admin_session(admin):
        raise HTTPException(status_code=403, detail=_ADMIN_REQUIRED)
    value, reason = _switch_body(await _body(request), key)
    try:
        rc.clean_reason(reason, required=True)
    except rc.RiskControlError as e:
        raise _invalid(e)
    if not await db.users.find_one({"user_id": user_id}, {"_id": 0, "user_id": 1}):
        raise HTTPException(status_code=404, detail="user_not_found")
    await rc.ensure_indexes(db)
    return value, reason


async def _admin_set(request: Request, admin: Dict[str, Any], user_id: str, field: str) -> Dict[str, Any]:
    enabled, reason = await _target(request, admin, user_id, "enabled")
    try:
        state = await rc.set_control(db, user_id, field=field, value=enabled, reason=reason,
                                     actor=rc.session_actor(admin))
    except rc.RiskControlError as e:
        raise _invalid(e)
    return {**state, "policy_version": rc.POLICY_VERSION}


@admin_router.put("/{user_id}/kill-switch")
async def admin_kill_switch(request: Request, user_id: str = _TARGET,
                            admin: dict = Depends(_require_admin)) -> Dict[str, Any]:
    """Body: {enabled: bool, reason: str}."""
    return await _admin_set(request, admin, user_id, "kill_switch")


@admin_router.put("/{user_id}/halt")
async def admin_halt(request: Request, user_id: str = _TARGET,
                     admin: dict = Depends(_require_admin)) -> Dict[str, Any]:
    """Body: {enabled: bool, reason: str}."""
    return await _admin_set(request, admin, user_id, "halted")


@admin_router.put("/{user_id}/live-authorization")
async def admin_live_authorization(request: Request, user_id: str = _TARGET,
                                   admin: dict = Depends(_require_admin)) -> Dict[str, Any]:
    """Body: {granted: bool, reason: str}. A grant is necessary, never sufficient: live execution does not exist in
    this release (`live_execution_available` is false), so the gate keeps refusing the live mode."""
    granted, reason = await _target(request, admin, user_id, "granted")
    try:
        auth = await modes.set_live_authorization(db, user_id, granted, reason, rc.session_actor(admin))
    except rc.RiskControlError as e:
        raise _invalid(e)
    return {"live_authorization": auth, "live_execution_available": modes.LIVE_EXECUTION_AVAILABLE,
            "policy_version": rc.POLICY_VERSION}
