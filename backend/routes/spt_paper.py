"""SPT paper trading API (PRD §17.4; DESIGN.md D8; slice C). Every route is scoped to the signed-in user
(deps.get_current_user; 401 without a session) and reads or writes ONLY that user's orders and positions: another
user's id answers 404, exactly as a missing one. Errors carry a stable `detail.code`.

    POST /api/v1/paper/orders                       {purpose: "EXIT", position_id, quantity?, order_type?, limit_price?}
                                                    an exit of the caller's own open position (reason manual); or
                                                    {purpose: "ENTRY", proposal_id}: only for the caller's proposal in
                                                    READY_FOR_ORDER, handed to slice B's pipeline (which owns the risk
                                                    decision and the reservation); anything else 422
                                                    entry_requires_approved_proposal. The risk check is never bypassed.
    GET  /api/v1/paper/orders                       ?state=&purpose=&limit=
    GET  /api/v1/paper/orders/{order_id}            with its fills
    POST /api/v1/paper/orders/{order_id}/cancel     409 order_not_live when it is not live
    GET  /api/v1/paper/positions                    ?status=open|closed|all (default open)
    GET  /api/v1/paper/positions/{position_id}      with fills, modifications and events
    POST /api/v1/paper/positions/{position_id}/modify  {change: {...}, reason, expect_version?}  (services/spt/paper/modify.py)
    POST /api/v1/paper/positions/{position_id}/exit    {quantity?, order_type?, limit_price?}: an exit order, reason manual;
                                                    a second request while one is live returns the live one
    GET  /api/v1/paper/trades                       closed positions: net P&L, R, MFE/MAE, exit reason, the signal /
                                                    opportunity / proposal ids
    GET  /api/v1/paper/trades/{trade_id}            one closed position with its outcome record (trade_id = position id)
    GET  /api/v1/paper/reconcile                    the caller's reconciliation report (read-only)
    GET  /api/v1/paper/stream                       server-sent events: the caller's new SPT events as they are written
                                                    (event-driven; no snapshot per tick), `: heartbeat` between

Exits and risk-reducing changes stay available while new entries are blocked (PRD §18 rules 12–14). Nothing here talks
to a broker.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from deps import db, get_current_user
from services.spt import constants as C
from services.spt.paper import modify as modify_mod
from services.spt.paper import monitor, orders, positions, reconcile, store

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["spt-paper"])

MAX_LIST = 500
STREAM_MAX_SECONDS = 30 * 60
STREAM_POLL_SECONDS = 2.0
HEARTBEAT_SECONDS = 15.0
_quotes = monitor.default_quotes                     # the market reference of a modification (tests replace it)
_EXIT_422 = ("exit_reason_invalid", "order_type_invalid", "limit_price_required", "quantity_invalid")


def _err(status: int, code: str, message: str, **extra: Any) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message, **extra})


async def _uid(request: Request) -> str:
    user = await get_current_user(request)
    return str(user["user_id"])


async def _own_position(uid: str, position_id: str) -> Dict[str, Any]:
    pos = await store.get_position(db, position_id)
    if pos is None or pos.get("user_id") != uid:
        raise _err(404, "position_not_found", "No such paper position for this account.")
    return pos


async def _own_order(uid: str, order_id: str) -> Dict[str, Any]:
    o = await store.get_order(db, order_id)
    if o is None or o.get("user_id") != uid:
        raise _err(404, "order_not_found", "No such paper order for this account.")
    return o


def _exit_refused(e: orders.ExitRefused) -> HTTPException:
    return _err(422 if e.code in _EXIT_422 else 409, e.code, "The exit order was not created.")


class OrderIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    purpose: str = Field(..., max_length=10)
    position_id: Optional[str] = Field(None, max_length=80)
    proposal_id: Optional[str] = Field(None, max_length=80)
    quantity: Optional[int] = Field(None, ge=1, le=10_000_000)
    order_type: str = Field("MARKET", max_length=10)
    limit_price: Optional[float] = Field(None, gt=0)


class ExitIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    quantity: Optional[int] = Field(None, ge=1, le=10_000_000)
    order_type: str = Field("MARKET", max_length=10)
    limit_price: Optional[float] = Field(None, gt=0)


class ModifyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    change: Dict[str, Any]
    reason: Optional[str] = Field(None, max_length=500)
    expect_version: Optional[int] = Field(None, ge=0)


@router.post("/paper/orders")
async def create_order(request: Request, body: OrderIn):
    uid = await _uid(request)
    purpose = body.purpose.strip().upper()
    if purpose == "EXIT":
        if not body.position_id:
            raise _err(422, "position_id_required", "An exit order names the position it closes.")
        await _own_position(uid, body.position_id)
        try:
            o = await orders.create_exit_order(db, position_id=body.position_id, reason="manual", quantity=body.quantity,
                                               order_type=body.order_type, limit_price=body.limit_price, actor_id=uid,
                                               trigger={"requested_by": uid, "via": "POST /paper/orders"})
        except orders.ExitRefused as e:
            raise _exit_refused(e)
        return {"order": orders.public(o), "duplicate": bool(o.get("duplicate"))}
    if purpose != "ENTRY":
        raise _err(422, "purpose_invalid", "purpose must be ENTRY or EXIT.")
    proposal = await db[C.PROPOSALS].find_one({"_id": body.proposal_id, "user_id": uid}) if body.proposal_id else None
    if proposal is not None and proposal.get("state") == C.PROP_ORDER_CREATED:
        o = await db[store.ORDERS].find_one({"proposal_id": proposal["_id"], "user_id": uid, "purpose": "ENTRY"})
        if o is not None:
            return {"order": orders.public(o), "duplicate": True}
    if proposal is None or proposal.get("state") != C.PROP_READY_FOR_ORDER:
        raise _err(422, "entry_requires_approved_proposal",
                   "A paper entry is created only from your own proposal that has passed the risk checks and is ready "
                   "for an order.", proposal_state=(proposal or {}).get("state"))
    try:
        from services.spt import pipeline                     # slice B: it owns the risk decision and the reservation
        place = getattr(pipeline, "place_entry_order")
    except (ImportError, AttributeError):
        raise _err(503, "entry_pipeline_unavailable", "The proposal pipeline is not available, so no entry was created.")
    o = await place(db, user_id=uid, proposal_id=proposal["_id"], actor_id=uid)
    return {"order": orders.public(o), "duplicate": bool((o or {}).get("duplicate"))}


@router.get("/paper/orders")
async def list_orders(request: Request, state: Optional[str] = Query(None, max_length=20),
                      purpose: Optional[str] = Query(None, max_length=10), limit: int = Query(100, ge=1, le=MAX_LIST)):
    uid = await _uid(request)
    q: Dict[str, Any] = {"user_id": uid}
    if state:
        s = state.strip().upper()
        if s == "LIVE":
            q["state"] = {"$in": list(C.ORD_LIVE_STATES)}
        elif s in C.ORD_STATES:
            q["state"] = s
        else:
            raise _err(422, "state_invalid", "Unknown order state.", allowed=list(C.ORD_STATES) + ["LIVE"])
    if purpose:
        if purpose.strip().upper() not in C.ORDER_PURPOSES:
            raise _err(422, "purpose_invalid", "purpose must be ENTRY or EXIT.")
        q["purpose"] = purpose.strip().upper()
    rows = await db[store.ORDERS].find(q).sort("created_at", -1).limit(limit).to_list(limit)
    return {"orders": [orders.public(o) for o in rows], "count": len(rows)}


@router.get("/paper/orders/{order_id}")
async def get_order(request: Request, order_id: str):
    uid = await _uid(request)
    return {"order": orders.public(await _own_order(uid, order_id), with_fills=True)}


@router.post("/paper/orders/{order_id}/cancel")
async def cancel(request: Request, order_id: str):
    uid = await _uid(request)
    await _own_order(uid, order_id)
    o = await orders.cancel_paper_order(db, order_id, reason="user_cancelled", user_id=uid)
    if o is None:
        raise _err(409, "order_not_live", "The order is no longer live, so it cannot be cancelled.")
    return {"order": orders.public(o)}


@router.get("/paper/positions")
async def list_positions(request: Request, status: str = Query("open", max_length=10),
                         limit: int = Query(200, ge=1, le=MAX_LIST)):
    uid = await _uid(request)
    s = status.strip().lower()
    q: Dict[str, Any] = {"user_id": uid}
    if s == "open":
        q["state"] = {"$in": list(C.POS_OPEN_STATES)}
    elif s == "closed":
        q["state"] = C.POS_CLOSED
    elif s != "all":
        raise _err(422, "status_invalid", "status must be open, closed or all.")
    rows = await db[store.POSITIONS].find(q).sort("created_at", -1).limit(limit).to_list(limit)
    return {"positions": [positions.public(p) for p in rows], "count": len(rows)}


async def _position_detail(pos: Dict[str, Any]) -> Dict[str, Any]:
    fills = await db[store.FILLS].find({"$or": [{"order_id": pos.get("entry_order_id")},
                                                {"position_id": pos["_id"]}]}).to_list(MAX_LIST)
    fills = sorted(fills, key=lambda f: (str(f.get("at") or ""), int(f.get("seq") or 0)))
    order_ids = sorted({pos.get("entry_order_id")} | {f.get("order_id") for f in fills}
                       | {o["_id"] for o in await db[store.ORDERS].find({"position_id": pos["_id"]}).to_list(MAX_LIST)})
    events = await db[C.EVENTS].find({"account_id": pos["user_id"], "$or": [
        {"payload.position_id": pos["_id"]}, {"payload.order_id": {"$in": [i for i in order_ids if i]}}]}) \
        .sort("occurred_at", 1).to_list(1000)
    return {"position": positions.public(pos), "fills": fills, "modifications": pos.get("modifications") or [],
            "orders": [i for i in order_ids if i], "events": events}


@router.get("/paper/positions/{position_id}")
async def get_position(request: Request, position_id: str):
    uid = await _uid(request)
    return await _position_detail(await _own_position(uid, position_id))


@router.post("/paper/positions/{position_id}/modify")
async def modify(request: Request, position_id: str, body: ModifyIn):
    uid = await _uid(request)
    await _own_position(uid, position_id)
    try:
        out = await modify_mod.modify_position(db, user_id=uid, position_id=position_id, change=body.change,
                                               reason=body.reason or "", requested_by=uid,
                                               expect_version=body.expect_version, quotes=_quotes)
    except modify_mod.ModifyRefused as e:
        raise _err(e.status, e.code, "The modification was not applied.", **e.detail)
    return out


@router.post("/paper/positions/{position_id}/exit")
async def exit_position(request: Request, position_id: str, body: Optional[ExitIn] = None):
    uid = await _uid(request)
    await _own_position(uid, position_id)
    b = body or ExitIn()
    try:
        o = await orders.create_exit_order(db, position_id=position_id, reason="manual", quantity=b.quantity,
                                           order_type=b.order_type, limit_price=b.limit_price, actor_id=uid,
                                           trigger={"requested_by": uid, "via": "POST /paper/positions/{id}/exit"})
    except orders.ExitRefused as e:
        raise _exit_refused(e)
    return {"order": orders.public(o), "duplicate": bool(o.get("duplicate"))}


async def _signal_ids(opportunity_id: Optional[str]) -> List[str]:
    """The scanner signals behind a trade (slice A's opportunity document), read-only; [] when not there."""
    if not opportunity_id:
        return []
    opp = await db[C.OPPORTUNITIES].find_one({"_id": opportunity_id})
    return [s.get("signal_id") for s in (opp or {}).get("signals") or [] if s.get("signal_id")]


def _trade(pos: Dict[str, Any]) -> Dict[str, Any]:
    out = pos.get("outcome") or {}
    p = positions.public(pos)
    return {"trade_id": pos["_id"], "position_id": pos["_id"], "symbol": pos.get("symbol"), "direction": pos.get("direction"),
            "quantity": pos.get("entry_qty"), "avg_entry_price": pos.get("avg_entry_price"),
            "avg_exit_price": out.get("avg_exit_price"), "realized_gross_rs": pos.get("realized_gross_rs"),
            "realized_net_rs": pos.get("realized_net_rs"), "costs_rs": out.get("costs_rs"), "r_multiple": p.get("r_multiple"),
            "mfe_rs": p.get("mfe_rs"), "mae_rs": p.get("mae_rs"), "mfe_r": p.get("mfe_r"), "mae_r": p.get("mae_r"),
            "exit_reason": pos.get("exit_reason"), "exit_gap": pos.get("exit_gap"), "opened_at": pos.get("opened_at"),
            "closed_at": pos.get("closed_at"), "proposal_id": pos.get("proposal_id"),
            "opportunity_id": pos.get("opportunity_id"), "entry_order_id": pos.get("entry_order_id"),
            "release_state": (pos.get("release") or {}).get("state")}


@router.get("/paper/trades")
async def list_trades(request: Request, limit: int = Query(200, ge=1, le=MAX_LIST)):
    uid = await _uid(request)
    rows = await db[store.POSITIONS].find({"user_id": uid, "state": C.POS_CLOSED}).sort("closed_at", -1) \
        .limit(limit).to_list(limit)
    trades = []
    for p in rows:
        t = _trade(p)
        t["signal_ids"] = await _signal_ids(p.get("opportunity_id"))
        trades.append(t)
    return {"trades": trades, "count": len(trades)}


@router.get("/paper/trades/{trade_id}")
async def get_trade(request: Request, trade_id: str):
    uid = await _uid(request)
    pos = await store.get_position(db, trade_id)
    if pos is None or pos.get("user_id") != uid or pos.get("state") != C.POS_CLOSED:
        raise _err(404, "trade_not_found", "No such closed paper trade for this account.")
    t = _trade(pos)
    t["signal_ids"] = await _signal_ids(pos.get("opportunity_id"))
    return {"trade": t, "outcome": pos.get("outcome"), **await _position_detail(pos)}


@router.get("/paper/reconcile")
async def reconcile_report(request: Request):
    uid = await _uid(request)
    return await reconcile.report(db, user_id=uid)


# ── P1: the event stream ─────────────────────────────────────────────────────────────────────────────────────────────

async def events_after(dbh, uid: str, cursor: str, seen: set, *, limit: int = 200) -> Tuple[List[Dict[str, Any]], str, set]:
    """The caller's events ingested at or after `cursor` that were not sent yet, oldest first; the new cursor and the
    ids already sent at it (two events can share one stamp)."""
    rows = await dbh[C.EVENTS].find({"account_id": uid, "ingested_at": {"$gte": cursor}}).sort("ingested_at", 1) \
        .limit(limit).to_list(limit)
    fresh = [e for e in rows if e.get("event_id") not in seen]
    if not fresh:
        return [], cursor, seen
    last = max(str(e.get("ingested_at") or "") for e in fresh)
    keep = {e.get("event_id") for e in rows if str(e.get("ingested_at") or "") == last}
    return fresh, last, keep


@router.get("/paper/stream")
async def stream(request: Request, since: Optional[str] = Query(None, max_length=40)):
    uid = await _uid(request)
    start = since or store.iso()

    async def gen():
        loop = asyncio.get_event_loop()
        began = loop.time()
        cursor, seen = start, set()
        quiet = 0.0
        yield "retry: 3000\n\n"
        while loop.time() - began < STREAM_MAX_SECONDS:
            if await request.is_disconnected():
                return
            try:
                rows, cursor, seen = await events_after(db, uid, cursor, seen)
            except Exception as e:  # noqa: BLE001 — tell the client, keep the stream
                logger.warning("spt paper stream: read failed (%s)", type(e).__name__)
                yield f"event: problem\ndata: {json.dumps({'error': 'events_unavailable', 'kind': type(e).__name__})}\n\n"
                rows = []
            for e in rows:
                yield (f"id: {e.get('event_id')}\nevent: {e.get('event_type')}\n"
                       f"data: {json.dumps(e, separators=(',', ':'), default=str)}\n\n")
            quiet = 0.0 if rows else quiet + STREAM_POLL_SECONDS
            if quiet >= HEARTBEAT_SECONDS:
                quiet = 0.0
                yield ": heartbeat\n\n"
            await asyncio.sleep(STREAM_POLL_SECONDS)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"})
