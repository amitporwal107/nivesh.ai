"""Paper fills → orders, ledger, positions, journal; and the session steps that drive them (PHASE2_DESIGN §5–§6).

run_open     simulation OPEN (09:15): submit what was validated at 09:00 and price it from the session's daily row.
run_close    simulation CLOSE (15:30): resting limits that price traded through, expiry of the rest, marks, snapshot.
live_tick    the live desk: price working orders from FRESH live quotes only; expire at the session close; mark positions.

Every fill is SIMULATED. Nothing here reaches a broker. Narrative strings avoid the AD-92 words.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional

from .. import contracts as C
from .. import store
from ..market.live_quotes import check_quote, in_fill_window
from ..market.view import IST
from . import capital, costs, journal, orders, positions
from . import fill_model as fm
from .capital import rs
from .gateway import ExecutionGateway, PRODUCER, session_close_utc

log = logging.getLogger(__name__)
ZERO = Decimal("0")
TERMINAL = {s.value for s in C.ORDER_TERMINAL}


# ── one fill ────────────────────────────────────────────────────────────────

async def apply_fill(c, *, intent: dict, order: dict, d: fm.Decision, plan: dict, body: C.TradePlanBody, res: dict,
                     siblings: list[dict], policy: C.PolicyBody, at: datetime, sim_time: Optional[datetime],
                     quote_ref: Optional[str] = None) -> dict:
    """Book one fill: fill row, order move, ledger rows, reservation conversion, position leg, journal. Returns the order."""
    tenant_id = order["tenant_id"]
    qty, price = d.qty, d.price
    value = rs(price * qty)
    ch = costs.charges(order["kind"], order["side"], value, first_fill=order["filled_qty"] == 0)
    fees = rs(ch["total"])
    fill_time = at + timedelta(milliseconds=d.latency_ms)
    fill_id = C.new_id("FIL")
    await c.execute(
        """INSERT INTO autodesk.trade_fills (fill_id, order_id, intent_id, tenant_id, account_id, simulation_id, trade_id,
               leg_id, side, quantity, price, arrival_price, value_rs, spread_rs, slippage_rs, charges, charges_rs,
               cost_model, price_source, fill_model, latency_ms, fill_time, sim_time, session_date)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22,$23,$24)""",
        fill_id, order["order_id"], intent["intent_id"], tenant_id, order["account_id"], order["simulation_id"],
        order["trade_id"], order["leg_id"], order["side"], qty, price, d.arrival or price, value, rs(d.spread_rs),
        rs(d.slippage_rs), {k: str(v) for k, v in ch.items()}, fees, costs.COST_MODEL, d.source, fm.VERSION,
        d.latency_ms, fill_time, sim_time, order["session_date"])
    new_filled = order["filled_qty"] + qty
    avg = ((order["avg_fill_price"] or ZERO) * order["filled_qty"] + price * qty) / new_filled
    to = C.OrderState.FILLED if new_filled >= order["quantity"] else C.OrderState.PARTIALLY_FILLED
    cols: dict[str, Any] = {"filled_qty": new_filled, "avg_fill_price": avg}
    if quote_ref:
        cols["last_quote_ref"] = quote_ref
    order_after = await orders.move(c, order, to, reason=f"{qty} filled at {price} ({d.source})", sim_time=sim_time,
                                    detail={"fill_id": fill_id, "price": str(price), "qty": qty}, **cols)

    # ledger: funds (shares and premium), futures margin, charges; then the reservation converts
    kind, side = order["kind"], order["side"]
    cash = ZERO if kind == "FUT" else (-value if side == "BUY" else value)
    margin = rs(value * policy.futures_margin_pct / 100) if kind == "FUT" else ZERO
    base = dict(tenant_id=tenant_id, account_id=order["account_id"], simulation_id=order["simulation_id"],
                trade_id=order["trade_id"], ref_type="FILL", ref_id=fill_id, sim_time=sim_time)
    await capital.post(c, **base, entry_type=C.LedgerEntry.POSITION_FUNDS, cash=cash, notional=value,
                       memo=f"{side.lower()} {qty} {order['underlying']} {kind} at {price}")
    if margin:
        await capital.post(c, **base, entry_type=C.LedgerEntry.MARGIN_UTILIZED, margin=margin,
                           memo=f"futures margin estimate {policy.futures_margin_pct}% of {value}")
    await capital.post(c, **base, entry_type=C.LedgerEntry.FEES_BOOKED, cash=-fees, fees=fees, memo="charges on the fill")
    total_ref = sum((s["ref_price"] * s["quantity"] for s in siblings), ZERO) or Decimal("1")
    share = (order["ref_price"] * qty) / total_ref
    # shares of several legs are rounded to the paisa each; never move more than what the reservation still holds
    risk_moved = min(rs(res["risk_rs"] * share), res["risk_rs"] - res["risk_moved_rs"])
    commit_done = min(rs(res["commitment_rs"] * share), res["commitment_rs"] - res["commitment_done_rs"])
    used = max(ZERO, -cash) + margin + fees
    await capital.consume(c, res, used_rs=used, risk_moved_rs=risk_moved, commitment_done_rs=commit_done, ref_id=fill_id,
                          sim_time=sim_time)

    pos = await c.fetchrow("SELECT open_risk_rs, capital_rs FROM autodesk.trade_positions WHERE trade_id=$1", order["trade_id"])
    pos_row, created = await positions.open_or_add(
        c, plan={"trade_id": order["trade_id"], "instrument": plan["instrument"], "strategy_type": plan["strategy_type"]},
        order=order, qty=qty, price=price, value_rs=value, charges_rs=fees, margin_rs=margin,
        open_risk_rs=(pos["open_risk_rs"] if pos else ZERO) + risk_moved,
        capital_rs=min((pos["capital_rs"] if pos else ZERO) + rs(res["capital_rs"] * share), res["capital_rs"]), sector=res["sector"], fno=res["fno"],
        at=fill_time, sim_time=sim_time)
    await store.emit(c, C.EventType.ORDER_FILLED, tenant_id=tenant_id, producer=PRODUCER, account_id=order["account_id"],
                     simulation_id=order["simulation_id"], correlation_id=order["trade_id"], sim_time=sim_time,
                     payload={"fill_id": fill_id, "order_id": order["order_id"], "trade_id": order["trade_id"],
                              "leg_id": order["leg_id"], "quantity": qty, "price": str(price), "charges_rs": str(fees),
                              "fill_kind": "SIMULATED", "price_source": d.source})
    jb = dict(tenant_id=tenant_id, account_id=order["account_id"], simulation_id=order["simulation_id"],
              trade_id=order["trade_id"], sim_time=sim_time)
    await journal.record(c, **jb, kind="FILL", ref_id=fill_id,
                         summary=f"{qty} {order['underlying']} {kind} {side.lower()} filled at {price} (simulated), "
                                 f"charges {fees}", data={"price": str(price), "quantity": qty, "source": d.source})
    if created:
        await journal.record(c, **jb, kind="POSITION", ref_id=pos_row["position_id"],
                             summary=f"position opened on {plan['instrument']} ({plan['strategy_type']})")
    return order_after


async def _basket_margin(c, intent: dict, spec: dict, pos_trade_id: str, at: datetime, sim_time: Optional[datetime]) -> None:
    """A credit structure ties up its width once all legs have filled (PHASE2_DESIGN §3.1)."""
    if not spec.get("credit_width_rs"):
        return
    width = Decimal(spec["credit_width_rs"])
    await capital.post(c, tenant_id=intent["tenant_id"], account_id=intent["account_id"], simulation_id=intent["simulation_id"],
                       entry_type=C.LedgerEntry.MARGIN_UTILIZED, ref_type="INTENT", ref_id=intent["intent_id"],
                       trade_id=pos_trade_id, memo="width of the credit structure", sim_time=sim_time, margin=width)
    await c.execute("UPDATE autodesk.trade_positions SET margin_rs=margin_rs+$2, updated_at=now() WHERE trade_id=$1",
                    pos_trade_id, width)


# ── ending an intent ──────────────────────────────────────────────────────────

async def finish_intent(c, intent: dict, *, as_of: datetime, sim_time: Optional[datetime], why: str) -> dict:
    """When every order is terminal: close the reservation, set the intent's result and the plan's status."""
    intent = dict(await c.fetchrow("SELECT * FROM autodesk.execution_intents WHERE intent_id=$1 FOR UPDATE",
                                   intent["intent_id"]))
    if intent["status"] in ("COMPLETED", "REFUSED"):
        return intent
    os_ = await orders.of_intent(c, intent["intent_id"])
    if any(o["state"] not in TERMINAL for o in os_):
        return intent
    tenant_id = intent["tenant_id"]
    if intent["reservation_id"]:
        res = await capital.get_reservation(c, tenant_id, intent["reservation_id"], for_update=True)
        status = C.ReservationStatus.EXPIRED if any(o["state"] == "EXPIRED" for o in os_) else C.ReservationStatus.RELEASED
        await capital.close_reservation(c, res, status=status, reason=f"orders ended: {why}", sim_time=sim_time)
    filled = [o for o in os_ if o["filled_qty"] > 0]
    full = all(o["state"] == "FILLED" for o in os_)
    result = "FILLED" if full else ("PARTIALLY_FILLED" if filled else "NOT_FILLED")
    row = await c.fetchrow("UPDATE autodesk.execution_intents SET status='COMPLETED', result=$2, updated_at=now() "
                           "WHERE intent_id=$1 RETURNING *", intent["intent_id"], result)
    if filled:
        plan_status = C.PlanStatus.EXECUTED
    elif any(o["state"] == "REJECTED" for o in os_):
        plan_status = C.PlanStatus.EXECUTION_REFUSED
    else:
        plan_status = C.PlanStatus.EXPIRED
    await store.set_plan_status(c, tenant_id=tenant_id, trade_id=intent["trade_id"], status=plan_status)
    await store.emit(c, C.EventType.EXECUTION_INTENT_COMPLETED, tenant_id=tenant_id, producer=PRODUCER,
                     account_id=intent["account_id"], simulation_id=intent["simulation_id"], correlation_id=intent["trade_id"],
                     sim_time=sim_time, payload={"intent_id": intent["intent_id"], "trade_id": intent["trade_id"],
                                                 "result": result, "plan_status": plan_status.value, "why": why})
    return dict(row)


async def _end_orders(c, os_: list[dict], to: C.OrderState, *, reason: str, sim_time, code: Optional[str] = None) -> None:
    for o in os_:
        if o["state"] in TERMINAL:
            continue
        cols = {"reject_code": code, "reject_reason": reason} if to == C.OrderState.REJECTED else {}
        await orders.move(c, o, to, reason=reason, sim_time=sim_time, **cols)


async def _context(c, gw: ExecutionGateway, intent: dict):
    tenant_id = intent["tenant_id"]
    plan = await store.get_plan(c, tenant_id, intent["trade_id"], intent["plan_version"])
    body = C.TradePlanBody.model_validate(plan["body"])
    account = await store.get_account(c, tenant_id, intent["account_id"])
    pol = C.PolicyBody.model_validate((await store.get_policy(c, tenant_id, account["policy_id"]))["body"])
    res = await capital.get_reservation(c, tenant_id, intent["reservation_id"], for_update=True)
    return plan, body, account, pol, res


async def _apply_priced(c, gw, intent: dict, priced, *, plan, body, policy, res, at: datetime, sim_time,
                        quotes: Optional[dict] = None) -> None:
    """Fills, rests and a rejection from one pricing pass over an intent's orders."""
    spec = intent["order_spec"]
    all_orders = await orders.of_intent(c, intent["intent_id"])
    if priced.reject is not None:
        d = priced.reject
        await _end_orders(c, all_orders, C.OrderState.REJECTED, reason=f"{d.code}: {d.reason}", sim_time=sim_time, code=d.code)
        return
    for o, d in priced.rests:
        await orders.note_no_fill(c, o, d.code or "NO_FILL", d.reason, sim_time)
    filled_any = False
    for o, d in priced.fills:
        fresh = await orders.get_order(c, o["tenant_id"], o["order_id"], for_update=True)
        res = await capital.get_reservation(c, o["tenant_id"], res["reservation_id"], for_update=True)
        await apply_fill(c, intent=intent, order=fresh, d=d, plan=plan, body=body, res=res, siblings=all_orders,
                         policy=policy, at=at, sim_time=sim_time,
                         quote_ref=quotes[orders.leg_ref(fresh).key].ref if quotes else None)
        filled_any = True
    if filled_any and spec.get("basket") and len(priced.fills) == len(all_orders):
        await _basket_margin(c, intent, spec, intent["trade_id"], at, sim_time)


