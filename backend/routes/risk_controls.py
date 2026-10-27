"""Risk controls: the kill switch and the trading halt (services/risk_controls.py), the live-execution grant
(services/execution_modes.py) and the F&O risk policy (services/risk_gate).

    GET  /api/risk/status          the signed-in user's controls, what they block, who may clear them, the live grant,
                                   the execution modes and whether the F&O risk gate is on for this user
    PUT  /api/risk/kill-switch     set or clear the kill switch; a reason is required; clearing needs an admin
    PUT  /api/risk/halt            set or clear the trading halt; a reason is required; clearing needs an admin
    GET  /api/risk/audit           the append-only record of every control change
    GET  /api/risk/decisions       the append-only record of every risk decision and denial
    GET  /api/risk/policy          the F&O risk policy's version, limits and this user's usage against them
    GET  /api/risk/live-readiness  the twelve live-trading conditions of PRD §21, each pass / fail with its evidence
    GET  /api/risk/profile         the account's risk profile (limits, capital basis, effective date), the definitions,
                                   the live equity basis and budgets (equity, peak, drawdown, day / week P&L, open risk,
                                   sector exposure) and the change log
    PUT  /api/risk/profile         {changes: {limit: value, ...} | profile: name, reason}: tighten any limit; loosening
                                   needs an admin (403 admin_required); every change is recorded (risk_profile_audit)
    GET  /api/risk/freshness?symbol=  the risk service's input freshness: the symbol's last close and sector (with a
                                   symbol) and the market state, each with its as-of date, age in sessions, budget and
                                   ok / stale / unknown, built by the same functions the decision uses; read-only
    GET  /api/risk/decisions/{id}/lineage  the decision's ten-step lineage: what is recorded and what is not
    POST /api/risk/decisions/{id}/replay   re-run the gate on the decision's stored snapshot and compare; writes nothing
                                   (both: the caller's own decision, or any for an admin; otherwise 404)

    PUT  /api/admin/risk/{user_id}/kill-switch         admin only: {enabled: bool, reason: str}
    PUT  /api/admin/risk/{user_id}/halt                admin only: {enabled: bool, reason: str}
    PUT  /api/admin/risk/{user_id}/live-authorization  admin only: {granted: bool, reason: str}
    PUT  /api/admin/risk/{user_id}/profile             admin only: {changes | profile, reason}; may loosen
    GET  /api/admin/risk/jobs/{job}                    admin only: the scheduled job's last run, last success and
                                                       health (ok | partial | failed | running | missed | no_data |
                                                       skipped | never_run | calendar_not_ready | refused);
                                                       services/job_runs. Reads only. Jobs: check_desk_alerts (the
                                                       evening exit check) and positional_engine (the AI scanner).

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
from services import data_freshness as fresh
from services import desk_trading as desk
from services import execution_modes as modes
from services import job_runs
from services import risk_controls as rc
from services import risk_book
from services import risk_gate
from services import risk_profile
from services.risk_gate import policy as risk_policy
from services.risk_gate import estimate as risk_estimate
from services.risk_gate import inputs as risk_inputs
from services.risk_gate import readiness, replay
from services.risk_gate import service as risk_service

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
        "scope": "blocks new positions on the AI-trader ticket, desk paper-trade and journal paths (every entry path "
                 "runs the universal risk service, services/risk_gate/service.py)",
        "not_in_scope": "no order is placed anywhere in this system, and open positions are untouched",
        "policy_version": rc.POLICY_VERSION,
        "can_reset": await _is_admin_session(user),
        "live_authorization": await modes.read_live_authorization(db, uid),
        "modes": list(modes.MODES),
        "live_execution_available": modes.LIVE_EXECUTION_AVAILABLE,
        "gate": {"enabled": await risk_gate.enabled_for(db, user), "policy_version": risk_policy.POLICY_VERSION,
                 "scope": "the flag rolls out ADDITIONAL F&O structure checks only; the core risk checks always run"},
        "risk_policy_version": risk_service.POLICY_VERSION,
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


@router.get("/live-readiness")
async def live_readiness(request: Request) -> Dict[str, Any]:
    """PRD §21: the conditions live F&O orders need, each read from what exists today. None passes in this build."""
    user = await get_current_user(request)
    from services.kite_live_feed.feed import get_feed  # imported here: the feed module is heavy and optional

    return await readiness.live_readiness(db, _uid(user), gate_enabled=lambda: risk_gate.enabled_for(db, user),
                                          feed_status=lambda: get_feed().read_status())


def _freshness_status(rec: Dict[str, Any]) -> str:
    """ok, or why not in the risk service's own terms: stale (dated, too old) or unknown (no value or no date)."""
    if rec.get("ok"):
        return "ok"
    return "stale" if rec.get("age_sessions") is not None else "unknown"


