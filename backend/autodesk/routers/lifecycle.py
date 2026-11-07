"""Read APIs of Phase 3A (PHASE3_DESIGN §11) and its writes: controls, cancel pending entries, amend, close a desk position.
Signed in; tenant-scoped (another tenant's id answers 404 or an empty list). Money as strings. Simulated rows are listed only
with their simulation_id, as in Phase 2."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from .. import contracts as C
from .. import store
from ..lifecycle import controls, limits, recon
from ..market.view import IST
from .api import _state, current_user, out, tenant_of
from .execution import _list

router = APIRouter(prefix="/api/v1")


@router.get("/positions/{position_id}/lifecycle")
async def position_lifecycle(position_id: str, request: Request, user: dict = Depends(current_user)):
    t = tenant_of(user)
    async with _state(request).pool.acquire() as c:
        p = await c.fetchrow("SELECT * FROM autodesk.trade_positions WHERE position_id=$1 AND tenant_id=$2", position_id, t)
        if p is None:
            raise store.NotFound(position_id)
        xs = await c.fetchrow("SELECT * FROM autodesk.trade_exit_state WHERE trade_id=$1", p["trade_id"])
        events = [dict(r) for r in await c.fetch("SELECT * FROM autodesk.trade_lifecycle_events WHERE trade_id=$1 ORDER BY seq",
                                                 p["trade_id"])]
        closing = [dict(r) for r in await c.fetch("SELECT * FROM autodesk.trade_orders WHERE trade_id=$1 AND purpose=$2 "
                                                  "ORDER BY created_at, leg_id", p["trade_id"], C.OrderPurpose.CLOSE.value)]
        records = [dict(r) for r in await c.fetch("SELECT * FROM autodesk.trade_exit_records WHERE trade_id=$1 ORDER BY created_at",
                                                  p["trade_id"])]
    exit_state = None
    if xs is not None:
        st = xs["state"] or {}
        exit_state = {"trigger_key": xs["trigger_key"], "trigger_basis": xs["trigger_basis"], "side": xs["side"],
                      "level_ratio": xs["level_ratio"], "level_in_force": st.get("stop"), "level_version": st.get("stop_version"),
                      "level_history": st.get("stop_history"), "sessions_held": st.get("sessions_held"),
                      "objectives": xs["objectives"], "next_objective": xs["next_objective"], "pending": xs["pending"],
                      "first_step_session": xs["first_step_session"], "last_session": xs["last_session"],
                      "pre_expiry_session": xs["pre_expiry_session"], "rules": xs["rules"], "notes": xs["notes"]}
    return out({"position_id": position_id, "trade_id": p["trade_id"], "status": p["status"], "lifecycle_state": p["lifecycle_state"],
                "flags": p["flags"], "close_reason": p["close_reason"], "closed_at": p["closed_at"], "settled_at": p["settled_at"],
                "history": events, "exit_state": exit_state, "closing_orders": closing, "exit_records": records})


@router.get("/trades/closed")
async def closed_trades(request: Request, account_id: Optional[str] = None, simulation_id: Optional[str] = None,
                        limit: int = Query(200, ge=1, le=1000), user: dict = Depends(current_user)):
    t = tenant_of(user)
    async with _state(request).pool.acquire() as c:
        rows = await _list(c, "trade_positions", t, simulation_id=simulation_id, order="closed_at DESC NULLS LAST", limit=limit,
                           filters={"account_id": account_id, "status": "CLOSED"})
        outl = []
        for p in rows:
            legs = [dict(x) for x in await c.fetch(
                """SELECT leg_id, kind, underlying, expiry, strike, side, opened_qty, closed_qty, avg_price, charges_rs,
                          close_value_rs, closing_charges_rs, realized_gross_rs FROM autodesk.trade_position_legs
                   WHERE position_id=$1 ORDER BY leg_id""", p["position_id"])]
            for lg in legs:
                lg["closing_avg_price"] = (lg["close_value_rs"] / lg["closed_qty"]).quantize(Decimal("0.0001")) if lg["closed_qty"] else None
                lg["opening_avg_price"] = lg.pop("avg_price")
            opening_charges = sum((lg["charges_rs"] for lg in legs), Decimal("0"))
            held = await c.fetchval("SELECT (state->>'sessions_held')::int FROM autodesk.trade_exit_state WHERE trade_id=$1",
                                    p["trade_id"])
            outl.append({"trade_id": p["trade_id"], "position_id": p["position_id"], "account_id": p["account_id"],
                         "simulation_id": p["simulation_id"], "instrument": p["instrument"], "strategy_type": p["strategy_type"],
                         "opened_at": p["opened_at"], "closed_at": p["closed_at"], "sessions_held": held,
                         "close_reason": p["close_reason"], "legs": legs, "gross_realized_rs": p["realized_gross_rs"],
                         "opening_charges_rs": opening_charges, "closing_charges_rs": p["closing_charges_rs"],
                         "net_realized_rs": p["realized_gross_rs"] - opening_charges - p["closing_charges_rs"],
                         "lifecycle_state": p["lifecycle_state"], "reconciled": p["lifecycle_state"] == C.LifecycleState.SETTLED.value,
                         "fill_kind": "SIMULATED", "broker_confirmed": False})
    return out(outl)


@router.get("/execution/exit-records")
async def exit_records(request: Request, account_id: Optional[str] = None, simulation_id: Optional[str] = None,
                       trade_id: Optional[str] = None, limit: int = Query(500, ge=1, le=2000), user: dict = Depends(current_user)):
    async with _state(request).pool.acquire() as c:
        return out(await _list(c, "trade_exit_records", tenant_of(user), simulation_id=simulation_id, order="created_at DESC",
                               limit=limit, filters={"account_id": account_id, "trade_id": trade_id}))


@router.get("/lifecycle/events")
async def lifecycle_events(request: Request, trade_id: Optional[str] = None, account_id: Optional[str] = None,
                           simulation_id: Optional[str] = None, after_seq: Optional[int] = Query(None, ge=0),
                           limit: int = Query(500, ge=1, le=5000), user: dict = Depends(current_user)):
    t = tenant_of(user)
    q, args = ["SELECT * FROM autodesk.trade_lifecycle_events WHERE tenant_id=$1 AND seq>$2"], [t, after_seq or 0]
    if trade_id:
        args.append(trade_id); q.append(f"AND trade_id=${len(args)}")
    elif simulation_id:
        args.append(simulation_id); q.append(f"AND simulation_id=${len(args)}")
    else:
        q.append("AND simulation_id IS NULL")
    if account_id:
        args.append(account_id); q.append(f"AND account_id=${len(args)}")
    args.append(limit)
    q.append(f"ORDER BY seq {'' if after_seq is not None else 'DESC '}LIMIT ${len(args)}")
    async with _state(request).pool.acquire() as c:
        rows = [dict(r) for r in await c.fetch(" ".join(q), *args)]
    return out(rows if after_seq is not None else rows[::-1])


@router.get("/accounts/{account_id}/limits")
async def account_limits(account_id: str, request: Request, user: dict = Depends(current_user)):
    t = tenant_of(user)
    async with _state(request).pool.acquire() as c:
        acc = await store.get_account(c, t, account_id)
        session = None
        if acc["simulation_id"]:
            session = await c.fetchval("SELECT clock_session FROM autodesk.simulations WHERE simulation_id=$1", acc["simulation_id"])
        session = session or datetime.now(timezone.utc).astimezone(IST).date()
        return out(await limits.current(c, tenant_id=t, account_id=account_id, session=session))


@router.get("/accounts/{account_id}/reconciliation")
async def account_reconciliation(account_id: str, request: Request, user: dict = Depends(current_user)):
    t = tenant_of(user)
    async with _state(request).pool.acquire() as c:
        await store.get_account(c, t, account_id)
        last = await c.fetchrow("SELECT * FROM autodesk.reconciliation_runs WHERE account_id=$1 ORDER BY seq DESC LIMIT 1", account_id)
        now = await recon.account_checks(c, t, account_id)
        runs = await c.fetchrow("SELECT count(*) AS n, count(*) FILTER (WHERE NOT ok) AS failed FROM autodesk.reconciliation_runs "
                                "WHERE account_id=$1", account_id)
    return out({"account_id": account_id, "now": {"ok": all(k["ok"] for k in now), "checks": now},
                "last_run": dict(last) if last else None, "runs": runs["n"], "runs_failed": runs["failed"]})


# ── writes ───────────────────────────────────────────────────────────────────────────────────────────────────────

class ControlIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    active: bool
    reason: str = Field(min_length=1, max_length=300)
    scope: str = Field(default="*", min_length=1, max_length=80)


@router.get("/lifecycle/controls")
async def get_controls(request: Request, user: dict = Depends(current_user)):
    async with _state(request).pool.acquire() as c:
        return out(await controls.list_controls(c, tenant_of(user)))


@router.post("/lifecycle/controls/{control}")
async def set_control(control: C.LifecycleControl, body: ControlIn, request: Request, user: dict = Depends(current_user)):
    """PRD §10.4. None of these cancels a protective closing or removes a level. scope: '*' (desk accounts), an account id, or
    (SUSPEND_STRATEGY) a strategy type."""
    t = tenant_of(user)
    async with _state(request).pool.acquire() as c:
        if control == C.LifecycleControl.SUSPEND_STRATEGY:
            if body.scope not in {s.value for s in C.StrategyType}:
                raise HTTPException(422, "SUSPEND_STRATEGY needs a strategy type as scope")
        elif body.scope != "*":
            await store.get_account(c, t, body.scope)
        elif control == C.LifecycleControl.SUSPEND_ACCOUNT:
            raise HTTPException(422, "SUSPEND_ACCOUNT needs an account id as scope")
        async with c.transaction():
            return out(await controls.set_control(c, tenant_id=t, control=control, scope=body.scope, active=body.active,
                                                  reason=body.reason, actor=f"user:{t}"))


class ReasonIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1, max_length=300)


@router.post("/execution/cancel-pending-entries")
async def cancel_pending_entries(body: ReasonIn, request: Request, user: dict = Depends(current_user)):
    st = _state(request)
    if st.execution is None:
        raise HTTPException(409, "paper execution is not running in this process")
    ids = await controls.cancel_pending_openings(st.execution, tenant_id=tenant_of(user), reason=body.reason)
    return out({"withdrawn": ids, "count": len(ids)})


class AmendIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lots: Optional[int] = Field(default=None, ge=1)
    limit_price: Optional[Decimal] = Field(default=None, gt=0)


@router.post("/execution/orders/{order_id}/amend")
async def amend_order(order_id: str, body: AmendIn, request: Request, user: dict = Depends(current_user)):
    st = _state(request)
    if st.execution is None:
        raise HTTPException(409, "paper execution is not running in this process")
    return out(await st.execution.amend(tenant_id=tenant_of(user), order_id=order_id,
                                        changes={k: v for k, v in body.model_dump().items() if v is not None}))


@router.post("/positions/{position_id}/close")
async def close_position(position_id: str, body: ReasonIn, request: Request, user: dict = Depends(current_user)):
    """A person's request to close a whole desk position; the manager does it at the next fresh quote (PHASE3_DESIGN §7.3)."""
    t = tenant_of(user)
    async with _state(request).pool.acquire() as c:
        p = await c.fetchrow("SELECT * FROM autodesk.trade_positions WHERE position_id=$1 AND tenant_id=$2", position_id, t)
        if p is None:
            raise store.NotFound(position_id)
        if p["simulation_id"] is not None or p["status"] != "OPEN":
            raise store.Conflict("only an open desk position can be closed on request")
        async with c.transaction():
            return out(await controls.request_close(c, pos=dict(p), reason=C.CloseReason.MANUAL, note=body.reason,
                                                    actor=f"user:{t}"))
