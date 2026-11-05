"""Paper Trading v2 (docs/scanner_paper_trading/UI_DESIGN_V2.md §4, §7): the backend of the owner's six-view Paper
Trading area. Every route reads only, except the two policy PUTs.

    GET  /api/v1/paper/overview                       Overview: status strip, KPIs, today's pipeline, risk warnings,
                                                      the headline's figures (services/spt/overview.py)
    GET  /api/v1/paper/accounts/{account_id}/policy   the combined policy over the risk profile and the SPT config, one
                                                      version (services/spt/policy_view.py)
    PUT  /api/v1/paper/accounts/{account_id}/policy   {expected_version, values: {key: number | null}, reason?}: the
                                                      holder tightens; loosening → 403 admin_required {loosened}; 409
                                                      version_conflict; 422 {code, field, message}; both stores or neither
    GET  /api/v1/risk/correlation/{account_id}        ?with=SYMBOL&days=60: daily-return correlation of the open paper
                                                      positions (services/spt/correlation.py)
    GET  /api/v1/analytics/account/{account_id}       ?days=90: closed SPT trades' figures, ratios, by setup / regime,
                                                      certification (services/spt/account_analytics.py)
    GET  /api/v1/paper/fno-structures                 the desk's open paper F&O structures with payoff, Greeks,
                                                      scenarios and margin (services/spt/fno_structures.py)
    GET  /api/admin/spt/{user_id}/policy              admin: any user's combined policy
    PUT  /api/admin/spt/{user_id}/policy              admin: {expected_version, values, reason (required)}; any direction
                                                      within the ranges

account_id must be the caller's user_id (403 not_your_account, routes/spt_accounts.own); no session → 401; the admin
routes answer 403 to a non-admin (deps.require_role("admin")). The named stress scenarios are on the existing
GET /api/v1/risk/stress-test/{account_id} (routes/spt_risk.py, services/spt/stress_named.py).
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from deps import db, get_current_user, require_role
from services import desk_trading as desk
from services import risk_controls as rc
from services.spt import account_analytics, allocation, correlation, fno_structures, overview, policy_view

from .spt_accounts import is_admin_session, own

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["paper-v2"])
_require_admin = require_role("admin")
admin_router = APIRouter(prefix="/api/admin/spt", tags=["paper-v2-admin"], dependencies=[Depends(_require_admin)])

POLICY_BODY = {"expected_version", "values", "reason"}


def _uid(user: Dict[str, Any]) -> str:
    return str(user.get("user_id") or "")


async def _body(request: Request) -> Dict[str, Any]:
    try:
        body = json.loads(await request.body() or b"{}")
    except ValueError:
        raise HTTPException(status_code=422, detail={"code": "invalid_body", "field": None, "message": "The body must be JSON."})
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail={"code": "invalid_body", "field": None, "message": "The body must be an object."})
    unknown = set(body) - POLICY_BODY
    if unknown:
        raise HTTPException(status_code=422, detail={"code": "unknown_field", "field": sorted(unknown)[0],
                                                     "message": f"unknown field(s): {', '.join(sorted(unknown))}; send "
                                                                "{expected_version, values, reason?}"})
    return body


def _err(e: policy_view.PolicyError) -> HTTPException:
    return HTTPException(status_code=e.status, detail=e.detail())


# ── overview ─────────────────────────────────────────────────────────────────
@router.get("/paper/overview")
async def paper_overview(request: Request) -> Dict[str, Any]:
    user = await get_current_user(request)
    return await overview.read(db, _uid(user), now=desk.utcnow())


# ── the combined policy ──────────────────────────────────────────────────────
@router.get("/paper/accounts/{account_id}/policy")
async def get_policy(account_id: str, request: Request) -> Dict[str, Any]:
    user = await get_current_user(request)
    uid = own(user, account_id)
    try:
        return await policy_view.read(db, uid, now=desk.utcnow())
    except policy_view.PolicyError as e:
        raise _err(e)


@router.put("/paper/accounts/{account_id}/policy")
async def put_policy(account_id: str, request: Request) -> Dict[str, Any]:
    """The holder tightens any field; a loosening needs an admin (an admin signed in on their own account may)."""
    user = await get_current_user(request)
    uid = own(user, account_id)
    body = await _body(request)
    try:
        return await policy_view.write(db, uid, values=body.get("values"), expected_version=body.get("expected_version"),
                                       reason=body.get("reason"), actor=rc.session_actor(user),
                                       actor_is_admin=await is_admin_session(user), require_reason=False,
                                       now=desk.utcnow())
    except policy_view.PolicyError as e:
        raise _err(e)


@admin_router.get("/{user_id}/policy")
async def admin_get_policy(user_id: str, request: Request) -> Dict[str, Any]:
    try:
        return await policy_view.read(db, user_id, now=desk.utcnow())
    except policy_view.PolicyError as e:
        raise _err(e)


@admin_router.put("/{user_id}/policy")
async def admin_put_policy(user_id: str, request: Request) -> Dict[str, Any]:
    """An admin sets any user's policy in any direction within the ranges; a reason is required."""
    admin = await get_current_user(request)
    body = await _body(request)
    try:
        return await policy_view.write(db, user_id, values=body.get("values"), expected_version=body.get("expected_version"),
                                       reason=body.get("reason"), actor=rc.session_actor(admin), actor_is_admin=True,
                                       require_reason=True, now=desk.utcnow())
    except policy_view.PolicyError as e:
        raise _err(e)


# ── correlation, analytics, F&O ──────────────────────────────────────────────
@router.get("/risk/correlation/{account_id}")
async def risk_correlation(account_id: str, request: Request,
                           with_symbol: Optional[str] = Query(None, alias="with", max_length=30),
                           days: int = Query(correlation.DEFAULT_DAYS, ge=correlation.MIN_DAYS, le=correlation.MAX_DAYS)
                           ) -> Dict[str, Any]:
    user = await get_current_user(request)
    uid = own(user, account_id)
    try:
        sym = correlation.clean_symbol(with_symbol)
    except ValueError as e:
        raise HTTPException(status_code=422, detail={"code": "invalid_symbol", "field": "with", "message": str(e)})
    return {"account_id": uid, **await correlation.read(db, uid, now=desk.utcnow(), days=days, with_symbol=sym)}


@router.get("/analytics/account/{account_id}")
async def account_analytics_route(account_id: str, request: Request,
                                  days: int = Query(account_analytics.DEFAULT_DAYS, ge=1, le=account_analytics.MAX_DAYS)
                                  ) -> Dict[str, Any]:
    user = await get_current_user(request)
    uid = own(user, account_id)
    return await account_analytics.read(db, uid, days=days, now=desk.utcnow())


@router.get("/paper/fno-structures")
async def paper_fno_structures(request: Request) -> Dict[str, Any]:
    user = await get_current_user(request)
    uid = _uid(user)
    now = desk.utcnow()
    state = await allocation.account_state(db, uid, now=now)
    extras = (state.get("config") or {}).get("extras") or {}
    limits = {"fno_max_loss_pct": extras.get("fno_max_loss_pct"), "margin_util_pct": extras.get("margin_util_pct")}
    out = await fno_structures.read(request, db, uid, now=now, equity=state.get("equity_rs"), limits=limits)
    if state.get("error"):
        out["notes"] = [f"The paper account could not be read: {state['error']}"] + list(out.get("notes") or [])
    return {"account_id": uid, **out}