# ── simulation: OPEN ──────────────────────────────────────────────────────────

async def run_open(gw: ExecutionGateway, *, tenant_id: str, simulation_id: str, session: date, as_of: datetime) -> dict:
    """09:15: everything validated at 09:00 is submitted and priced from the session's open."""
    out = {"submitted": 0, "filled_orders": 0, "resting": 0, "rejected": 0}
    async with gw.pool.acquire() as c:
        ids = [r["intent_id"] for r in await c.fetch(
            """SELECT intent_id FROM autodesk.execution_intents WHERE tenant_id=$1 AND simulation_id=$2 AND session_date=$3
               AND status IN ('VALIDATED','SUBMITTED') ORDER BY created_at, intent_id""", tenant_id, simulation_id, session)]
        seed = int((await store.get_simulation(c, tenant_id, simulation_id))["config"].get("seed", 42))
    for iid in ids:
        intent = await gw.submit(tenant_id=tenant_id, intent_id=iid, as_of=as_of)
        if intent["status"] != "SUBMITTED":
            out["rejected"] += intent["status"] == "REFUSED"
            continue
        out["submitted"] += 1
        async with gw.pool.acquire() as c:
            async with c.transaction():
                intent = dict(await c.fetchrow("SELECT * FROM autodesk.execution_intents WHERE intent_id=$1 FOR UPDATE", iid))
                plan, body, _acc, pol, res = await _context(c, gw, intent)
                working = [o for o in await orders.of_intent(c, iid) if o["state"] == "OPEN"]
                if not working:
                    continue
                spec = intent["order_spec"]
                net = Decimal(spec["net_limit_rs"]) if spec.get("net_limit_rs") else None
                inval = orders.invalidation_of(plan["body"], len(body.legs))
                priced = await gw.sim.price_open(working, session=session, seed=seed, net_limit=net, invalidation=inval)
                await _apply_priced(c, gw, intent, priced, plan=plan, body=body, policy=pol, res=res, at=as_of, sim_time=as_of)
                out["filled_orders"] += len(priced.fills)
                out["resting"] += len(priced.rests) if priced.reject is None else 0
                out["rejected"] += 1 if priced.reject is not None else 0
                await finish_intent(c, intent, as_of=as_of, sim_time=as_of, why="the open")
    return out