def _judged(rec: Dict[str, Any], **value: Any) -> Dict[str, Any]:
    return {**rec, "status": _freshness_status(rec), **value}


def _now():
    return job_runs.utcnow()


@router.get("/freshness")
async def freshness(request: Request, symbol: str = Query(None, max_length=40)) -> Dict[str, Any]:
    """How fresh the risk service's inputs are right now. The reads are inputs.instrument / sector_of / market_state
    and the judgements are risk_service.last_close_freshness / sector_freshness / market_freshness: the functions
    gather() and decide() use, with the same budgets. So this answer and a decision made at the same moment cannot
    disagree. Without a symbol only the market state is judged. Read-only."""
    await get_current_user(request)
    sym = None
    if symbol is not None and symbol.strip():
        try:
            sym = desk.clean_symbol(symbol)
        except desk.DeskInputError as e:
            raise HTTPException(status_code=422, detail=e.code)
    now = _now()
    market = await risk_inputs.market_state()
    out: Dict[str, Any] = {
        "market_state": _judged(risk_service.market_freshness(market, now), regime=market.get("regime"),
                                vix=market.get("vix"), key=market.get("key")),
    }
    if sym:
        inst = await risk_inputs.instrument(sym, fresh.ist_today(now))
        inst.pop("bars", None)
        sec = await risk_inputs.sector_of(sym)
        out["last_close"] = _judged(risk_service.last_close_freshness(inst, now), value=inst.get("last_close"))
        out["sector"] = _judged(risk_service.sector_freshness(sec), value=sec.get("sector"))
    else:
        skipped = {"status": "not_checked", "ok": None, "reason": "give ?symbol= to check a share's inputs"}
        out["last_close"], out["sector"] = dict(skipped), dict(skipped)
    judged = [rec for rec in out.values() if rec["status"] != "not_checked"]
    return {"symbol": sym, "inputs": out, "all_ok": all(rec["ok"] for rec in judged),
            "reference_session": fresh.reference_session(now).isoformat(), "as_of": now.isoformat(),
            "budgets": {"last_close": risk_service.LAST_CLOSE_BUDGET, "market_state": risk_service.MARKET_STATE_BUDGET,
                        "sector": None},
            "calendar": fresh.CALENDAR_NOTE, "freshness_version": fresh.FRESHNESS_VERSION,
            "risk_policy_version": risk_service.POLICY_VERSION,
            "rule": "a new paper entry is blocked when any of its inputs is not ok (risk service check 'inputs')"}


_DECISION = Path(..., min_length=1, max_length=64)
_NOT_FOUND = {"code": "decision_not_found", "message": "No such decision on this account."}


async def _decision(request: Request, decision_id: str) -> Dict[str, Any]:
    """The decision row if the caller may read it: their own, or any for an admin. Anything else is 404, the same
    answer as an unknown id, so ids on other accounts cannot be probed."""
    user = await get_current_user(request)
    row = await replay.load(db, decision_id, _uid(user), await _is_admin_session(user))
    if not row:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return row


@router.get("/decisions/{decision_id}/lineage")
async def decision_lineage(request: Request, decision_id: str = _DECISION) -> Dict[str, Any]:
    """The ten lineage steps, each recorded / not_recorded / not_reached / not_applicable, from the row and the
    records that carry its id. Read only."""
    return await replay.lineage(db, await _decision(request, decision_id))


@router.post("/decisions/{decision_id}/replay")
async def decision_replay(request: Request, decision_id: str = _DECISION) -> Dict[str, Any]:
    """Re-run the gate's checks on the stored snapshot under the code and policy running now, and compare outcome,
    reasons and checks with the record. POST because it computes on demand; it writes nothing."""
    return replay.replay(await _decision(request, decision_id))


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


