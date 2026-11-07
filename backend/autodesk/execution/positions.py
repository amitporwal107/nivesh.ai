"""Fills → positions (one per trade, one leg row per plan leg) and marks. A position exists only after a fill: an
acknowledgement never opens one (ARCH §17.2). Phase 2 positions stay OPEN; exits are Phase 3."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from .. import contracts as C
from .. import store
from .capital import rs

SIDE_OF = {"BUY": "LONG", "SELL": "SHORT"}


def unrealized(side: str, quantity: int, cost_value: Decimal, mark: Decimal) -> Decimal:
    """Long: what it is worth now less what it cost. Short: what was received less what it would cost back."""
    worth = mark * quantity
    return rs(worth - cost_value if side == "LONG" else cost_value - worth)


async def open_or_add(c, *, plan: dict, order: dict, qty: int, price: Decimal, value_rs: Decimal, charges_rs: Decimal,
                      margin_rs: Decimal, open_risk_rs: Decimal, capital_rs: Decimal, sector: str, fno: bool,
                      at: datetime, sim_time: Optional[datetime]) -> tuple[dict, bool]:
    """Apply one fill. Returns (position row, created). `open_risk_rs` and `capital_rs` are the position's new totals."""
    pos = await c.fetchrow("SELECT * FROM autodesk.trade_positions WHERE trade_id=$1 FOR UPDATE", plan["trade_id"])
    created = pos is None
    if created:
        pid = C.new_id("POS")
        pos = await c.fetchrow(
            """INSERT INTO autodesk.trade_positions (position_id, tenant_id, account_id, simulation_id, trade_id,
                   plan_version, instrument, strategy_type, status, open_risk_rs, capital_rs, margin_rs, sector, fno,
                   opened_at, sim_time)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,'OPEN',$9,$10,$11,$12,$13,$14,$15) RETURNING *""",
            pid, order["tenant_id"], order["account_id"], order["simulation_id"], plan["trade_id"], order["plan_version"],
            plan["instrument"], plan["strategy_type"], rs(open_risk_rs), rs(capital_rs), rs(margin_rs), sector, fno, at,
            sim_time)
        await store.emit(c, C.EventType.POSITION_OPENED, tenant_id=order["tenant_id"], producer="EXECUTION_GATEWAY",
                         account_id=order["account_id"], simulation_id=order["simulation_id"],
                         correlation_id=plan["trade_id"], sim_time=sim_time,
                         payload={"position_id": pid, "trade_id": plan["trade_id"], "instrument": plan["instrument"],
                                  "strategy_type": plan["strategy_type"]})
    else:
        pos = await c.fetchrow(
            """UPDATE autodesk.trade_positions SET open_risk_rs=$2, capital_rs=$3, margin_rs=margin_rs+$4, updated_at=now()
               WHERE position_id=$1 RETURNING *""", pos["position_id"], rs(open_risk_rs), rs(capital_rs), rs(margin_rs))
    side = SIDE_OF[order["side"]]
    leg = await c.fetchrow("SELECT * FROM autodesk.trade_position_legs WHERE position_id=$1 AND leg_id=$2",
                           pos["position_id"], order["leg_id"])
    if leg is None:
        await c.execute(
            """INSERT INTO autodesk.trade_position_legs (position_id, leg_id, kind, underlying, expiry, strike, side,
                   lot_size, quantity, avg_price, cost_value_rs, charges_rs, mark_price, mark_source, marked_at,
                   unrealized_rs)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,'the fill price',$14,0)""",
            pos["position_id"], order["leg_id"], order["kind"], order["underlying"], order["expiry"], order["strike"],
            side, order["lot_size"], qty, price, rs(value_rs), rs(charges_rs), price, at)
    else:
        q = leg["quantity"] + qty
        cost = leg["cost_value_rs"] + rs(value_rs)
        await c.execute(
            """UPDATE autodesk.trade_position_legs SET quantity=$3, avg_price=$4, cost_value_rs=$5,
                   charges_rs=charges_rs+$6, unrealized_rs=$7 WHERE position_id=$1 AND leg_id=$2""",
            pos["position_id"], order["leg_id"], q, cost / q, cost, rs(charges_rs),
            unrealized(side, q, cost, leg["mark_price"]))
    return dict(pos), created


async def mark_leg(c, *, position_id: str, leg: dict, mark: Optional[Decimal], source: str, at: datetime,
                   stale: bool = False) -> None:
    """A new mark, or (mark None) keep the last one and flag it stale: an old price is never shown as current."""
    if mark is None:
        await c.execute("""UPDATE autodesk.trade_position_legs SET mark_stale=true, mark_source=$3
                           WHERE position_id=$1 AND leg_id=$2""", position_id, leg["leg_id"], source)
        return
    await c.execute(
        """UPDATE autodesk.trade_position_legs SET mark_price=$3, mark_source=$4, marked_at=$5, mark_stale=$6,
               unrealized_rs=$7 WHERE position_id=$1 AND leg_id=$2""",
        position_id, leg["leg_id"], mark, source, at, stale,
        unrealized(leg["side"], leg["quantity"], leg["cost_value_rs"], mark))


async def open_legs(c, *, tenant_id: Optional[str] = None, account_id: Optional[str] = None,
                    desk_only: bool = False) -> list[dict]:
    q = ["""SELECT l.*, p.tenant_id, p.account_id, p.simulation_id, p.trade_id FROM autodesk.trade_position_legs l
            JOIN autodesk.trade_positions p USING (position_id) WHERE p.status='OPEN'"""]
    args: list = []
    if tenant_id is not None:
        args.append(tenant_id); q.append(f"AND p.tenant_id=${len(args)}")
    if account_id is not None:
        args.append(account_id); q.append(f"AND p.account_id=${len(args)}")
    if desk_only:
        q.append("AND p.simulation_id IS NULL")
    return [dict(r) for r in await c.fetch(
        " ".join(q) + " ORDER BY p.opened_at, p.position_id, l.leg_id", *args)]
