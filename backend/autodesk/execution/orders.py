"""Plan version → order spec, and the order state machine (PRD §11.3, PHASE2_DESIGN §5.3, §5.4)."""
from __future__ import annotations

from datetime import date, datetime
from decimal import ROUND_FLOOR, Decimal
from typing import Any, Optional

from .. import contracts as C
from .. import store
from ..control import sizing
from ..market.session_bars import LegRef
from . import costs
from .capital import rs
from .fill_model import PCT, TICK, FillParams, OrderView, on_tick

SIDE = {C.LegSide.LONG: "BUY", C.LegSide.SHORT: "SELL"}
COL_ALLOWED = {"filled_qty", "avg_fill_price", "reject_code", "reject_reason", "last_quote_ref", "last_no_fill_reason"}


def _down(px: Decimal) -> Decimal:
    return (px / TICK).to_integral_value(rounding=ROUND_FLOOR) * TICK


def _up(px: Decimal) -> Decimal:
    return -_down(-px)


def _limit(leg: C.PlanLeg, body: C.TradePlanBody, params: FillParams) -> Decimal:
    """One leg's limit, on the tick, never past the side the plan accepts (PHASE2_DESIGN §5.4)."""
    entry = body.entry or {}
    slip = Decimal(str(entry.get("max_slippage_pct") or "0.5")) / PCT
    buy = leg.side == C.LegSide.LONG
    ref = leg.ref_price
    if leg.kind in (C.InstrumentKind.CE, C.InstrumentKind.PE):
        d = params.option_limit_pct / PCT
        return _down(ref * (1 + d)) if buy else _up(ref * (1 - d))
    zone = entry.get("zone_high" if buy else "zone_low")
    base = entry.get("reference_price")
    if zone not in (None, "") and leg.kind == C.InstrumentKind.EQ:
        px = Decimal(str(zone))
    elif zone not in (None, "") and base not in (None, ""):          # a future keeps the zone's distance from its own price
        px = ref * Decimal(str(zone)) / Decimal(str(base))
    else:
        px = ref * (1 + slip) if buy else ref * (1 - slip)
    return _down(px) if buy else _up(px)


def build_spec(body: C.TradePlanBody, policy: C.PolicyBody, params: FillParams) -> dict:
    """What the approved version turns into. JSON-safe (strings), stored on the intent."""
    otype = str((body.entry or {}).get("order_type") or "LIMIT").upper()
    if otype not in ("LIMIT", "MARKET"):
        raise ValueError(f"unknown order type {otype}")
    basket = len(body.legs) > 1
    legs, commitment, cash_out, margin, charges = [], Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0")
    for lg in body.legs:
        kind = lg.kind.value
        side = SIDE[lg.side]
        limit: Optional[Decimal] = None
        if basket:
            order_type = "BASKET_LEG"
            px = lg.ref_price * (1 + params.basket_net_pct / PCT)
        elif otype == "MARKET":
            order_type = "MARKET"
            c = params.market_collar_pct[kind] / PCT
            px = lg.ref_price * (1 + c if side == "BUY" else 1 - c)
        else:
            order_type = "LIMIT"
            limit = _limit(lg, body, params)
            px = limit
        value = px * lg.quantity
        commitment += value
        charges += costs.charges(kind, side, rs(value))["total"]
        if lg.kind == C.InstrumentKind.FUT:
            margin += value * policy.futures_margin_pct / PCT
        elif not basket:
            cash_out += value if side == "BUY" else -value
        legs.append({"leg_id": lg.leg_id, "kind": kind, "underlying": lg.underlying,
                     "expiry": lg.expiry.isoformat() if lg.expiry else None,
                     "strike": str(lg.strike) if lg.strike is not None else None, "side": side, "lots": lg.lots,
                     "lot_size": lg.lot_size, "quantity": lg.quantity, "ref_price": str(lg.ref_price),
                     "order_type": order_type, "limit_price": str(limit) if limit is not None else None})
    net_ref = sum((lg.ref_price * lg.quantity * (1 if lg.side == C.LegSide.LONG else -1) for lg in body.legs
                   if lg.kind != C.InstrumentKind.FUT), Decimal("0"))
    net_limit = net_ref + abs(net_ref) * params.basket_net_pct / PCT if basket else None
    width = None
    if basket:
        terms = sizing.credit(body.legs)
        width = rs(terms["width_rs"]) if terms else None
        cash_out = net_limit
        margin += width or Decimal("0")
    needed = max(cash_out + margin + charges, Decimal("0"))
    return {"basket": basket, "plan_order_type": otype, "legs": legs,
            "net_ref_rs": str(rs(net_ref)), "net_limit_rs": str(rs(net_limit)) if net_limit is not None else None,
            "credit_width_rs": str(width) if width is not None else None,
            "funds": {"cash_out_rs": str(rs(cash_out)), "margin_rs": str(rs(margin)), "charges_rs": str(rs(charges)),
                      "needed_rs": str(rs(needed)), "basis": "worst acceptable prices; futures margin is an estimate"},
            "commitment_rs": str(rs(commitment))}


