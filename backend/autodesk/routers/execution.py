"""Read APIs of Phase 2 (PHASE2_DESIGN §9) and the one write: withdraw a working paper order. Signed in; tenant-scoped (another
tenant's id answers 404 or an empty list). Money is returned as strings. Every fill says it is simulated."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from .. import store
from ..execution import journal, reports
from .api import _state, current_user, out, tenant_of

router = APIRouter(prefix="/api/v1")

FILL_LABELS = {"fill_kind": "SIMULATED", "broker_confirmed": False}


async def _list(c, table: str, tenant_id: str, *, simulation_id: Optional[str], filters: dict[str, Optional[str]],
                order: str, limit: int) -> list[dict]:
    q, args = [f"SELECT * FROM autodesk.{table} WHERE tenant_id=$1"], [tenant_id]
    if simulation_id:
        args.append(simulation_id); q.append(f"AND simulation_id=${len(args)}")
    else:
        q.append("AND simulation_id IS NULL")
    for col, v in filters.items():
        if v is not None:
            args.append(v); q.append(f"AND {col}=${len(args)}")
    args.append(limit)
    q.append(f"ORDER BY {order} LIMIT ${len(args)}")
    return [dict(r) for r in await c.fetch(" ".join(q), *args)]


@router.get("/accounts/{account_id}/capital")
async def account_capital(account_id: str, request: Request, user: dict = Depends(current_user)):
    t = tenant_of(user)
    async with _state(request).pool.acquire() as c:
        await store.get_account(c, t, account_id)
        return out(await reports.capital_view(c, t, account_id))


@router.get("/accounts/{account_id}/capital/ledger")
async def account_ledger(account_id: str, request: Request, after_seq: Optional[int] = Query(None, ge=0),
                         limit: int = Query(200, ge=1, le=2000), user: dict = Depends(current_user)):
    t = tenant_of(user)
    async with _state(request).pool.acquire() as c:
        await store.get_account(c, t, account_id)
        rows = [dict(r) for r in await c.fetch(
            "SELECT * FROM autodesk.capital_ledger_entries WHERE tenant_id=$1 AND account_id=$2 AND seq>$3 "
            f"ORDER BY seq {'' if after_seq is not None else 'DESC '}LIMIT $4", t, account_id, after_seq or 0, limit)]
    return out(rows if after_seq is not None else rows[::-1])


@router.get("/accounts/{account_id}/reservations")
async def account_reservations(account_id: str, request: Request, status: Optional[str] = None,
                               limit: int = Query(200, ge=1, le=1000), user: dict = Depends(current_user)):
    t = tenant_of(user)
    async with _state(request).pool.acquire() as c:
        await store.get_account(c, t, account_id)
        rows = await c.fetch("SELECT * FROM autodesk.capital_reservations WHERE tenant_id=$1 AND account_id=$2 "
                             "AND ($3::text IS NULL OR status=$3) ORDER BY created_at DESC LIMIT $4", t, account_id, status, limit)
    return out([dict(r) for r in rows])


@router.get("/accounts/{account_id}/pnl")
async def account_pnl(account_id: str, request: Request, user: dict = Depends(current_user)):
    t = tenant_of(user)
    async with _state(request).pool.acquire() as c:
        await store.get_account(c, t, account_id)
        return out(await reports.pnl(c, t, account_id))


@router.get("/execution/intents")
async def list_intents(request: Request, account_id: Optional[str] = None, simulation_id: Optional[str] = None,
                       trade_id: Optional[str] = None, status: Optional[str] = None, limit: int = Query(200, ge=1, le=1000),
                       user: dict = Depends(current_user)):
    async with _state(request).pool.acquire() as c:
        return out(await _list(c, "execution_intents", tenant_of(user), simulation_id=simulation_id, order="created_at DESC", limit=limit,
                               filters={"account_id": account_id, "trade_id": trade_id, "status": status}))


@router.get("/execution/intents/{intent_id}")
async def get_intent(intent_id: str, request: Request, user: dict = Depends(current_user)):
    async with _state(request).pool.acquire() as c:
        r = await c.fetchrow("SELECT * FROM autodesk.execution_intents WHERE intent_id=$1 AND tenant_id=$2", intent_id, tenant_of(user))
    if r is None:
        raise store.NotFound(intent_id)
    return out(dict(r))


@router.get("/execution/orders")
async def list_orders(request: Request, account_id: Optional[str] = None, simulation_id: Optional[str] = None,
                      trade_id: Optional[str] = None, state: Optional[str] = None, limit: int = Query(200, ge=1, le=1000),
                      user: dict = Depends(current_user)):
    async with _state(request).pool.acquire() as c:
        return out(await _list(c, "trade_orders", tenant_of(user), simulation_id=simulation_id, order="created_at DESC", limit=limit,
                               filters={"account_id": account_id, "trade_id": trade_id, "state": state}))


@router.get("/execution/orders/{order_id}")
async def get_order(order_id: str, request: Request, user: dict = Depends(current_user)):
    t = tenant_of(user)
    async with _state(request).pool.acquire() as c:
        r = await c.fetchrow("SELECT * FROM autodesk.trade_orders WHERE order_id=$1 AND tenant_id=$2", order_id, t)
        if r is None:
            raise store.NotFound(order_id)
        hist = [dict(x) for x in await c.fetch("SELECT * FROM autodesk.trade_order_events WHERE order_id=$1 ORDER BY seq", order_id)]
        fills = [dict(x) | FILL_LABELS for x in await c.fetch("SELECT * FROM autodesk.trade_fills WHERE order_id=$1 ORDER BY fill_time", order_id)]
    return out({**dict(r), "history": hist, "fills": fills})


@router.post("/execution/orders/{order_id}/cancel")
async def cancel_order(order_id: str, request: Request, user: dict = Depends(current_user)):
    t = tenant_of(user)
    st = _state(request)
    if st.execution is None:
        raise HTTPException(409, "paper execution is not running in this process")
    await st.execution.withdraw(tenant_id=t, order_id=order_id)
    async with st.pool.acquire() as c:
        return out(dict(await c.fetchrow("SELECT * FROM autodesk.trade_orders WHERE order_id=$1 AND tenant_id=$2", order_id, t)))


@router.get("/execution/fills")
async def list_fills(request: Request, account_id: Optional[str] = None, simulation_id: Optional[str] = None,
                     trade_id: Optional[str] = None, order_id: Optional[str] = None, limit: int = Query(200, ge=1, le=1000),
                     user: dict = Depends(current_user)):
    async with _state(request).pool.acquire() as c:
        rows = await _list(c, "trade_fills", tenant_of(user), simulation_id=simulation_id, order="fill_time DESC", limit=limit,
                           filters={"account_id": account_id, "trade_id": trade_id, "order_id": order_id})
    return out([r | FILL_LABELS for r in rows])


async def _positions(c, t: str, where: dict, simulation_id: Optional[str], status: Optional[str], limit: int) -> list[dict]:
    rows = await _list(c, "trade_positions", t, simulation_id=simulation_id, order="opened_at DESC", limit=limit,
                       filters={"account_id": where.get("account_id"), "status": status, "position_id": where.get("position_id")})
    for p in rows:
        legs = [dict(x) for x in await c.fetch("SELECT * FROM autodesk.trade_position_legs WHERE position_id=$1 ORDER BY leg_id", p["position_id"])]
        for lg in legs:
            lg.update(reports.mark_age(lg, live=p["simulation_id"] is None))
        p["legs"] = legs
        p["unrealized_rs"] = sum((lg["unrealized_rs"] for lg in legs), 0)
        p["charges_rs"] = sum((lg["charges_rs"] for lg in legs), 0)
    return rows


@router.get("/positions")
async def list_positions(request: Request, account_id: Optional[str] = None, simulation_id: Optional[str] = None,
                         status: Optional[str] = None, limit: int = Query(200, ge=1, le=1000), user: dict = Depends(current_user)):
    async with _state(request).pool.acquire() as c:
        return out(await _positions(c, tenant_of(user), {"account_id": account_id}, simulation_id, status, limit))


@router.get("/positions/{position_id}")
async def get_position(position_id: str, request: Request, user: dict = Depends(current_user)):
    t = tenant_of(user)
    async with _state(request).pool.acquire() as c:
        r = await c.fetchrow("SELECT simulation_id FROM autodesk.trade_positions WHERE position_id=$1 AND tenant_id=$2", position_id, t)
        if r is None:
            raise store.NotFound(position_id)
        rows = await _positions(c, t, {"position_id": position_id}, r["simulation_id"], None, 1)
    return out(rows[0])


@router.get("/journal")
async def get_journal(request: Request, trade_id: Optional[str] = None, account_id: Optional[str] = None,
                      simulation_id: Optional[str] = None, after_seq: Optional[int] = Query(None, ge=0),
                      limit: int = Query(500, ge=1, le=5000), user: dict = Depends(current_user)):
    async with _state(request).pool.acquire() as c:
        return out(await journal.list_entries(c, tenant_of(user), trade_id=trade_id, account_id=account_id,
                                              simulation_id=simulation_id, after_seq=after_seq, limit=limit))
