"""Trade Journal — staged-entry tracker for positional / BTST trades.

Stores user-logged trades against picks, with:
  • staged-entry plan (4 stages: 20 / 30 / 30 / 20 % of capital)
  • exit ladder (book 25% at +8-10%, 25% at +12-15%, trail rest)
  • running P&L + readiness vs the live LTP
  • status: OPEN / CLOSED / STOPPED

The journal collection is `trade_journal`. Schema:
  {
    _id, user_id, nse_symbol, opened_at, closed_at,
    capital_alloc_rs, stop_loss, target,
    plan_source: "POSITIONAL_PICK" | "MANUAL",
    pick_signal_date,
    fills: [{stage, qty, price, at, kind: "ENTRY|EXIT"}],
    status: "OPEN|CLOSED|STOPPED",
    notes,
    realized_pnl, realized_pnl_pct,
    created_at, updated_at,
  }

Hedge tracker is OUT-OF-SCOPE for v1 (deferred — needs option chain feed).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, Request

from deps import db, get_current_user
from services import risk_controls as rc
from services import risk_gate

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/positional/journal", tags=["positional-journal"])

COL = "trade_journal"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _public(doc: dict) -> dict:
    """Strip _id, return clean dict."""
    return {k: v for k, v in doc.items() if k != "_id"}


def _compute_pnl(trade: dict, ltp: Optional[float]) -> Dict[str, Any]:
    """Aggregate fills → cost basis, exit value, realized + unrealized P&L."""
    fills = trade.get("fills") or []
    qty_in = 0
    qty_out = 0
    cost_in = 0.0
    proc_out = 0.0
    for f in fills:
        q = float(f.get("qty") or 0)
        p = float(f.get("price") or 0)
        if (f.get("kind") or "ENTRY").upper() == "ENTRY":
            qty_in += q
            cost_in += q * p
        else:
            qty_out += q
            proc_out += q * p
    avg_in = (cost_in / qty_in) if qty_in else 0.0
    avg_out = (proc_out / qty_out) if qty_out else 0.0

    held_qty = max(qty_in - qty_out, 0)
    realized_pnl = proc_out - (avg_in * qty_out) if qty_out else 0.0
    unrealized_pnl = (
        (ltp - avg_in) * held_qty if (ltp and held_qty) else 0.0
    )
    invested = cost_in
    cap_alloc = float(trade.get("capital_alloc_rs") or 0) or invested or 1.0
    deployed_pct = round((invested / cap_alloc) * 100, 1) if cap_alloc else 0.0

    return {
        "qty_in": qty_in,
        "qty_out": qty_out,
        "held_qty": held_qty,
        "avg_buy": round(avg_in, 2),
        "avg_sell": round(avg_out, 2) if qty_out else None,
        "invested_rs": round(invested, 2),
        "deployed_pct": deployed_pct,
        "realized_pnl_rs": round(realized_pnl, 2),
        "unrealized_pnl_rs": round(unrealized_pnl, 2),
        "total_pnl_rs": round(realized_pnl + unrealized_pnl, 2),
        "total_pnl_pct": (
            round(((realized_pnl + unrealized_pnl) / invested) * 100, 2)
            if invested else 0.0
        ),
    }


def _next_stage(trade: dict) -> Optional[str]:
    """Determine which staged entry comes next (PILOT / CONFIRM / SUSTAIN / MOMENTUM)."""
    stages = ["PILOT", "CONFIRM", "SUSTAIN", "MOMENTUM"]
    used = {(f.get("stage") or "").upper() for f in (trade.get("fills") or []) if (f.get("kind") or "ENTRY").upper() == "ENTRY"}
    for s in stages:
        if s not in used:
            return s
    return None


def _stage_targets(trade: dict) -> List[Dict[str, Any]]:
    """Return the 4-step deployment plan with rupee allocation per stage.

    Default split per the user's framework: 20 / 30 / 30 / 20 % of capital.
    """
    cap = float(trade.get("capital_alloc_rs") or 0)
    plan = trade.get("entry_plan") or {}
    weights = plan.get("weights") or [0.20, 0.30, 0.30, 0.20]
    names = ["PILOT", "CONFIRM", "SUSTAIN", "MOMENTUM"]
    triggers = plan.get("triggers") or [
        "Mini-consolidation breakout · vol > 3d avg · sector strong",
        "Closes strong · VWAP holds · no rejection",
        "Crosses prior swing high",
        "OI rising · sector outperforming",
    ]
    used = {(f.get("stage") or "").upper(): f for f in (trade.get("fills") or []) if (f.get("kind") or "ENTRY").upper() == "ENTRY"}
    out = []
    for i, name in enumerate(names):
        w = weights[i] if i < len(weights) else 0.0
        out.append({
            "stage":      name,
            "alloc_rs":   round(cap * w, 0),
            "alloc_pct":  round(w * 100, 0),
            "trigger":    triggers[i] if i < len(triggers) else "",
            "filled":     name in used,
            "fill":       _public(used[name]) if name in used else None,
        })
    return out


def _exit_ladder(trade: dict, ltp: Optional[float]) -> List[Dict[str, Any]]:
    """4-step exit ladder per the user's framework: +5% (recover hedge),
    +8-10% (book 25%), +12-15% (book 25%), trail rest."""
    avg_in = _compute_pnl(trade, ltp)["avg_buy"]
    if avg_in <= 0:
        return []
    levels = [
        {"name": "+5%",        "trigger_price": round(avg_in * 1.05, 2), "action": "Cover hedge cost"},
        {"name": "+8-10%",     "trigger_price": round(avg_in * 1.09, 2), "action": "Book 25% — recycle to next leg"},
        {"name": "+12-15%",    "trigger_price": round(avg_in * 1.135, 2), "action": "Book another 25%"},
        {"name": "Trailing",   "trigger_price": None,                     "action": "Trail rest using 5 EMA / swing low"},
    ]
    if ltp:
        for lv in levels:
            tp = lv["trigger_price"]
            if tp is None:
                lv["status"] = "ACTIVE"
            elif ltp >= tp:
                lv["status"] = "HIT"
            else:
                lv["status"] = "WAITING"
    return levels


# ── the kill switch (the F&O risk gate's flag off) ─────────────────────
async def _kill_switch(request: Request, user: dict, *, path: str, symbol: Any = None,
                       requested_qty: Optional[float] = None) -> None:
    """409 risk_blocked when the user's kill switch or halt is on (or the controls cannot be read: fail closed),
    recorded with the path, the symbol and the request's correlation id. Nothing is written before it."""
    try:
        await rc.assert_allowed(db, user["user_id"], "journal_trade")
    except rc.RiskBlocked as blocked:
        sym = symbol.strip().upper()[:20] if isinstance(symbol, str) and symbol.strip() else None
        detail = blocked.detail("journal_trade")
        await rc.record_decision(db, user["user_id"], action="journal_trade", outcome="blocked", symbol=sym,
                                 requested_qty=requested_qty, reasons=[{"code": "RISK_CONTROL", "text": str(blocked)}],
                                 correlation_id=risk_gate.correlation_id(request), detail=detail, path=path)
        raise HTTPException(status_code=409, detail=detail)