# ── simulation: CLOSE ─────────────────────────────────────────────────────────

async def run_close(gw: ExecutionGateway, *, tenant_id: str, simulation_id: str, session: date, as_of: datetime) -> dict:
    """15:30: resting limits that price traded through fill at the limit; whatever is left expires; positions are marked
    at the close; the account's session snapshot is written."""
    out = {"filled_orders": 0, "expired_orders": 0, "marked_legs": 0, "stale_legs": 0}
    async with gw.pool.acquire() as c:
        ids = [r["intent_id"] for r in await c.fetch(
            """SELECT intent_id FROM autodesk.execution_intents WHERE tenant_id=$1 AND simulation_id=$2 AND session_date=$3
               AND status IN ('VALIDATED','SUBMITTED') ORDER BY created_at, intent_id""", tenant_id, simulation_id, session)]
    for iid in ids:
        async with gw.pool.acquire() as c:
            async with c.transaction():
                intent = dict(await c.fetchrow("SELECT * FROM autodesk.execution_intents WHERE intent_id=$1 FOR UPDATE", iid))
                plan, body, _acc, pol, res = await _context(c, gw, intent)
                os_ = await orders.of_intent(c, iid)
                working = [o for o in os_ if o["state"] in ("OPEN", "PARTIALLY_FILLED")]
                if working:
                    priced = await gw.sim.price_close(working, session=session)
                    await _apply_priced(c, gw, intent, priced, plan=plan, body=body, policy=pol, res=res, at=as_of, sim_time=as_of)
                    out["filled_orders"] += len(priced.fills)
                os_ = await orders.of_intent(c, iid)
                left = [o for o in os_ if o["state"] not in TERMINAL]
                reason = "the session ended before the order filled" if not any(o["filled_qty"] for o in left) \
                    else "the session ended with part of the order unfilled"
                await _end_orders(c, left, C.OrderState.EXPIRED, reason=reason, sim_time=as_of)
                out["expired_orders"] += len(left)
                await finish_intent(c, intent, as_of=as_of, sim_time=as_of, why="the close")
    async with gw.pool.acquire() as c:
        async with c.transaction():
            acct = await c.fetchrow("SELECT account_id FROM autodesk.accounts WHERE tenant_id=$1 AND simulation_id=$2",
                                    tenant_id, simulation_id)
            if acct is not None:
                m = await mark_to_close(c, gw, tenant_id=tenant_id, account_id=acct["account_id"], session=session, as_of=as_of)
                out.update(marked_legs=m[0], stale_legs=m[1])
                await snapshot(c, tenant_id=tenant_id, account_id=acct["account_id"], session=session, as_of=as_of,
                               simulation_id=simulation_id)
    return out


