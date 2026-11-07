"""Capital ledger and atomic reservation (PRD §9.2, §9.4; ARCH §8.1, §8.2, §8.4).

Every balance is a sum over autodesk.capital_ledger_entries (append-only) plus the latest position marks. Nothing is
stored as "available" and updated in place. All amounts are Decimal, rounded to the paisa, half up, before posting.

Concurrency: `reserve` locks the account row (SELECT … FOR UPDATE) inside the caller's transaction, then derives the
balances. A second proposal waits for the first's commit and then sees its reservation, so two proposals can never
reserve the same funds. Functions take a connection; the caller holds the transaction.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Optional

from .. import contracts as C
from .. import store

ZERO = Decimal("0")
PAISA = Decimal("0.01")
BUCKET_COLUMNS = {"cash": "cash_delta_rs", "reserved": "reserved_delta_rs", "margin": "margin_delta_rs",
                  "notional": "notional_delta_rs", "open_risk": "open_risk_delta_rs",
                  "pending_risk": "pending_risk_delta_rs", "pending_commitment": "pending_commitment_delta_rs",
                  "realized_gross": "realized_gross_delta_rs", "fees": "fees_delta_rs"}


def rs(x: Any) -> Decimal:
    return Decimal(str(x)).quantize(PAISA, rounding=ROUND_HALF_UP)


class ReservationRefused(Exception):
    """A limit or the funds refused the reservation. Nothing was written."""

    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


# ── posting ───────────────────────────────────────────────────────────────────────────────────────────────────────────

async def post(c, *, tenant_id: str, account_id: str, simulation_id: Optional[str], entry_type: C.LedgerEntry,
               ref_type: str, ref_id: str, trade_id: Optional[str] = None, memo: str = "",
               sim_time: Optional[datetime] = None, **deltas: Any) -> int:
    """Append one ledger row. `deltas` are bucket names (cash=, reserved=, margin=, …), rounded to the paisa."""
    bad = set(deltas) - set(BUCKET_COLUMNS)
    if bad:
        raise ValueError(f"unknown ledger buckets: {sorted(bad)}")
    cols = [BUCKET_COLUMNS[k] for k in deltas]
    vals = [rs(v) for v in deltas.values()]
    base = [C.new_id("CAP"), tenant_id, account_id, simulation_id, entry_type.value, trade_id, ref_type, ref_id, memo,
            sim_time]
    names = ["entry_id", "tenant_id", "account_id", "simulation_id", "entry_type", "trade_id", "ref_type", "ref_id",
             "memo", "sim_time"] + cols
    marks = ",".join(f"${i + 1}" for i in range(len(names)))
    return await c.fetchval(
        f"INSERT INTO autodesk.capital_ledger_entries ({','.join(names)}) VALUES ({marks}) RETURNING seq",
        *base, *vals)


# ── balances ──────────────────────────────────────────────────────────────────────────────────────────────────────────

@dataclass
class CapitalView:
    """The separate measures of PRD §9.2. Notional, margin and maximum loss are never interchanged."""
    account_id: str
    starting_capital_rs: Decimal
    adjustments_rs: Decimal
    cash_balance_rs: Decimal
    used_margin_rs: Decimal
    available_cash_rs: Decimal
    reserved_capital_rs: Decimal
    available_buying_power_rs: Decimal
    deployed_notional_rs: Decimal
    open_risk_rs: Decimal
    pending_risk_rs: Decimal
    pending_order_commitment_rs: Decimal
    realized_gross_rs: Decimal
    fees_rs: Decimal
    net_realized_rs: Decimal
    unrealized_gross_rs: Decimal
    net_pnl_rs: Decimal
    equity_rs: Decimal
    position_market_value_rs: Decimal = ZERO
    stale_legs: list[dict] = field(default_factory=list)
    marks_as_of: Optional[datetime] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def equity_from_positions_rs(self) -> Decimal:
        return self.cash_balance_rs + self.position_market_value_rs

    def reconciliation(self) -> dict:
        """Equity two ways: capital + net P&L, and cash + what the positions are worth. They must agree."""
        return {"equity_from_pnl_rs": self.equity_rs, "equity_from_positions_rs": self.equity_from_positions_rs,
                "difference_rs": self.equity_rs - self.equity_from_positions_rs}


async def ledger_sums(c, tenant_id: str, account_id: str) -> dict[str, Decimal]:
    cols = ", ".join(f"COALESCE(sum({col}),0) AS {name}" for name, col in BUCKET_COLUMNS.items())
    row = await c.fetchrow(f"""SELECT {cols},
                                      COALESCE(sum(cash_delta_rs) FILTER (WHERE entry_type='MANUAL_ADJUSTMENT'),0) AS adj
                               FROM autodesk.capital_ledger_entries WHERE account_id=$1 AND tenant_id=$2""",
                           account_id, tenant_id)
    return dict(row)


async def balances(c, tenant_id: str, account_id: str) -> CapitalView:
    acc = await store.get_account(c, tenant_id, account_id)
    s = await ledger_sums(c, tenant_id, account_id)
    legs = await c.fetch(
        """SELECT l.position_id, l.leg_id, l.kind, l.side, l.quantity, l.mark_price, l.marked_at, l.mark_stale,
                  l.unrealized_rs, p.trade_id, l.underlying
           FROM autodesk.trade_position_legs l JOIN autodesk.trade_positions p USING (position_id)
           WHERE p.account_id=$1 AND p.tenant_id=$2 AND p.status='OPEN'""", account_id, tenant_id)
    unrealized, market_value = ZERO, ZERO
    stale: list[dict] = []
    as_of: Optional[datetime] = None
    for lg in legs:
        unrealized += lg["unrealized_rs"]
        mark = lg["mark_price"] if lg["mark_price"] is not None else ZERO
        if lg["kind"] == "FUT":                 # a future's cost is notional, not cash: only its P&L is worth anything
            market_value += lg["unrealized_rs"]
        else:
            sign = 1 if lg["side"] == "LONG" else -1
            market_value += sign * lg["quantity"] * mark
        if lg["mark_stale"]:
            stale.append({"trade_id": lg["trade_id"], "leg_id": lg["leg_id"], "underlying": lg["underlying"],
                          "marked_at": lg["marked_at"]})
        if lg["marked_at"] is not None and (as_of is None or lg["marked_at"] > as_of):
            as_of = lg["marked_at"]
    start = Decimal(str(acc["starting_capital_rs"]))
    net_realized = s["realized_gross"] - s["fees"]
    net = net_realized + unrealized
    available = s["cash"] - s["margin"]
    return CapitalView(account_id=account_id, starting_capital_rs=start, adjustments_rs=s["adj"],
                       cash_balance_rs=s["cash"], used_margin_rs=s["margin"], available_cash_rs=available,
                       reserved_capital_rs=s["reserved"], available_buying_power_rs=available - s["reserved"],
                       deployed_notional_rs=s["notional"], open_risk_rs=s["open_risk"],
                       pending_risk_rs=s["pending_risk"], pending_order_commitment_rs=s["pending_commitment"],
                       realized_gross_rs=s["realized_gross"], fees_rs=s["fees"], net_realized_rs=net_realized,
                       unrealized_gross_rs=unrealized, net_pnl_rs=net, equity_rs=start + s["adj"] + net,
                       position_market_value_rs=rs(market_value), stale_legs=stale, marks_as_of=as_of)


async def lock_account(c, tenant_id: str, account_id: str) -> dict:
    """Serialise this account's allocation state until the caller's transaction ends (ARCH §8.2 step 2)."""
    row = await c.fetchrow("SELECT * FROM autodesk.accounts WHERE account_id=$1 AND tenant_id=$2 FOR UPDATE",
                           account_id, tenant_id)
    if row is None:
        raise store.NotFound(account_id)
    return dict(row)


# ── reservation ───────────────────────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ReserveRequest:
    tenant_id: str
    account_id: str
    simulation_id: Optional[str]
    trade_id: str
    plan_version: int
    idempotency_key: str
    amount_rs: Decimal          # worst-acceptable funds: cash out at the limit + margin + estimated charges
    risk_rs: Decimal            # the plan's maximum loss
    commitment_rs: Decimal      # gross value of the orders at their limit
    capital_rs: Decimal         # what the risk engine compares with its position and sector limits
    instrument: str
    sector: str
    fno: bool
    expires_at: datetime
    as_of: datetime
    policy: C.PolicyBody


async def get_reservation(c, tenant_id: str, reservation_id: str, *, for_update: bool = False) -> dict:
    r = await c.fetchrow("SELECT * FROM autodesk.capital_reservations WHERE reservation_id=$1 AND tenant_id=$2"
                         + (" FOR UPDATE" if for_update else ""), reservation_id, tenant_id)
    if r is None:
        raise store.NotFound(reservation_id)
    return dict(r)


async def exposure(c, tenant_id: str, account_id: str) -> dict[str, Any]:
    """Capital committed by active reservations and open positions, in total, for F&O, and by sector."""
    rows = await c.fetch(
        """SELECT sector, fno, capital_rs * (1 - risk_moved_rs / NULLIF(risk_rs, 0)) AS capital_rs
           FROM autodesk.capital_reservations
           WHERE tenant_id=$1 AND account_id=$2 AND status='ACTIVE' AND risk_rs > 0
           UNION ALL
           SELECT sector, fno, capital_rs FROM autodesk.trade_positions
           WHERE tenant_id=$1 AND account_id=$2 AND status='OPEN'""", tenant_id, account_id)
    fno, sectors = ZERO, {}
    for r in rows:
        if r["fno"]:
            fno += r["capital_rs"]
        sectors[r["sector"]] = sectors.get(r["sector"], ZERO) + r["capital_rs"]
    return {"fno_capital_rs": fno, "sector_capital_rs": sectors}


async def reserve(c, req: ReserveRequest) -> dict:
    """Atomic reservation (ARCH §8.2). The caller holds the transaction. Same key: the same reservation, nothing new.
    Raises ReservationRefused with a code when funds or a limit say no; nothing is written then."""
    if not c.is_in_transaction():
        raise RuntimeError("reserve needs the caller's transaction")
    await lock_account(c, req.tenant_id, req.account_id)
    ex = await c.fetchrow("SELECT * FROM autodesk.capital_reservations WHERE tenant_id=$1 AND idempotency_key=$2",
                          req.tenant_id, req.idempotency_key)
    if ex is not None:
        return dict(ex)
    await release_overdue(c, req.tenant_id, req.account_id, req.as_of, sim_time=req.as_of if req.simulation_id else None)
    v = await balances(c, req.tenant_id, req.account_id)
    eq, pol = v.equity_rs, req.policy
    if req.amount_rs > v.available_buying_power_rs:
        raise ReservationRefused("INSUFFICIENT_FUNDS", f"needs {req.amount_rs}, buying power is "
                                                       f"{v.available_buying_power_rs}")
    lim = eq * pol.per_trade_risk_pct / 100
    if req.risk_rs > lim:
        raise ReservationRefused("PER_TRADE_RISK", f"maximum loss {req.risk_rs} is above {rs(lim)} "
                                                   f"({pol.per_trade_risk_pct}% of equity)")
    tot = v.open_risk_rs + v.pending_risk_rs + req.risk_rs
    lim = eq * pol.open_risk_pct / 100
    if tot > lim:
        raise ReservationRefused("OPEN_RISK_LIMIT", f"open and pending risk with this plan {tot} is above {rs(lim)} "
                                                    f"({pol.open_risk_pct}% of equity)")
    lim = eq * pol.position_pct / 100
    if req.capital_rs > lim:
        raise ReservationRefused("POSITION_LIMIT", f"capital {req.capital_rs} is above {rs(lim)} "
                                                   f"({pol.position_pct}% of equity)")
    exp = await exposure(c, req.tenant_id, req.account_id)
    sec = exp["sector_capital_rs"].get(req.sector, ZERO) + req.capital_rs
    lim = eq * pol.sector_pct / 100
    if sec > lim:
        raise ReservationRefused("SECTOR_LIMIT", f"{req.sector} capital with this plan {sec} is above {rs(lim)} "
                                                 f"({pol.sector_pct}% of equity)")
    if req.fno:
        fno = exp["fno_capital_rs"] + req.capital_rs
        lim = eq * pol.max_margin_utilization_pct / 100
        if fno > lim:
            raise ReservationRefused("MARGIN_LIMIT", f"F&O capital with this plan {fno} is above {rs(lim)} "
                                                     f"({pol.max_margin_utilization_pct}% of equity; estimate, not SPAN)")
    rid = C.new_id("RES")
    sim_time = req.as_of if req.simulation_id else None
    row = await c.fetchrow(
        """INSERT INTO autodesk.capital_reservations (reservation_id, tenant_id, account_id, simulation_id, trade_id,
               plan_version, status, amount_rs, risk_rs, commitment_rs, capital_rs, instrument, sector, fno,
               idempotency_key, expires_at, sim_time)
           VALUES ($1,$2,$3,$4,$5,$6,'ACTIVE',$7,$8,$9,$10,$11,$12,$13,$14,$15,$16) RETURNING *""",
        rid, req.tenant_id, req.account_id, req.simulation_id, req.trade_id, req.plan_version, rs(req.amount_rs),
        rs(req.risk_rs), rs(req.commitment_rs), rs(req.capital_rs), req.instrument, req.sector, req.fno,
        req.idempotency_key, req.expires_at, sim_time)
    await post(c, tenant_id=req.tenant_id, account_id=req.account_id, simulation_id=req.simulation_id,
               entry_type=C.LedgerEntry.CAPITAL_RESERVED, ref_type="RESERVATION", ref_id=rid, trade_id=req.trade_id,
               memo="funds set aside for the working orders", sim_time=sim_time, reserved=req.amount_rs,
               pending_risk=req.risk_rs, pending_commitment=req.commitment_rs)
    await store.emit(c, C.EventType.CAPITAL_RESERVED, tenant_id=req.tenant_id, producer="EXECUTION_GATEWAY",
                     account_id=req.account_id, simulation_id=req.simulation_id, correlation_id=req.trade_id,
                     sim_time=sim_time, payload={"reservation_id": rid, "trade_id": req.trade_id,
                                                 "plan_version": req.plan_version, "amount_rs": str(rs(req.amount_rs)),
                                                 "risk_rs": str(rs(req.risk_rs)), "expires_at": req.expires_at.isoformat()})
    return dict(row)


async def consume(c, res: dict, *, used_rs: Decimal, risk_moved_rs: Decimal, commitment_done_rs: Decimal,
                  ref_id: str, sim_time: Optional[datetime]) -> dict:
    """Fills convert the reservation (ARCH §8.2 step 7): reserved falls by what was used, pending risk becomes open
    risk. `used_rs` above what is left (a fill may cost more than estimated) takes only what is left."""
    left = res["amount_rs"] - res["consumed_rs"] - res["released_rs"]
    take = max(ZERO, min(rs(used_rs), left))
    await post(c, tenant_id=res["tenant_id"], account_id=res["account_id"], simulation_id=res["simulation_id"],
               entry_type=C.LedgerEntry.CAPITAL_RESERVATION_CONSUMED, ref_type="FILL", ref_id=ref_id,
               trade_id=res["trade_id"], memo="reservation converted by a fill", sim_time=sim_time, reserved=-take,
               pending_risk=-risk_moved_rs, open_risk=risk_moved_rs, pending_commitment=-commitment_done_rs)
    row = await c.fetchrow(
        """UPDATE autodesk.capital_reservations SET consumed_rs=consumed_rs+$2, risk_moved_rs=risk_moved_rs+$3,
               commitment_done_rs=commitment_done_rs+$4, updated_at=now() WHERE reservation_id=$1 RETURNING *""",
        res["reservation_id"], take, rs(risk_moved_rs), rs(commitment_done_rs))
    return dict(row)


async def close_reservation(c, res: dict, *, status: C.ReservationStatus, reason: str,
                            sim_time: Optional[datetime]) -> dict:
    """Release what is left and close the row (ARCH §8.2 step 8). consumed + released = amount afterwards. A row a fill
    used ends CONSUMED whatever `status` asks for, so its history stays readable."""
    if res["status"] != C.ReservationStatus.ACTIVE.value:
        return res
    left = res["amount_rs"] - res["consumed_rs"] - res["released_rs"]
    risk_left = res["risk_rs"] - res["risk_moved_rs"]
    commit_left = res["commitment_rs"] - res["commitment_done_rs"]
    final = C.ReservationStatus.CONSUMED if res["consumed_rs"] > 0 else status
    await post(c, tenant_id=res["tenant_id"], account_id=res["account_id"], simulation_id=res["simulation_id"],
               entry_type=C.LedgerEntry.CAPITAL_RESERVATION_RELEASED, ref_type="RESERVATION",
               ref_id=res["reservation_id"], trade_id=res["trade_id"], memo=reason, sim_time=sim_time, reserved=-left,
               pending_risk=-risk_left, pending_commitment=-commit_left)
    row = await c.fetchrow(
        """UPDATE autodesk.capital_reservations SET status=$2, released_rs=released_rs+$3, close_reason=$4,
               updated_at=now(), closed_at=now() WHERE reservation_id=$1 RETURNING *""",
        res["reservation_id"], final.value, left, reason)
    await store.emit(c, C.EventType.CAPITAL_RELEASED, tenant_id=res["tenant_id"], producer="EXECUTION_GATEWAY",
                     account_id=res["account_id"], simulation_id=res["simulation_id"], correlation_id=res["trade_id"],
                     sim_time=sim_time, payload={"reservation_id": res["reservation_id"], "trade_id": res["trade_id"],
                                                 "status": final.value, "released_rs": str(left),
                                                 "consumed_rs": str(res["consumed_rs"]), "reason": reason})
    return dict(row)


async def release_overdue(c, tenant_id: str, account_id: str, as_of: datetime, *,
                          sim_time: Optional[datetime] = None) -> int:
    """Reservations past their expiry with no working order give their funds back (a stopped process leaves them)."""
    rows = await c.fetch(
        """SELECT r.* FROM autodesk.capital_reservations r
           WHERE r.tenant_id=$1 AND r.account_id=$2 AND r.status='ACTIVE' AND r.expires_at <= $3
             AND NOT EXISTS (SELECT 1 FROM autodesk.execution_intents i JOIN autodesk.trade_orders o USING (intent_id)
                             WHERE i.reservation_id = r.reservation_id
                               AND o.state NOT IN ('FILLED','CANCELLED','REJECTED','EXPIRED'))
           ORDER BY r.created_at FOR UPDATE OF r""", tenant_id, account_id, as_of)
    for r in rows:
        await close_reservation(c, dict(r), status=C.ReservationStatus.EXPIRED,
                                reason="validity ended before the funds were used", sim_time=sim_time)
    return len(rows)