def spec_problems(spec: dict, params: FillParams) -> list[tuple[str, str]]:
    """Lot, tick and collar of the order spec (PRD §11.4 step 8–9): [(code, reason)]."""
    out = []
    for lg in spec["legs"]:
        if lg["quantity"] % lg["lot_size"] != 0:
            out.append(("LOT_SIZE", f"leg {lg['leg_id']}: {lg['quantity']} is not a multiple of the lot {lg['lot_size']}"))
        if lg["limit_price"] is None:
            continue
        lim, ref = Decimal(lg["limit_price"]), Decimal(lg["ref_price"])
        if not on_tick(lim):
            out.append(("TICK_SIZE", f"leg {lg['leg_id']}: limit {lim} is not on the {TICK} tick"))
        collar = params.market_collar_pct[lg["kind"]]
        if abs(lim / ref - 1) * PCT > collar:
            out.append(("COLLAR", f"leg {lg['leg_id']}: limit {lim} is more than {collar}% from the plan's price {ref}"))
    return out


def leg_ref(o: dict) -> LegRef:
    return LegRef(kind=o["kind"], underlying=o["underlying"], expiry=o.get("expiry"), strike=o.get("strike"))


def view(o: dict, invalidation: Optional[Decimal] = None) -> OrderView:
    return OrderView(key=leg_ref(o).key, kind=o["kind"], side=o["side"], order_type=o["order_type"],
                     quantity=o["quantity"], lot_size=o["lot_size"], ref_price=o["ref_price"],
                     filled_qty=o["filled_qty"], limit_price=o["limit_price"], invalidation=invalidation,
                     leg_id=o["leg_id"])


def invalidation_of(body: dict, n_legs: int) -> Optional[Decimal]:
    """The level a long single leg must not open through. A structure's loss is bounded by its legs, not by this level."""
    v = (body.get("invalidation") or {}).get("underlying_level")
    return Decimal(str(v)) if n_legs == 1 and v not in (None, "") else None


async def insert_orders(c, *, intent: dict, spec: dict, sim_time: Optional[datetime]) -> list[dict]:
    """One order per leg, CREATED then VALIDATED (the controls have passed), with its history."""
    out = []
    for lg in spec["legs"]:
        oid = C.new_id("ORD")
        row = dict(await c.fetchrow(
            """INSERT INTO autodesk.trade_orders (order_id, intent_id, tenant_id, account_id, simulation_id, trade_id,
                   plan_version, leg_id, kind, underlying, expiry, strike, side, lots, lot_size, quantity, order_type,
                   limit_price, ref_price, state, session_date, idempotency_key, sim_time)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,'CREATED',$20,$21,$22)
               RETURNING *""",
            oid, intent["intent_id"], intent["tenant_id"], intent["account_id"], intent["simulation_id"],
            intent["trade_id"], intent["plan_version"], lg["leg_id"], lg["kind"], lg["underlying"],
            _date(lg["expiry"]), Decimal(lg["strike"]) if lg["strike"] else None, lg["side"], lg["lots"],
            lg["lot_size"], lg["quantity"], lg["order_type"], Decimal(lg["limit_price"]) if lg["limit_price"] else None,
            Decimal(lg["ref_price"]), intent["session_date"], f"{intent['idempotency_key']}:{lg['leg_id']}", sim_time))
        await _history(c, row, None, C.OrderState.CREATED, "order written from the approved plan version", sim_time)
        out.append(await move(c, row, C.OrderState.VALIDATED, reason="every control passed", sim_time=sim_time))
    return out