async def mark_to_close(c, gw: ExecutionGateway, *, tenant_id: str, account_id: str, session: date, as_of: datetime) -> tuple[int, int]:
    """Mark every open leg at the session's close from the leg's own row. No row, or no trade: the last mark is kept and
    flagged stale (never shown as current)."""
    marked = stale = 0
    for leg in await positions.open_legs(c, tenant_id=tenant_id, account_id=account_id):
        ref = orders.leg_ref({"kind": leg["kind"], "underlying": leg["underlying"], "expiry": leg["expiry"],
                              "strike": leg["strike"]})
        bar = await gw.sim.bars.bar(ref, session, clock_session=session)
        if bar is None or not bar.traded or bar.close is None:
            await positions.mark_leg(c, position_id=leg["position_id"], leg=leg, mark=None,
                                     source=f"no trade in the {session} session; last mark kept", at=as_of, stale=True)
            stale += 1
        else:
            await positions.mark_leg(c, position_id=leg["position_id"], leg=leg, mark=bar.close,
                                     source=f"{bar.source} close", at=as_of)
            marked += 1
    return marked, stale


async def snapshot(c, *, tenant_id: str, account_id: str, session: date, as_of: datetime, simulation_id: Optional[str]) -> dict:
    v = await capital.balances(c, tenant_id, account_id)
    row = await c.fetchrow(
        """INSERT INTO autodesk.equity_snapshots (account_id, session_date, tenant_id, simulation_id, as_of, equity_rs,
               cash_balance_rs, used_margin_rs, reserved_rs, buying_power_rs, notional_rs, open_risk_rs, realized_gross_rs,
               fees_rs, unrealized_gross_rs, net_pnl_rs, stale_legs)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17)
           ON CONFLICT (account_id, session_date) DO UPDATE SET as_of=EXCLUDED.as_of, equity_rs=EXCLUDED.equity_rs,
               cash_balance_rs=EXCLUDED.cash_balance_rs, used_margin_rs=EXCLUDED.used_margin_rs,
               reserved_rs=EXCLUDED.reserved_rs, buying_power_rs=EXCLUDED.buying_power_rs, notional_rs=EXCLUDED.notional_rs,
               open_risk_rs=EXCLUDED.open_risk_rs, realized_gross_rs=EXCLUDED.realized_gross_rs, fees_rs=EXCLUDED.fees_rs,
               unrealized_gross_rs=EXCLUDED.unrealized_gross_rs, net_pnl_rs=EXCLUDED.net_pnl_rs,
               stale_legs=EXCLUDED.stale_legs RETURNING *""",
        account_id, session, tenant_id, simulation_id, as_of, v.equity_rs, v.cash_balance_rs, v.used_margin_rs,
        v.reserved_capital_rs, v.available_buying_power_rs, v.deployed_notional_rs, v.open_risk_rs, v.realized_gross_rs,
        v.fees_rs, v.unrealized_gross_rs, v.net_pnl_rs, len(v.stale_legs))
    return dict(row)