# ── CRUD ────────────────────────────────────────────────────────────────
@router.post("")
async def create_trade(request: Request):
    """Open a new trade journal entry."""
    user = await get_current_user(request)
    gated = await risk_gate.enabled_for(db, user)
    try:
        body = await request.json()
    except ValueError:
        body = None
    # Same kill switch as the other position-creating paths; this one had no risk gate either. With the
    # F&O risk gate on, the same controls are the gate's first check. The body is only read here, for the
    # symbol on the refusal's record; nothing is validated or written before the check.
    if not gated:
        await _kill_switch(request, user, path="journal_create",
                           symbol=body.get("nse_symbol") if isinstance(body, dict) else None)
    if not isinstance(body, dict):
        raise HTTPException(400, "nse_symbol and capital_alloc_rs are required")
    sym = (body.get("nse_symbol") or "").upper().strip()
    cap = float(body.get("capital_alloc_rs") or 0)
    if not sym or cap <= 0:
        raise HTTPException(400, "nse_symbol and capital_alloc_rs are required")
    decision = None
    if gated:
        # The journal records the user's own trades; the platform places nothing, so the gate sees "paper".
        # The capital allocated is the capital at risk: a long share position can lose all of it.
        decision = await risk_gate.enforce(db, risk_gate.cash_request(
            user, risk_gate.correlation_id(request), path="journal_create", mode="paper", action="open",
            symbol=sym, quantity=None, capital_at_risk_rs=cap))

    trade = {
        "_id":              str(uuid4()),
        "user_id":          user["user_id"],
        "nse_symbol":       sym,
        "capital_alloc_rs": cap,
        "stop_loss":        float(body.get("stop_loss") or 0),
        "target":           float(body.get("target") or 0),
        "plan_source":      (body.get("plan_source") or "MANUAL").upper(),
        "pick_signal_date": body.get("pick_signal_date"),
        "entry_plan":       body.get("entry_plan") or {},
        "fills":            [],
        "status":           "OPEN",
        "notes":            body.get("notes") or "",
        "opened_at":        _now(),
        "closed_at":        None,
        "created_at":       _now(),
        "updated_at":       _now(),
    }
    if decision is not None:
        risk_gate.stamp(trade, decision)
    await db[COL].insert_one(trade)
    return _public(trade)


