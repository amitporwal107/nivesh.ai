"""SPT paper accounts (PRD §17.1; DESIGN.md D3, D4): the caller's paper account and its SPT configuration.

    GET  /api/v1/paper/accounts                       the caller's account (one per user, D3): paper account + SPT config
    GET  /api/v1/paper/accounts/{account_id}          the same, with the config's recent version history
    PUT  /api/v1/paper/accounts/{account_id}/config   {mode?, extras?, reason?, expected_version?}: change the SPT mode
                                                      (off | tracking | approval | auto) and/or the SPT risk extras;
                                                      versioned (services/spt/policy.py); 422 codes on bad input,
                                                      409 concurrent_change
    GET  /api/v1/paper/accounts/{account_id}/ledger   the paper account's ledger (paper_account_ledger), newest first;
                                                      ?limit= (≤ 200) &before=<at of the last row seen>

account_id is the caller's user_id (D3: one account per user); any other id answers 403 not_your_account. No session
answers 401. The risk profile's limits stay in services/risk_profile (PUT /api/risk/profile); this config cannot loosen
them (risk_pct above the profile's per-trade % is refused: risk_pct_above_profile).
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query, Request

from deps import db, get_current_user
from services import paper_account
from services import risk_controls as rc
from services import risk_profile
from services.spt import policy

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["spt-accounts"])

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


@router.put("/paper/accounts/{account_id}/config")
async def put_config(account_id: str, request: Request) -> Dict[str, Any]:
    user = await get_current_user(request)
    uid = own(user, account_id)
    body = await _body(request)
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail={"code": "invalid_body", "message": "The body must be an object."})
    unknown = set(body) - {"mode", "extras", "reason", "expected_version"}
    if unknown:
        raise HTTPException(status_code=422, detail={"code": "unknown_field",
                                                     "message": f"unknown field(s): {', '.join(sorted(unknown))}"})
    try:
        profile = await risk_profile.read(db, uid)
    except Exception as e:  # noqa: BLE001 — the profile is the authority: an unreadable one refuses the change
        logger.error("spt accounts: the risk profile of %s could not be read (%s)", uid, type(e).__name__)
        raise HTTPException(status_code=503, detail={"code": "profile_unreadable",
                                                     "message": "The risk profile could not be read; nothing changed."})
    await policy.ensure_indexes(db)
    try:
        config = await policy.update(db, uid, actor=rc.session_actor(user), mode=body.get("mode"),
                                     extras=body.get("extras"), reason=body.get("reason"),
                                     expected_version=body.get("expected_version"), profile_limits=profile["limits"])
    except policy.ConfigError as e:
        raise HTTPException(status_code=e.status, detail=e.detail())
    return {"account_id": uid, "config": config}


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
