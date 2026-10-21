"""Risk controls: the kill switch and the trading halt (services/risk_controls.py).

    GET  /api/risk/status          the signed-in user's controls and what they block
    PUT  /api/risk/kill-switch     set or clear the kill switch; a reason is required
    PUT  /api/risk/halt            set or clear the trading halt; a reason is required
    GET  /api/risk/audit           the append-only record of every change

Scope, stated because the name invites a bigger reading: this blocks a user's position-CREATING
paths (AI-trader tickets, desk paper trades, journal trades). It is not an order kill switch — this
system places no orders (docs/RISK_CONTROL_INVENTORY.md). It does not close or unwind anything
already open: blocking new risk and unwinding existing risk are different decisions, and only the
first is implemented.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Query, Request

from deps import db, get_current_user
from services import risk_controls as rc

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/risk", tags=["risk"])


async def _body(request: Request) -> Any:
    try:
        return json.loads(await request.body())
    except ValueError:
        raise HTTPException(status_code=422, detail="invalid_body")


def _actor(user: Dict[str, Any]) -> str:
    return str(user.get("user_id") or "unknown")


@router.get("/status")
async def status(request: Request) -> Dict[str, Any]:
    """What is blocked for this user right now, and who set it."""
    user = await get_current_user(request)
    state = await rc.read(db, _actor(user))
    return {
        **state,
        "scope": "blocks new positions on the AI-trader ticket, desk paper-trade and journal paths",
        "not_in_scope": "no order is placed anywhere in this system, and open positions are untouched",
        "policy_version": rc.POLICY_VERSION,
    }


async def _set(request: Request, field: str) -> Dict[str, Any]:
    user = await get_current_user(request)
    body = await _body(request)
    if not isinstance(body, dict) or "enabled" not in body:
        raise HTTPException(status_code=422, detail={"code": "invalid_input",
                                                     "message": "enabled (true/false) is required"})
    enabled = body.get("enabled")
    if not isinstance(enabled, bool):
        raise HTTPException(status_code=422, detail={"code": "invalid_input",
                                                     "message": "enabled must be true or false"})
    try:
        state = await rc.set_control(db, _actor(user), field=field, value=enabled,
                                     reason=body.get("reason"), actor=_actor(user))
    except rc.RiskControlError as e:
        # Clearing without a reason is refused on purpose: the record is the point.
        raise HTTPException(status_code=422, detail={"code": "invalid_input", "message": str(e)})
    return {**state, "policy_version": rc.POLICY_VERSION}


@router.put("/kill-switch")
async def kill_switch(request: Request) -> Dict[str, Any]:
    """Body: {enabled: bool, reason: str}. The reason is required in BOTH directions — turning a
    control off without saying why is the change most worth having on record."""
    return await _set(request, "kill_switch")


@router.put("/halt")
async def halt(request: Request) -> Dict[str, Any]:
    """Body: {enabled: bool, reason: str}."""
    return await _set(request, "halted")


@router.get("/audit")
async def audit(request: Request, limit: int = Query(50, ge=1, le=rc.MAX_AUDIT_LISTED)) -> Dict[str, Any]:
    """Every change, newest first. Append only: nothing here is updated or deleted."""
    user = await get_current_user(request)
    rows = await rc.audit_rows(db, _actor(user), limit)
    return {"events": rows, "count": len(rows), "append_only": True,
            "policy_version": rc.POLICY_VERSION}