@admin_router.get("/jobs/{job}")
async def admin_job_health(job: str = Path(..., min_length=1, max_length=64)) -> Dict[str, Any]:
    """The scheduled job's newest run, newest successful run and health. "missed" means no run was recorded since the
    job's latest scheduled slot plus its grace period (services/job_runs.SCHEDULES), so a weekend is not a miss."""
    if job not in job_runs.SCHEDULES:
        raise HTTPException(status_code=404, detail="unknown_job")
    return await job_runs.read_health(db, job, job_runs.utcnow())


# ── the risk profile (services/risk_profile.py) ──────────────────────────────
def _profile_error(e: risk_profile.ProfileError) -> HTTPException:
    status = {"admin_required": 403, "concurrent_change": 409, "no_change": 409}.get(e.code, 422)
    return HTTPException(status_code=status, detail=e.detail())


def _profile_body(body: Any) -> Dict[str, Any]:
    if not isinstance(body, dict) or set(body) - {"changes", "profile", "reason"}:
        raise HTTPException(status_code=422, detail={"code": "invalid_input",
                                                     "message": "send {changes: {...}} or {profile: name}, and a reason"})
    return body


async def _profile_view(uid: str, user: Dict[str, Any]) -> Dict[str, Any]:
    profile = await risk_profile.read(db, uid)
    try:
        book = await risk_book.read(db, uid, sector_of=risk_inputs.sector_of)
        limits = profile["limits"]
        equity = book["equity"]["equity_rs"]

        def cap(pct: float):
            return None if equity is None else round(equity * pct / 100.0, 2)

        live = {"equity": book["equity"], "peak": book["peak"], "drawdown_pct": book["drawdown_pct"],
                "day": book["day"], "week": book["week"], "open": book["open"],
                "budgets_rs": {"per_trade": cap(limits["per_trade_risk_pct"]), "open_risk": cap(limits["max_open_risk_pct"]),
                               "position": cap(limits["max_position_pct"]), "sector": cap(limits["max_sector_pct"])},
                "error": None}
    except Exception as e:  # noqa: BLE001 — the profile still answers; the live figures say they are unavailable
        logger.warning("risk profile: book unreadable for %s (%s)", uid, type(e).__name__)
        live = {"error": f"the account could not be read ({type(e).__name__})"}
    return {"profile": profile, "live": live, "changes": await risk_profile.audit_rows(db, uid, 20),
            "can_loosen": await _is_admin_session(user), "catalogue": risk_profile.catalogue(),
            "estimate": risk_estimate.segment_note(), "risk_policy_version": risk_service.POLICY_VERSION,
            "fno_additional_checks": {"flag": risk_gate.FLAG, "enabled": await risk_gate.enabled_for(db, user)}}


@router.get("/profile")
async def get_profile(request: Request) -> Dict[str, Any]:
    """The account's risk profile, its definitions, the live equity basis and budgets, and the change log."""
    user = await get_current_user(request)
    return await _profile_view(_uid(user), user)


@router.put("/profile")
async def put_profile(request: Request) -> Dict[str, Any]:
    """{changes: {limit: value}} or {profile: name}, and a reason. Tightening is the user's; loosening needs an admin."""
    user = await get_current_user(request)
    body = _profile_body(await _body(request))
    try:
        await risk_profile.set_limits(db, _uid(user), reason=body.get("reason"), actor=rc.session_actor(user),
                                      actor_is_admin=await _is_admin_session(user), changes=body.get("changes"),
                                      profile=body.get("profile"))
    except risk_profile.ProfileError as e:
        raise _profile_error(e)
    return await _profile_view(_uid(user), user)


@admin_router.put("/{user_id}/profile")
async def admin_profile(request: Request, user_id: str = _TARGET, admin: dict = Depends(_require_admin)) -> Dict[str, Any]:
    """Admin only: change another account's profile, loosening included; recorded with the admin as the actor."""
    if not await _is_admin_session(admin):
        raise HTTPException(status_code=403, detail=_ADMIN_REQUIRED)
    body = _profile_body(await _body(request))
    if not await db.users.find_one({"user_id": user_id}, {"_id": 0, "user_id": 1}):
        raise HTTPException(status_code=404, detail="user_not_found")
    try:
        profile = await risk_profile.set_limits(db, user_id, reason=body.get("reason"), actor=rc.session_actor(admin),
                                                actor_is_admin=True, changes=body.get("changes"),
                                                profile=body.get("profile"))
    except risk_profile.ProfileError as e:
        raise _profile_error(e)
    return {"profile": profile, "changes": await risk_profile.audit_rows(db, user_id, 20)}