@router.get("")
async def list_trades(request: Request,
                       status: Optional[str] = Query(None),
                       symbol: Optional[str] = Query(None),
                       live: bool = Query(False)):
    user = await get_current_user(request)
    q: Dict[str, Any] = {"user_id": user["user_id"]}
    if status:
        q["status"] = status.upper()
    if symbol:
        q["nse_symbol"] = symbol.upper().strip()
    docs = await db[COL].find(q).sort("opened_at", -1).to_list(500)

    # Live LTP overlay (best-effort, capped 6s)
    ltp_by_sym: Dict[str, float] = {}
    if live and docs:
        import asyncio
        try:
            from services import live_price as _lp
            syms = list({d["nse_symbol"] for d in docs})
            ltp_by_sym = await asyncio.wait_for(
                asyncio.to_thread(_lp._batch_fetch_prices, syms), timeout=6.0,
            )
        except Exception as e:  # noqa: BLE001
            logger.debug("journal live overlay failed: %s", e)
            ltp_by_sym = {}

    out = []
    for d in docs:
        ltp = ltp_by_sym.get(d["nse_symbol"]) if live else None
        pnl = _compute_pnl(d, ltp)
        out.append({
            **_public(d),
            "live_price":   ltp,
            "pnl":          pnl,
            "next_stage":   _next_stage(d),
        })
    return {"count": len(out), "trades": out, "live": bool(live)}


@router.get("/{trade_id}")
async def get_trade(request: Request, trade_id: str, live: bool = Query(True)):
    user = await get_current_user(request)
    doc = await db[COL].find_one({"_id": trade_id, "user_id": user["user_id"]})
    if not doc:
        raise HTTPException(404, "trade not found")

    ltp: Optional[float] = None
    if live:
        import asyncio
        try:
            from services import live_price as _lp
            res = await asyncio.wait_for(
                asyncio.to_thread(_lp._batch_fetch_prices, [doc["nse_symbol"]]),
                timeout=6.0,
            )
            ltp = res.get(doc["nse_symbol"])
        except Exception:  # noqa: BLE001
            ltp = None

    return {
        **_public(doc),
        "live_price":   ltp,
        "pnl":          _compute_pnl(doc, ltp),
        "next_stage":   _next_stage(doc),
        "stage_plan":   _stage_targets(doc),
        "exit_ladder":  _exit_ladder(doc, ltp),
    }


@router.post("/{trade_id}/fill")
async def add_fill(request: Request, trade_id: str):
    """Add a staged entry / exit fill.

    Body: {stage: "PILOT|CONFIRM|SUSTAIN|MOMENTUM", qty, price,
           kind: "ENTRY|EXIT", at?: ISO}

    Only the owner's OPEN trade takes a fill (409 trade_not_open otherwise), and the write is filtered
    on both, so a fill can never land on another user's trade or on a closed one. An ENTRY fill (it adds to the
    position) is checked first: by the F&O risk gate when it is on, else by the kill switch and the halt. An EXIT
    fill reduces risk and is not checked.
    """
    user = await get_current_user(request)
    uid = user["user_id"]
    doc = await db[COL].find_one({"_id": trade_id, "user_id": uid})
    if not doc:
        raise HTTPException(404, "trade not found")
    if doc.get("status") != "OPEN":
        raise HTTPException(status_code=409, detail="trade_not_open")

    body = await request.json()
    fill = {
        "stage": (body.get("stage") or "MOMENTUM").upper(),
        "qty":   float(body.get("qty") or 0),
        "price": float(body.get("price") or 0),
        "at":    body.get("at") or _now(),
        "kind":  (body.get("kind") or "ENTRY").upper(),
        "id":    str(uuid4()),
    }
    if fill["qty"] <= 0 or fill["price"] <= 0:
        raise HTTPException(400, "qty and price must be > 0")
    if fill["kind"] == "ENTRY":
        if await risk_gate.enabled_for(db, user):
            decision = await risk_gate.enforce(db, risk_gate.cash_request(
                user, risk_gate.correlation_id(request), path="journal_fill", mode="paper", action="add",
                symbol=doc.get("nse_symbol"), quantity=fill["qty"], capital_at_risk_rs=fill["qty"] * fill["price"]))
            risk_gate.stamp(fill, decision)
        else:
            # An ENTRY fill adds to the position, so the kill switch applies with the flag off too. It used to be
            # checked only inside the gate: with the flag off (staging's setting) a Rs 1 crore fill was accepted
            # with the kill switch on, although the flag's own description says "Off = the kill-switch check only".
            await _kill_switch(request, user, path="journal_fill", symbol=doc.get("nse_symbol"),
                               requested_qty=fill["qty"])

    res = await db[COL].update_one(
        {"_id": trade_id, "user_id": uid, "status": "OPEN"},
        {"$push": {"fills": fill}, "$set": {"updated_at": _now()}},
    )
    if not res.matched_count:
        # Closed (or deleted) between the read and the write.
        raise HTTPException(status_code=409, detail="trade_not_open")
    updated = await db[COL].find_one({"_id": trade_id, "user_id": uid})
    return {
        **_public(updated),
        "added_fill": fill,
        "pnl": _compute_pnl(updated, None),
        "next_stage": _next_stage(updated),
    }


