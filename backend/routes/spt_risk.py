"""SPT allocation and risk (PRD §17.2-§17.3; WF §8-§11, §19): sizing, a dry-run trade check, the account's risk, its
exposures and a stress test, ranked allocation, the caller's proposals, and the approve / reject of a proposal.

    POST /api/v1/risk/calculate-position-size        PURE: the sizing formula and caps on the numbers sent (PRD §8.4);
                                                     writes nothing, reads nothing
    POST /api/v1/risk/validate-trade                 DRY RUN: sizing + allocation + the SPT checks + the universal risk
                                                     service's decide() on {opportunity_id} or {symbol, entry, stop_loss,
                                                     target, quantity?}; nothing recorded, nothing reserved (dry_run: true)
    GET  /api/v1/risk/account/{account_id}           equity, cash, available, deployed, reserved, open risk, the SPT
                                                     planned / stressed risk, daily / weekly loss used, drawdown and the
                                                     ladder, the kill-switch state, limits and utilisation
    GET  /api/v1/risk/exposures/{account_id}         exposure by sector, instrument and category (bucket)
    GET  /api/v1/risk/stress-test/{account_id}       deterministic scenarios on the open SPT entries (P1)
    GET  /api/v1/allocation/recommendations/{account_id}   QUALIFIED opportunities ranked for this account with the size
                                                     and risk each would get now; writes nothing
    POST /api/v1/allocation/recalculate/{account_id} re-run sizing + allocation on the caller's AWAITING proposals
    GET  /api/v1/proposals?state=&limit=             the caller's proposals, newest first
    GET  /api/v1/proposals/{proposal_id}             one of the caller's proposals (404 otherwise)
    POST /api/v1/opportunities/{opportunity_id}/approve   the caller's AWAITING proposal: re-validated and re-risked,
                                                     then the paper order is created (409 with the reasons otherwise)
    POST /api/v1/opportunities/{opportunity_id}/reject    {reason} (required): USER_REJECTED

account_id must be the caller's user_id (403 not_your_account); no session → 401. `detail` is always {code, message,
...}. The risk engine has the final word: an approval never overrides a hard limit (WF §10.4).
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query, Request

from deps import db, get_current_user
from services import desk_trading as desk
from services.spt import allocation, constants as C, pipeline, proposals, risk, sizing

from .spt_accounts import own

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["spt-risk"])

SIZE_FIELDS = ("equity_rs", "risk_pct", "entry", "stop", "cost_per_share", "adv_rs", "min_adv_rs",
               "max_adv_participation_pct", "max_position_pct", "available_rs", "reserve_rs", "profile_per_trade_pct",
               "stressed_gap_pct", "lot_size")


def _uid(user: Dict[str, Any]) -> str:
    return str(user.get("user_id") or "")


async def _body(request: Request) -> Any:
    try:
        return json.loads(await request.body() or b"{}")
    except ValueError:
        raise HTTPException(status_code=422, detail={"code": "invalid_body", "message": "The body must be JSON."})


def _refused(e: pipeline.PipelineError) -> HTTPException:
    return HTTPException(status_code=e.status, detail=e.detail())


@router.post("/risk/calculate-position-size")
async def calculate_position_size(request: Request) -> Dict[str, Any]:
    await get_current_user(request)
    body = await _body(request)
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail={"code": "invalid_body", "message": "The body must be an object."})
    unknown = set(body) - set(SIZE_FIELDS)
    if unknown:
        raise HTTPException(status_code=422, detail={"code": "unknown_field",
                                                     "message": f"unknown field(s): {', '.join(sorted(unknown))}",
                                                     "fields": list(SIZE_FIELDS)})
    for k in ("equity_rs", "risk_pct", "entry", "stop"):
        if sizing._f(body.get(k)) is None:
            raise HTTPException(status_code=422, detail={"code": "invalid_input", "message": f"{k} must be a number",
                                                         "field": k})
    lot = body.get("lot_size", 1)
    if isinstance(lot, bool) or not isinstance(lot, int) or lot < 1:
        raise HTTPException(status_code=422, detail={"code": "invalid_input", "message": "lot_size must be a whole number ≥ 1",
                                                     "field": "lot_size"})
    args = {k: body[k] for k in SIZE_FIELDS if k in body}
    out = sizing.size(**args, model=desk.COST_MODEL)
    return {**out, "pure": True, "writes": "none",
            "formula": "quantity = floor(equity × risk% / (|entry − stop| + cost per share)), then the caps in order"}


@router.post("/risk/validate-trade")
async def validate_trade(request: Request) -> Dict[str, Any]:
    user = await get_current_user(request)
    body = await _body(request)
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail={"code": "invalid_body", "message": "The body must be an object."})
    try:
        return await pipeline.validate_trade(db, _uid(user), body, desk.utcnow())
    except pipeline.PipelineError as e:
        raise _refused(e)


def _pct(part: Optional[float], whole: Optional[float]) -> Optional[float]:
    return None if part is None or not whole else round(float(part) / float(whole) * 100.0, 4)


async def _spt_risk_totals(uid: str, state: Dict[str, Any]) -> Dict[str, Any]:
    rows = await risk.open_spt_book(db, uid, state)
    gap = float(((state.get("config") or {}).get("extras") or {}).get("stressed_gap_pct") or 0.0)
    s = risk.stress(rows, gap_pct=gap)
    return {"planned_rs": s["totals"]["planned_rs"], "stressed_rs": s["totals"]["stressed_rs"],
            "entries": len(rows), "unpriced": s["unpriced"], "stressed_gap_pct": gap,
            "basis": "the open SPT entries and positions: quantity × (entry − stop) + round-trip costs; stressed adds a "
                     f"{gap:g}% gap through the stop"}


@router.get("/risk/account/{account_id}")
async def risk_account(account_id: str, request: Request) -> Dict[str, Any]:
    user = await get_current_user(request)
    uid = own(user, account_id)
    now = desk.utcnow()
    state = await allocation.account_state(db, uid, now=now)
    ks = await risk.kill_switch_state(db, uid, now=now, state=state)
    limits = (state.get("profile") or {}).get("limits") or {}
    eq = state.get("equity_rs")

    def loss(key: str, pct_key: str) -> Dict[str, Any]:
        pnl, start = state.get(f"{key}_pnl_rs"), state.get(f"{key}_start_equity_rs")
        used = None if pnl is None or not start else round(max(0.0, -float(pnl)) / float(start) * 100.0, 4)
        return {"pnl_rs": pnl, "start_equity_rs": start, "loss_pct": used, "limit_pct": limits.get(pct_key),
                "breached": None if used is None or not limits else used >= float(limits[pct_key]) - 1e-9}

    return {
        "account_id": uid, "as_of": state["as_of"], "error": state.get("error"),
        "equity_rs": eq, "equity_basis": sizing.EQUITY_BASIS, "equity_unknown_reasons": state.get("equity_unknown_reasons"),
        "cash_rs": state.get("cash_rs"), "available_rs": state.get("available_rs"), "blocked_rs": state.get("blocked_rs"),
        "deployed_rs": state.get("deployed_rs"), "reserved_rs": state.get("reserved_rs"),
        "pending_entries": state.get("pending_entries"), "reserve_bucket_rs": state.get("reserve_rs"),
        "open_risk": {"rs": state.get("open_risk_rs"), "basis": state.get("open_risk_basis"),
                      "cap_rs": state.get("open_risk_cap_rs"), "limit_pct": limits.get("max_open_risk_pct"),
                      "used_pct_of_equity": _pct(state.get("open_risk_rs"), eq)},
        "spt_risk": await _spt_risk_totals(uid, state) if not state.get("error") else None,
        "daily_loss": loss("day", "daily_loss_pct"), "weekly_loss": loss("week", "weekly_loss_pct"),
        "drawdown": {"pct": state.get("drawdown_pct"), "peak_rs": state.get("peak_rs"),
                     "profile_halt_pct": limits.get("max_drawdown_pct"), "ladder": state.get("ladder")},
        "kill_switch": ks,
        "limits": {"profile": limits, "limits_version": (state.get("profile") or {}).get("limits_version"),
                   "spt": (state.get("config") or {}).get("extras"),
                   "spt_config_version": (state.get("config") or {}).get("version")},
        "utilisation": {"positions": {"open": state.get("positions_open"), "max": state.get("max_positions")},
                        "new_today": {"count": state.get("new_today"), "max": state.get("max_new_per_day")},
                        "buckets": {k: {"used_rs": (state.get("bucket_used_rs") or {}).get(k),
                                        "cap_rs": (state.get("bucket_cap_rs") or {}).get(k)}
                                    for k in allocation.CATEGORIES},
                        "exposure_rs": state.get("exposure_rs"), "exposure_pct_of_equity": _pct(state.get("exposure_rs"), eq)},
        "mode": (state.get("config") or {}).get("mode"),
    }


@router.get("/risk/exposures/{account_id}")
async def exposures(account_id: str, request: Request) -> Dict[str, Any]:
    user = await get_current_user(request)
    uid = own(user, account_id)
    state = await allocation.account_state(db, uid, now=desk.utcnow())
    if state.get("error"):
        raise HTTPException(status_code=503, detail={"code": "account_unreadable", "message": state["error"]})
    eq = state.get("equity_rs")
    limits = state["profile"]["limits"]
    book = state["book"]
    by_instrument: Dict[str, float] = {}
    for e in book.get("reservations") or []:
        sym = e.get("symbol") or "?"
        by_instrument[sym] = round(by_instrument.get(sym, 0.0) + float(e.get("exposure_rs") or 0.0), 2)
    for p in book.get("positions") or []:
        if not p.get("reserved"):
            sym = p.get("symbol") or "?"
            by_instrument[sym] = round(by_instrument.get(sym, 0.0) + float(p.get("exposure_rs") or 0.0), 2)
    return {
        "account_id": uid, "as_of": state["as_of"], "equity_rs": eq,
        "by_sector": [{"sector": k, "exposure_rs": v, "pct_of_equity": _pct(v, eq), "limit_pct": limits["max_sector_pct"]}
                      for k, v in sorted(state["sector_rs"].items(), key=lambda kv: -kv[1])],
        "unclassified_exposure_rs": state.get("unclassified_exposure_rs"),
        "by_instrument": [{"symbol": k, "exposure_rs": v, "pct_of_equity": _pct(v, eq),
                           "limit_pct": limits["max_position_pct"]}
                          for k, v in sorted(by_instrument.items(), key=lambda kv: -kv[1])],
        "by_category": [{"category": k, "used_rs": state["bucket_used_rs"].get(k), "cap_rs": state["bucket_cap_rs"].get(k),
                         "bucket_pct": state["config"]["extras"]["allocation_buckets_pct"][k]} for k in allocation.CATEGORIES],
        "total_exposure_rs": state.get("exposure_rs"),
        "basis": "exposure = quantity × entry price of every reserved position or pending entry, plus positions opened "
                 "before reservations existed at their stored levels (services/risk_book.py); sector from the NSE "
                 "industry classification",
    }


@router.get("/risk/stress-test/{account_id}")
async def stress_test(account_id: str, request: Request) -> Dict[str, Any]:
    user = await get_current_user(request)
    uid = own(user, account_id)
    state = await allocation.account_state(db, uid, now=desk.utcnow())
    if state.get("error"):
        raise HTTPException(status_code=503, detail={"code": "account_unreadable", "message": state["error"]})
    rows = await risk.open_spt_book(db, uid, state)
    gap = float(state["config"]["extras"]["stressed_gap_pct"])
    out = risk.stress(rows, gap_pct=gap)
    return {"account_id": uid, "as_of": state["as_of"], "equity_rs": state.get("equity_rs"), **out}


@router.get("/allocation/recommendations/{account_id}")
async def recommendations(account_id: str, request: Request) -> Dict[str, Any]:
    user = await get_current_user(request)
    uid = own(user, account_id)
    return await pipeline.recommendations(db, uid, desk.utcnow())


@router.post("/allocation/recalculate/{account_id}")
async def recalculate(account_id: str, request: Request) -> Dict[str, Any]:
    user = await get_current_user(request)
    uid = own(user, account_id)
    return await pipeline.recalculate(db, uid, desk.utcnow())


@router.get("/proposals")
async def list_proposals(request: Request, state: Optional[str] = Query(None, max_length=40),
                         limit: int = Query(50, ge=1, le=200)) -> Dict[str, Any]:
    user = await get_current_user(request)
    if state is not None and state not in C.PROP_STATES:
        raise HTTPException(status_code=422, detail={"code": "invalid_state", "message": f"state must be one of "
                                                                                         f"{', '.join(C.PROP_STATES)}"})
    rows = await proposals.list_for_user(db, _uid(user), states=[state] if state else None, limit=limit)
    return {"items": [proposals.public(r) for r in rows], "count": len(rows)}


@router.get("/proposals/{proposal_id}")
async def get_proposal(proposal_id: str, request: Request) -> Dict[str, Any]:
    user = await get_current_user(request)
    doc = await proposals.get(db, proposal_id, user_id=_uid(user))
    if doc is None:
        raise HTTPException(status_code=404, detail={"code": "proposal_not_found", "message": "No such proposal."})
    return proposals.public(doc)


@router.post("/opportunities/{opportunity_id}/approve")
async def approve(opportunity_id: str, request: Request) -> Dict[str, Any]:
    user = await get_current_user(request)
    try:
        out = await pipeline.approve(db, user_id=_uid(user), opportunity_id=opportunity_id, now=desk.utcnow())
    except pipeline.PipelineError as e:
        raise _refused(e)
    return {"proposal": proposals.public(out["proposal"]), "idempotent": out["idempotent"]}


@router.post("/opportunities/{opportunity_id}/reject")
async def reject(opportunity_id: str, request: Request) -> Dict[str, Any]:
    user = await get_current_user(request)
    body = await _body(request)
    reason = body.get("reason") if isinstance(body, dict) else None
    try:
        out = await pipeline.reject(db, user_id=_uid(user), opportunity_id=opportunity_id, reason=reason,
                                    now=desk.utcnow())
    except pipeline.PipelineError as e:
        raise _refused(e)
    return {"proposal": proposals.public(out["proposal"]), "idempotent": out["idempotent"]}