def _date(v: Any) -> Optional[date]:
    return date.fromisoformat(v) if v else None


async def _history(c, order: dict, frm: Optional[C.OrderState], to: C.OrderState, reason: str,
                   sim_time: Optional[datetime], detail: Optional[dict] = None) -> None:
    await c.execute(
        """INSERT INTO autodesk.trade_order_events (order_id, tenant_id, from_state, to_state, reason, detail, sim_time)
           VALUES ($1,$2,$3,$4,$5,$6,$7)""",
        order["order_id"], order["tenant_id"], frm.value if frm else None, to.value, reason, detail or {}, sim_time)


async def move(c, order: dict, to: C.OrderState, *, reason: str = "", detail: Optional[dict] = None,
               sim_time: Optional[datetime] = None, **cols: Any) -> dict:
    """Move an order along ORDER_TRANSITIONS, with its history row and event in the same transaction."""
    frm = C.OrderState(order["state"])
    if to not in C.ORDER_TRANSITIONS[frm]:
        raise store.IllegalTransition(f"order {order['order_id']}: {frm.value} → {to.value} is not allowed")
    bad = set(cols) - COL_ALLOWED
    if bad:
        raise ValueError(f"unknown order columns: {sorted(bad)}")
    sets, args = ["state=$2", "updated_at=now()"], [order["order_id"], to.value]
    for k, v in cols.items():
        args.append(v); sets.append(f"{k}=${len(args)}")
    row = dict(await c.fetchrow(f"UPDATE autodesk.trade_orders SET {', '.join(sets)} WHERE order_id=$1 RETURNING *", *args))
    await _history(c, row, frm, to, reason, sim_time, detail)
    await store.emit(c, C.EventType.ORDER_STATE_CHANGED, tenant_id=order["tenant_id"], producer="EXECUTION_GATEWAY",
                     account_id=order["account_id"], simulation_id=order["simulation_id"],
                     correlation_id=order["trade_id"], sim_time=sim_time,
                     payload={"order_id": order["order_id"], "trade_id": order["trade_id"], "leg_id": order["leg_id"],
                              "from": frm.value, "to": to.value, "reason": reason,
                              "filled_qty": row["filled_qty"], "quantity": row["quantity"]})
    return row


async def note_no_fill(c, order: dict, code: str, reason: str, sim_time: Optional[datetime] = None) -> dict:
    """The order stays as it is: count the attempt and say why. A history row only when the reason changes."""
    text = f"{code}: {reason}"
    prev = order.get("last_no_fill_reason")
    row = dict(await c.fetchrow(
        """UPDATE autodesk.trade_orders SET attempts=attempts+1, last_no_fill_reason=$2, updated_at=now()
           WHERE order_id=$1 RETURNING *""", order["order_id"], text))
    if (prev or "").split(":")[0] != code:
        st = C.OrderState(order["state"])
        await _history(c, row, st, st, text, sim_time)
    return row


async def get_order(c, tenant_id: str, order_id: str, *, for_update: bool = False) -> dict:
    r = await c.fetchrow("SELECT * FROM autodesk.trade_orders WHERE order_id=$1 AND tenant_id=$2"
                         + (" FOR UPDATE" if for_update else ""), order_id, tenant_id)
    if r is None:
        raise store.NotFound(order_id)
    return dict(r)


async def of_intent(c, intent_id: str) -> list[dict]:
    return [dict(r) for r in await c.fetch(
        "SELECT * FROM autodesk.trade_orders WHERE intent_id=$1 ORDER BY leg_id", intent_id)]
