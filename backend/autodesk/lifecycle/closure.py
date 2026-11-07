"""Closing fills and settlements -> fill rows, ledger, position legs, exit records, journal (PHASE3_DESIGN §5, §6).

Every amount is Decimal, rounded to the paisa. One closing UNIT (all legs of one closing intent, or one settlement) books:
  per leg   POSITION_FUNDS (cash: + sale of a long leg, − buy-back of a short leg, 0 for futures; notional − cost closed)
            FEES_BOOKED    (desk-cost-v2 on the closing side; brokerage once per order)
            REALIZED_PNL   (gross on the quantity closed; futures also move cash by it)
  per unit  MARGIN_RELEASED (margin and open risk of the closed fraction; everything left when the position closes)
The caller holds the transaction and the account lock. Narrative avoids the AD-92 words.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Optional

from .. import contracts as C
from .. import store
from ..execution import capital, costs, journal, orders
from ..execution import fill_model as fm
from ..execution.capital import rs
from ..execution.positions import unrealized

ZERO = Decimal("0")
PRODUCER = "TRADE_LIFECYCLE_MANAGER"
LS = C.LifecycleState
CLOSE_SIDE = {"LONG": "SELL", "SHORT": "BUY"}


async def move_state(c, pos: dict, to: C.LifecycleState, *, reason: str, session=None, sim_time=None,
                     detail: Optional[dict] = None) -> dict:
    """One lifecycle move along LIFECYCLE_TRANSITIONS, with its event row and event (PRD §8.2: explicit, validated, persisted)."""
    frm = C.LifecycleState(pos["lifecycle_state"])
    if frm == to:
        return pos
    if to not in C.LIFECYCLE_TRANSITIONS[frm]:
        raise store.IllegalTransition(f"position {pos['position_id']}: {frm.value} → {to.value} is not allowed")
    row = dict(await c.fetchrow("UPDATE autodesk.trade_positions SET lifecycle_state=$2, updated_at=now() WHERE position_id=$1 "
                                "RETURNING *", pos["position_id"], to.value))
    await c.execute(
        """INSERT INTO autodesk.trade_lifecycle_events (tenant_id, account_id, simulation_id, trade_id, position_id, from_state,
               to_state, reason, detail, session_date, sim_time) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)""",
        pos["tenant_id"], pos["account_id"], pos["simulation_id"], pos["trade_id"], pos["position_id"], frm.value, to.value,
        reason, detail or {}, session, sim_time)
    await store.emit(c, C.EventType.LIFECYCLE_STATE_CHANGED, tenant_id=pos["tenant_id"], producer=PRODUCER,
                     account_id=pos["account_id"], simulation_id=pos["simulation_id"], correlation_id=pos["trade_id"],
                     sim_time=sim_time, payload={"position_id": pos["position_id"], "trade_id": pos["trade_id"],
                                                 "from": frm.value, "to": to.value, "reason": reason})
    return row


async def first_state(c, pos: dict, *, reason: str, session=None, sim_time=None, detail: Optional[dict] = None) -> None:
    """The activation row (no from-state)."""
    await c.execute(
        """INSERT INTO autodesk.trade_lifecycle_events (tenant_id, account_id, simulation_id, trade_id, position_id, from_state,
               to_state, reason, detail, session_date, sim_time) VALUES ($1,$2,$3,$4,$5,NULL,$6,$7,$8,$9,$10)""",
        pos["tenant_id"], pos["account_id"], pos["simulation_id"], pos["trade_id"], pos["position_id"],
        pos["lifecycle_state"], reason, detail or {}, session, sim_time)


async def insert_fill(c, *, intent_id: str, order: dict, d: fm.Decision, at: datetime, sim_time: Optional[datetime]
                      ) -> tuple[str, Decimal, dict, Decimal]:
    """A SIMULATED fill row for a closing order. Returns (fill id, value, charges breakdown, fees)."""
    value = rs(d.price * d.qty)
    ch = costs.charges(order["kind"], order["side"], value, first_fill=order["filled_qty"] == 0)
    fees = rs(ch["total"])
    fill_id = C.new_id("FIL")
    await c.execute(
        """INSERT INTO autodesk.trade_fills (fill_id, order_id, intent_id, tenant_id, account_id, simulation_id, trade_id,
               leg_id, side, quantity, price, arrival_price, value_rs, spread_rs, slippage_rs, charges, charges_rs,
               cost_model, price_source, fill_model, latency_ms, fill_time, sim_time, session_date)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22,$23,$24)""",
        fill_id, order["order_id"], intent_id, order["tenant_id"], order["account_id"], order["simulation_id"],
        order["trade_id"], order["leg_id"], order["side"], d.qty, d.price, d.arrival or d.price, value, rs(d.spread_rs),
        rs(d.slippage_rs), {k: str(v) for k, v in ch.items()}, fees, costs.COST_MODEL, d.source, fm.VERSION, d.latency_ms,
        at + timedelta(milliseconds=d.latency_ms), sim_time, order["session_date"])
    new_filled = order["filled_qty"] + d.qty
    avg = ((order["avg_fill_price"] or ZERO) * order["filled_qty"] + d.price * d.qty) / new_filled
    to = C.OrderState.FILLED if new_filled >= order["quantity"] else C.OrderState.PARTIALLY_FILLED
    await orders.move(c, order, to, reason=f"{d.qty} closed at {d.price} ({d.source})", sim_time=sim_time,
                      detail={"fill_id": fill_id, "price": str(d.price), "qty": d.qty}, filled_qty=new_filled, avg_fill_price=avg)
    return fill_id, value, ch, fees


async def book_leg(c, *, pos: dict, leg: dict, qty: int, price: Decimal, value: Decimal, fees: Decimal, ref_type: str,
                   ref_id: str, sim_time: Optional[datetime], memo: str) -> dict:
    """Ledger and leg for `qty` units of one leg closed at `price` (a fill or a settlement). Returns the leg's result."""
    before = leg["quantity"]
    if qty <= 0 or qty > before:
        raise ValueError(f"leg {leg['leg_id']}: cannot close {qty} of {before}")
    cost_closed = leg["cost_value_rs"] if qty == before else rs(leg["cost_value_rs"] * qty / before)
    long = leg["side"] == "LONG"
    gross = rs(value - cost_closed if long else cost_closed - value)
    fut = leg["kind"] == "FUT"
    funds = ZERO if fut else (value if long else -value)
    base = dict(tenant_id=pos["tenant_id"], account_id=pos["account_id"], simulation_id=pos["simulation_id"],
                trade_id=pos["trade_id"], ref_type=ref_type, ref_id=ref_id, sim_time=sim_time)
    await capital.post(c, **base, entry_type=C.LedgerEntry.POSITION_FUNDS, cash=funds, notional=-cost_closed,
                       memo=f"{memo}: {qty} {leg['underlying']} {leg['kind']} at {price}")
    await capital.post(c, **base, entry_type=C.LedgerEntry.FEES_BOOKED, cash=-fees, fees=fees, memo=f"charges, {memo}")
    await capital.post(c, **base, entry_type=C.LedgerEntry.REALIZED_PNL, realized_gross=gross, cash=gross if fut else ZERO,
                       memo=f"gross result on {qty} closed: {gross}" + (" (futures settle it in cash)" if fut else ""))
    rem = before - qty
    rem_cost = leg["cost_value_rs"] - cost_closed
    await c.execute(
        """UPDATE autodesk.trade_position_legs SET quantity=$3, cost_value_rs=$4, closed_qty=closed_qty+$5,
               close_value_rs=close_value_rs+$6, closing_charges_rs=closing_charges_rs+$7, realized_gross_rs=realized_gross_rs+$8,
               unrealized_rs=$9 WHERE position_id=$1 AND leg_id=$2""",
        pos["position_id"], leg["leg_id"], rem, rem_cost, qty, value, fees, gross,
        unrealized(leg["side"], rem, rem_cost, leg["mark_price"]) if rem and leg["mark_price"] is not None else ZERO)
    return {"leg_id": leg["leg_id"], "kind": leg["kind"], "side": leg["side"], "quantity": qty, "price": str(price),
            "value_rs": str(value), "charges_rs": str(fees), "cost_closed_rs": str(cost_closed), "realized_gross_rs": str(gross),
            "cash_rs": str(funds + (gross if fut else ZERO) - fees)}


