"""SPT paper accounts (PRD §17.1; DESIGN.md D3, D4): the caller's paper account and its SPT configuration, and the admin's
view of any user's SPT configuration and of the market-wide SPT settings (owner decisions, 5 Nov 2026 ~06:50 IST).

    GET  /api/v1/paper/accounts                       the caller's account (one per user, D3): paper account + SPT config
    GET  /api/v1/paper/accounts/{account_id}          the same, with the config's recent version history
    PUT  /api/v1/paper/accounts/{account_id}/config   {mode?, extras?, reason?, expected_version?}: change the SPT mode
                                                      (off | tracking | approval | auto) and TIGHTEN any value (an extras
                                                      leaf set to null removes that override); LOOSENING needs an admin
                                                      (403 admin_required; an admin signed in on their own account may);
                                                      versioned (services/spt/policy.py); 422 codes on bad input, 409
                                                      concurrent_change, 503 profile_unreadable
    GET  /api/v1/paper/accounts/{account_id}/ledger   the paper account's ledger (paper_account_ledger), newest first;
                                                      ?limit= (≤ 200) &before=<at of the last row seen>

    GET  /api/admin/spt/{user_id}/config              admin: effective values, overrides, defaults (with their source),
                                                      the risk-profile limits they derive from, recent versions
    PUT  /api/admin/spt/{user_id}/config              admin: {mode?, extras?, reason (required), expected_version?}; any
                                                      direction within the ranges
    GET  /api/admin/spt/settings                      admin: the market-wide SPT settings (services/spt/settings.py)
    PUT  /api/admin/spt/settings                      admin: {values: {field: value | null}, reason, expected_version?}

account_id is the caller's user_id (D3: one account per user); any other id answers 403 not_your_account. No session
answers 401; the admin routes answer 403 to a non-admin (deps.require_role("admin"), as routes/risk_controls.py). The
defaults of the overlapping limits come from the user's risk profile (services/risk_profile; PUT /api/risk/profile).
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from deps import _is_role, db, get_current_user, require_role
from services import paper_account
from services import risk_controls as rc
from services.spt import policy
from services.spt import settings as spt_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["spt-accounts"])
_require_admin = require_role("admin")
admin_router = APIRouter(prefix="/api/admin/spt", tags=["spt-admin"], dependencies=[Depends(_require_admin)])

MAX_LEDGER = 200


def _uid(user: Dict[str, Any]) -> str:
    return str(user.get("user_id") or "")


def own(user: Dict[str, Any], account_id: str) -> str:
    """The caller's user id, or 403 when `account_id` is someone else's (D3: account_id = user_id)."""
    uid = _uid(user)
    if not uid or account_id != uid:
        raise HTTPException(status_code=403, detail={"code": "not_your_account",
                                                     "message": "You can only use your own paper account."})
    return uid


async def _body(request: Request) -> Any:
    try:
        return json.loads(await request.body() or b"{}")
    except ValueError:
        raise HTTPException(status_code=422, detail={"code": "invalid_body", "message": "The body must be JSON."})


async def summary(uid: str, *, versions: bool = False) -> Dict[str, Any]:
    out = {"account_id": uid, "account": await paper_account.read(db, uid), "config": await policy.read(db, uid),
           "modes": ["off", "tracking", "approval", "auto"],
           "note": "One paper account per user (D3); the SPT mode is off until the user opts in (D4)."}
    if versions:
        out["config_versions"] = await policy.versions(db, uid, limit=20)
    return out


@router.get("/paper/accounts")
async def list_accounts(request: Request) -> Dict[str, Any]:
    user = await get_current_user(request)
    acc = await summary(_uid(user))
    return {"accounts": [acc], "count": 1}


@router.get("/paper/accounts/{account_id}")
async def get_account(account_id: str, request: Request) -> Dict[str, Any]:
    user = await get_current_user(request)
    return await summary(own(user, account_id), versions=True)


async def is_admin_session(user: Dict[str, Any]) -> bool:
    """Is the SIGNED-IN person an admin? Under impersonation `user` is the client, so the session owner is read (the
    rule of routes/risk_controls._is_admin_session)."""
    owner = user.get("_session_user_id")
    if owner and owner != user.get("user_id"):
        doc = await db.users.find_one({"user_id": owner}, {"_id": 0, "role": 1, "is_admin": 1})
        return bool(doc) and _is_role(doc, "admin")
    return _is_role(user, "admin")


def _config_body(body: Any) -> Dict[str, Any]:
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail={"code": "invalid_body", "message": "The body must be an object."})
    unknown = set(body) - {"mode", "extras", "reason", "expected_version"}
    if unknown:
        raise HTTPException(status_code=422, detail={"code": "unknown_field",
                                                     "message": f"unknown field(s): {', '.join(sorted(unknown))}"})
    return body


async def _update(uid: str, body: Dict[str, Any], *, actor: str, actor_is_admin: bool,
                  require_reason: bool) -> Dict[str, Any]:
    await policy.ensure_indexes(db)
    try:
        return await policy.update(db, uid, actor=actor, actor_is_admin=actor_is_admin, mode=body.get("mode"),
                                   extras=body.get("extras"), reason=body.get("reason"),
                                   expected_version=body.get("expected_version"), require_reason=require_reason)
    except policy.ConfigError as e:
        raise HTTPException(status_code=e.status, detail=e.detail())


@router.put("/paper/accounts/{account_id}/config")
async def put_config(account_id: str, request: Request) -> Dict[str, Any]:
    """The account holder changes the mode and tightens any value; loosening needs an admin (403 admin_required) —
    an admin signed in on their own account may loosen (services/spt/policy.py)."""
    user = await get_current_user(request)
    uid = own(user, account_id)
    body = _config_body(await _body(request))
    config = await _update(uid, body, actor=rc.session_actor(user), actor_is_admin=await is_admin_session(user),
                           require_reason=False)
    return {"account_id": uid, "config": config}


# ── admin: any user's SPT config, and the market-wide SPT settings ───────────
@admin_router.get("/settings")
async def admin_get_settings(request: Request) -> Dict[str, Any]:
    return {**await spt_settings.read(db), "versions": await spt_settings.versions(db, limit=20)}


@admin_router.put("/settings")
async def admin_put_settings(request: Request) -> Dict[str, Any]:
    admin = await get_current_user(request)
    body = await _body(request)
    if not isinstance(body, dict) or set(body) - {"values", "reason", "expected_version"}:
        raise HTTPException(status_code=422, detail={"code": "invalid_body",
                                                     "message": "send {values: {...}, reason, expected_version?}"})
    try:
        out = await spt_settings.update(db, actor=rc.session_actor(admin), changes=body.get("values"),
                                        reason=body.get("reason"), expected_version=body.get("expected_version"))
    except spt_settings.SettingsError as e:
        raise HTTPException(status_code=e.status, detail=e.detail())
    return out


@admin_router.get("/{user_id}/config")
async def admin_get_config(user_id: str, request: Request) -> Dict[str, Any]:
    try:
        config = await policy.read(db, user_id)
    except policy.ConfigError as e:
        raise HTTPException(status_code=e.status, detail=e.detail())
    return {"account_id": user_id, "config": config, "versions": await policy.versions(db, user_id, limit=20)}


@admin_router.put("/{user_id}/config")
async def admin_put_config(user_id: str, request: Request) -> Dict[str, Any]:
    """An admin sets any user's mode and values, in any direction within the ranges; a reason is required."""
    admin = await get_current_user(request)
    body = _config_body(await _body(request))
    config = await _update(user_id, body, actor=rc.session_actor(admin), actor_is_admin=True, require_reason=True)
    return {"account_id": user_id, "config": config}


def _row(r: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(r)
    out["entry_id"] = str(out.pop("_id", ""))
    return out


@router.get("/paper/accounts/{account_id}/ledger")
async def ledger(account_id: str, request: Request, limit: int = Query(50, ge=1, le=MAX_LEDGER),
                 before: Optional[str] = Query(None, max_length=64)) -> Dict[str, Any]:
    user = await get_current_user(request)
    uid = own(user, account_id)
    q: Dict[str, Any] = {"user_id": uid}
    if before:
        q["at"] = {"$lt": before}
    rows = await db[paper_account.LEDGER].find(q).sort("at", -1).limit(limit).to_list(limit)
    items = [_row(r) for r in rows]
    return {"account_id": uid, "items": items, "count": len(items),
            "next_before": items[-1]["at"] if len(items) == limit else None,
            "source": "paper_account_ledger (services/paper_account.py): reserve / release / cancel_reservation / adjust"}