# ── live desk ─────────────────────────────────────────────────────────────────

async def live_tick(gw: ExecutionGateway, *, now: Optional[datetime] = None, tenant_id: Optional[str] = None) -> dict:
    """One pass of the live desk: submit validated intents, price working orders from FRESH quotes only, expire at the
    session close, mark open positions. No fresh quote means no fill: the order waits and tries again."""
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(IST).date()
    out = {"intents": 0, "fills": 0, "waiting": 0, "expired": 0, "marked": 0}
    if gw.live is None:
        return out
    async with gw.pool.acquire() as c:
        rows = [dict(r) for r in await c.fetch(
            """SELECT intent_id, tenant_id, session_date FROM autodesk.execution_intents WHERE simulation_id IS NULL
               AND status IN ('VALIDATED','SUBMITTED') AND ($1::text IS NULL OR tenant_id=$1) ORDER BY created_at""",
            tenant_id)]
    for r in rows:
        out["intents"] += 1
        iid, tenant_id, session = r["intent_id"], r["tenant_id"], r["session_date"]
        if now >= session_close_utc(session):
            async with gw.pool.acquire() as c:
                async with c.transaction():
                    intent = dict(await c.fetchrow("SELECT * FROM autodesk.execution_intents WHERE intent_id=$1 FOR UPDATE", iid))
                    left = [o for o in await orders.of_intent(c, iid) if o["state"] not in TERMINAL]
                    await _end_orders(c, left, C.OrderState.EXPIRED, reason="the session ended before the order filled", sim_time=None)
                    out["expired"] += len(left)
                    await finish_intent(c, intent, as_of=now, sim_time=None, why="the close")
            continue
        intent = await gw.submit(tenant_id=tenant_id, intent_id=iid, as_of=now)
        if intent["status"] != "SUBMITTED":
            continue
        async with gw.pool.acquire() as c:
            async with c.transaction():
                intent = dict(await c.fetchrow("SELECT * FROM autodesk.execution_intents WHERE intent_id=$1 FOR UPDATE", iid))
                working = [o for o in await orders.of_intent(c, iid) if o["state"] in ("OPEN", "PARTIALLY_FILLED")]
                if not working:
                    continue
                plan, body, _acc, pol, res = await _context(c, gw, intent)
                stop = await store.entries_stopped(c, tenant_id, None)
                if stop:
                    for o in working:
                        await orders.note_no_fill(c, o, "ENTRIES_STOPPED", f"STOP_NEW_ENTRIES is active ({stop['reason']})")
                    out["waiting"] += len(working)
                    continue
                if session != today or not all(in_fill_window(o["kind"], now) for o in working):
                    out["waiting"] += len(working)               # outside the fill window: no quote is read
                    continue
                answer = await gw.live.quotes.quotes([orders.leg_ref(o) for o in working], now)
                spec = intent["order_spec"]
                net = Decimal(spec["net_limit_rs"]) if spec.get("net_limit_rs") else None
                inval = orders.invalidation_of(plan["body"], len(body.legs))
                priced = gw.live.price(working, answer, now=now, net_limit=net, invalidation=inval)
                await _apply_priced(c, gw, intent, priced, plan=plan, body=body, policy=pol, res=res, at=now, sim_time=None,
                                    quotes=answer.quotes)
                out["fills"] += len(priced.fills)
                out["waiting"] += len(priced.rests)
                await finish_intent(c, intent, as_of=now, sim_time=None, why="filled or rejected")
    out["marked"] = await mark_live(gw, now=now, tenant_id=tenant_id)
    return out