async def release_unit(c, *, pos: dict, fraction: Decimal, closes_all: bool, ref_id: str, sim_time, memo: str) -> dict:
    """Margin, open risk and capital of the closed fraction go back (all that is left when the position closes)."""
    p = dict(await c.fetchrow("SELECT * FROM autodesk.trade_positions WHERE position_id=$1 FOR UPDATE", pos["position_id"]))
    if closes_all:
        m, r, k = p["margin_rs"], p["open_risk_rs"], p["capital_rs"]
    else:
        m, r, k = rs(p["margin_rs"] * fraction), rs(p["open_risk_rs"] * fraction), rs(p["capital_rs"] * fraction)
    await capital.post(c, tenant_id=p["tenant_id"], account_id=p["account_id"], simulation_id=p["simulation_id"],
                       entry_type=C.LedgerEntry.MARGIN_RELEASED, ref_type="CLOSING", ref_id=ref_id, trade_id=p["trade_id"],
                       sim_time=sim_time, margin=-m, open_risk=-r, memo=f"{memo}: margin {m} and open risk {r} released")
    return dict(await c.fetchrow(
        """UPDATE autodesk.trade_positions SET margin_rs=margin_rs-$2, open_risk_rs=open_risk_rs-$3, capital_rs=capital_rs-$4,
               updated_at=now() WHERE position_id=$1 RETURNING *""", p["position_id"], m, r, k))