@router.post("/{trade_id}/close")
async def close_trade(request: Request, trade_id: str):
    """Mark trade as CLOSED (or STOPPED) and lock final P&L."""
    user = await get_current_user(request)
    doc = await db[COL].find_one({"_id": trade_id, "user_id": user["user_id"]})
    if not doc:
        raise HTTPException(404, "trade not found")
    body = await request.json()
    status_new = (body.get("status") or "CLOSED").upper()
    if status_new not in ("CLOSED", "STOPPED"):
        raise HTTPException(400, "status must be CLOSED or STOPPED")

    pnl = _compute_pnl(doc, None)
    await db[COL].update_one(
        {"_id": trade_id},
        {"$set": {
            "status":            status_new,
            "closed_at":         _now(),
            "realized_pnl_rs":   pnl["realized_pnl_rs"],
            "realized_pnl_pct":  pnl["total_pnl_pct"],
            "updated_at":        _now(),
        }},
    )
    return {"ok": True, "status": status_new, "pnl": pnl}


@router.delete("/{trade_id}", response_model=None)
async def delete_trade(request: Request, trade_id: str):
    """Hard-delete a trade entry (use sparingly — prefer close)."""
    user = await get_current_user(request)
    res = await db[COL].delete_one({"_id": trade_id, "user_id": user["user_id"]})
    if res.deleted_count == 0:
        raise HTTPException(404, "trade not found")
    return {"ok": True, "deleted": trade_id}


@router.get("/summary/portfolio")
async def trade_summary(request: Request):
    """Aggregate exposure, # open trades, gross P&L, hedge-need flag."""
    user = await get_current_user(request)
    docs = await db[COL].find({"user_id": user["user_id"]}).to_list(2000)
    open_trades = [d for d in docs if d.get("status") == "OPEN"]
    closed = [d for d in docs if d.get("status") in ("CLOSED", "STOPPED")]

    gross_long = 0.0
    invested = 0.0
    for t in open_trades:
        pnl = _compute_pnl(t, None)
        invested += pnl["invested_rs"]
        gross_long += pnl["invested_rs"]   # all longs for now

    realized = sum(float(t.get("realized_pnl_rs") or 0) for t in closed)
    win = sum(1 for t in closed if (t.get("realized_pnl_rs") or 0) > 0)
    loss = sum(1 for t in closed if (t.get("realized_pnl_rs") or 0) < 0)

    # Hedge guidance: at gross long > ₹2L OR open trades >= 5, suggest hedge.
    needs_hedge = gross_long >= 200_000 or len(open_trades) >= 5
    suggested_pe = None
    if needs_hedge and gross_long > 0:
        # Crude sizing: 1 lot Nifty PE per ₹6L gross long (≈ 1× delta hedge
        # at 50-delta ATM). Refine later when option chain is wired.
        lots = max(1, round(gross_long / 600_000))
        suggested_pe = {
            "instrument":  "Nifty ATM PE (weekly)",
            "lots":        lots,
            "rationale":   f"Hedge ₹{gross_long:,.0f} gross long; ~1 lot per ₹6L exposure",
        }

    return {
        "open_count":       len(open_trades),
        "closed_count":     len(closed),
        "gross_long_rs":    round(gross_long, 0),
        "invested_rs":      round(invested, 0),
        "realized_pnl_rs":  round(realized, 0),
        "win_count":        win,
        "loss_count":       loss,
        "win_rate_pct":     (round(100 * win / (win + loss), 1) if (win + loss) else None),
        "needs_hedge":      needs_hedge,
        "suggested_hedge":  suggested_pe,
    }