async def mark_live(gw: ExecutionGateway, *, now: datetime, tenant_id: Optional[str] = None) -> int:
    """Mark open desk positions from fresh quotes. A leg with no fresh quote keeps its last mark, which is then shown as
    stale on read (reports.mark_age)."""
    if gw.live is None:
        return 0
    async with gw.pool.acquire() as c:
        legs = await positions.open_legs(c, tenant_id=tenant_id, desk_only=True)
    if not legs:
        return 0
    refs = [orders.leg_ref({"kind": lg["kind"], "underlying": lg["underlying"], "expiry": lg["expiry"], "strike": lg["strike"]})
            for lg in legs]
    answer = await gw.live.quotes.quotes(refs, now)
    n = 0
    async with gw.pool.acquire() as c:
        async with c.transaction():
            for lg, ref in zip(legs, refs):
                q = answer.quotes.get(ref.key)
                if check_quote(q, now) is None:
                    await positions.mark_leg(c, position_id=lg["position_id"], leg=lg, mark=q.ltp, source=q.ref, at=now)
                    n += 1
    return n


async def live_close(gw: ExecutionGateway, *, now: Optional[datetime] = None) -> int:
    """After the close: one snapshot per desk account that holds a position."""
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(IST).date()
    n = 0
    async with gw.pool.acquire() as c:
        accts = [dict(r) for r in await c.fetch("SELECT DISTINCT tenant_id, account_id FROM autodesk.trade_positions "
                                                "WHERE simulation_id IS NULL AND status='OPEN'")]
    for a in accts:
        async with gw.pool.acquire() as c:
            async with c.transaction():
                await snapshot(c, tenant_id=a["tenant_id"], account_id=a["account_id"], session=today, as_of=now, simulation_id=None)
                n += 1
    return n