async def record(c, *, pos: dict, intent_id: Optional[str], reason: C.CloseReason, how: C.PriceHow, session, legs: list[dict],
                 fraction: Decimal, trigger_price=None, level=None, gapped=False, both_in_range=False, sim_time=None) -> dict:
    """The exit record of one closing unit, the position's totals, and CLOSED when nothing is left."""
    value = sum((Decimal(x["value_rs"]) for x in legs), ZERO)
    fees = sum((Decimal(x["charges_rs"]) for x in legs), ZERO)
    gross = sum((Decimal(x["realized_gross_rs"]) for x in legs), ZERO)
    cash = sum((Decimal(x["cash_rs"]) for x in legs), ZERO)
    rid = C.new_id("XRC")
    await c.execute(
        """INSERT INTO autodesk.trade_exit_records (record_id, tenant_id, account_id, simulation_id, trade_id, position_id,
               intent_id, reason, how, session_date, trigger_price, level, gapped, both_in_range, fraction, legs, value_rs,
               charges_rs, realized_gross_rs, cash_rs, sim_time)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21)""",
        rid, pos["tenant_id"], pos["account_id"], pos["simulation_id"], pos["trade_id"], pos["position_id"], intent_id,
        reason.value, how.value, session, trigger_price, level, gapped, both_in_range, fraction, legs, value, fees, gross, cash,
        sim_time)
    left = await c.fetchval("SELECT COALESCE(sum(quantity),0) FROM autodesk.trade_position_legs WHERE position_id=$1",
                            pos["position_id"])
    p = dict(await c.fetchrow(
        """UPDATE autodesk.trade_positions SET realized_gross_rs=realized_gross_rs+$2, closing_charges_rs=closing_charges_rs+$3,
               updated_at=now() WHERE position_id=$1 RETURNING *""", pos["position_id"], gross, fees))
    jb = dict(tenant_id=p["tenant_id"], account_id=p["account_id"], simulation_id=p["simulation_id"], trade_id=p["trade_id"],
              sim_time=sim_time)
    what = C.CLOSE_REASON_TEXT[reason]
    if how == C.PriceHow.SETTLEMENT:
        await journal.record(c, **jb, kind="SETTLEMENT", ref_id=rid,
                             summary=f"settled at contract expiry: gross {gross}, charges {fees}",
                             data={"legs": legs, "gross_rs": str(gross)})
    payload = {"position_id": p["position_id"], "trade_id": p["trade_id"], "record_id": rid, "reason": reason.value,
               "how": how.value, "realized_gross_rs": str(gross), "charges_rs": str(fees), "left": int(left)}
    if left == 0:
        p = dict(await c.fetchrow(
            """UPDATE autodesk.trade_positions SET status='CLOSED', closed_at=COALESCE($2, now()), close_reason=$3,
                   open_risk_rs=0, capital_rs=0, margin_rs=0, updated_at=now() WHERE position_id=$1 RETURNING *""",
            p["position_id"], sim_time, reason.value))
        entry_fees = await c.fetchval("SELECT COALESCE(sum(charges_rs),0) FROM autodesk.trade_position_legs WHERE position_id=$1",
                                      p["position_id"])
        net = p["realized_gross_rs"] - entry_fees - p["closing_charges_rs"]
        await journal.record(c, **jb, kind="CLOSURE", ref_id=p["position_id"],
                             summary=f"{p['instrument']} closed by {what}: gross {p['realized_gross_rs']}, all charges "
                                     f"{entry_fees + p['closing_charges_rs']}, net {net}",
                             data={"reason": reason.value, "gross_rs": str(p["realized_gross_rs"]), "net_rs": str(net)})
        await store.emit(c, C.EventType.POSITION_CLOSED, tenant_id=p["tenant_id"], producer=PRODUCER, account_id=p["account_id"],
                         simulation_id=p["simulation_id"], correlation_id=p["trade_id"], sim_time=sim_time,
                         payload={**payload, "net_rs": str(net)})
    else:
        await store.emit(c, C.EventType.POSITION_REDUCED, tenant_id=p["tenant_id"], producer=PRODUCER, account_id=p["account_id"],
                         simulation_id=p["simulation_id"], correlation_id=p["trade_id"], sim_time=sim_time, payload=payload)
    return {"record_id": rid, "position": p, "left": int(left), "gross_rs": gross, "charges_rs": fees}
