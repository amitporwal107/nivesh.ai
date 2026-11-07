"""Reconciliation (PHASE3_DESIGN §5.2) and UNKNOWN orders (§9).

Every invariant is a difference that must be 0.00; each run is stored in autodesk.reconciliation_runs (append-only). A
difference on a trade moves it to RECONCILIATION_REQUIRED and stops its automatic actions; a CLOSED trade whose checks are all
0.00 moves to SETTLED. A paper adapter has no external state, so an UNKNOWN order (the adapter raised before acknowledging it)
never worked: it ends EXPIRED with the reason, never resubmitted.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from .. import contracts as C
from .. import store
from ..execution import journal, orders
from ..execution.capital import balances

ZERO = Decimal("0")
PRODUCER = "TRADE_LIFECYCLE_MANAGER"


def _chk(name: str, diff: Decimal, detail: str) -> dict:
    return {"name": name, "difference_rs": str(Decimal(diff).quantize(Decimal("0.01"))), "ok": diff == 0, "detail": detail}


async def trade_checks(c, trade_id: str) -> list[dict]:
    """Per-trade invariants 2, 3 and 6."""
    led = await c.fetchval("SELECT COALESCE(sum(realized_gross_delta_rs),0) FROM autodesk.capital_ledger_entries WHERE trade_id=$1 "
                           "AND entry_type='REALIZED_PNL'", trade_id)
    recs = await c.fetchval("SELECT COALESCE(sum(realized_gross_rs),0) FROM autodesk.trade_exit_records WHERE trade_id=$1", trade_id)
    pos = await c.fetchval("SELECT COALESCE(sum(realized_gross_rs),0) FROM autodesk.trade_positions WHERE trade_id=$1", trade_id)
    out = [_chk("realized_ledger_vs_records", led - recs, f"ledger {led}, records {recs}"),
           _chk("realized_ledger_vs_position", led - pos, f"ledger {led}, position {pos}")]
    q = await c.fetchrow(
        """SELECT COALESCE(sum(abs(COALESCE(l.opened_qty,0) - l.closed_qty - l.quantity)),0) AS legs,
                  COALESCE(sum(abs(COALESCE(l.opened_qty,0) - COALESCE((SELECT sum(f.quantity) FROM autodesk.trade_fills f
                        JOIN autodesk.trade_orders o USING (order_id) WHERE o.trade_id=p.trade_id AND o.leg_id=l.leg_id
                        AND o.purpose='OPEN'),0))),0) AS opened,
                  COALESCE(sum(abs(l.closed_qty - COALESCE((SELECT sum(f.quantity) FROM autodesk.trade_fills f
                        JOIN autodesk.trade_orders o USING (order_id) WHERE o.trade_id=p.trade_id AND o.leg_id=l.leg_id
                        AND o.purpose='CLOSE'),0) - COALESCE((SELECT sum((x->>'quantity')::int) FROM autodesk.trade_exit_records r,
                        jsonb_array_elements(r.legs) x WHERE r.trade_id=p.trade_id AND r.how='settlement'
                        AND x->>'leg_id'=l.leg_id),0))),0) AS closed
           FROM autodesk.trade_positions p JOIN autodesk.trade_position_legs l USING (position_id) WHERE p.trade_id=$1""",
        trade_id)
    out.append(_chk("quantities", Decimal(q["legs"] + q["opened"] + q["closed"]),
                    f"opened − closed − held {q['legs']}, opened vs opening fills {q['opened']}, closed vs closing fills and "
                    f"settlements {q['closed']} (units)"))
    bad = await c.fetchval("""SELECT count(*) FROM autodesk.capital_reservations WHERE trade_id=$1 AND status<>'ACTIVE'
                              AND consumed_rs + released_rs <> amount_rs""", trade_id)
    out.append(_chk("reservations_closed", Decimal(bad), f"{bad} closed reservation(s) not fully consumed or released"))
    return out


async def account_checks(c, tenant_id: str, account_id: str) -> list[dict]:
    v = await balances(c, tenant_id, account_id)
    out = [_chk("equity", v.equity_rs - v.equity_from_positions_rs,
                f"equity from P&L {v.equity_rs}, cash + positions {v.equity_from_positions_rs}")]
    fees = await c.fetchrow(
        """SELECT (SELECT COALESCE(sum(charges_rs),0) FROM autodesk.trade_fills WHERE account_id=$1) AS fills,
                  (SELECT COALESCE(sum(charges_rs),0) FROM autodesk.trade_exit_records WHERE account_id=$1 AND how='settlement') AS settle""",
        account_id)
    out.append(_chk("fees", v.fees_rs - fees["fills"] - fees["settle"],
                    f"ledger {v.fees_rs}, fills {fees['fills']}, settlements {fees['settle']}"))
    acc = await store.get_account(c, tenant_id, account_id)
    flows = await c.fetchrow(
        """SELECT COALESCE(sum(CASE WHEN o.kind='FUT' THEN 0 WHEN f.side=$2 THEN -f.value_rs ELSE f.value_rs END - f.charges_rs),0) AS opening
           FROM autodesk.trade_fills f JOIN autodesk.trade_orders o USING (order_id) WHERE f.account_id=$1 AND o.purpose='OPEN'""",
        account_id, "BUY")
    closing = await c.fetchval("SELECT COALESCE(sum(cash_rs),0) FROM autodesk.trade_exit_records WHERE account_id=$1", account_id)
    expected = Decimal(str(acc["starting_capital_rs"])) + v.adjustments_rs + flows["opening"] + closing
    out.append(_chk("cash", v.cash_balance_rs - expected, f"ledger {v.cash_balance_rs}, from opening capital, fills and "
                                                          f"closings {expected}"))
    pos = await c.fetchrow("""SELECT COALESCE(sum(open_risk_rs),0) AS risk, COALESCE(sum(margin_rs),0) AS margin
                              FROM autodesk.trade_positions WHERE account_id=$1 AND status='OPEN'""", account_id)
    pend = await c.fetchrow("""SELECT COALESCE(sum(risk_rs - risk_moved_rs),0) AS risk FROM autodesk.capital_reservations
                               WHERE account_id=$1 AND status='ACTIVE'""", account_id)
    out.append(_chk("open_risk", v.open_risk_rs - pos["risk"], f"ledger {v.open_risk_rs}, open positions {pos['risk']}"))
    out.append(_chk("margin", v.used_margin_rs - pos["margin"], f"ledger {v.used_margin_rs}, open positions {pos['margin']}"))
    out.append(_chk("pending_risk", v.pending_risk_rs - pend["risk"], f"ledger {v.pending_risk_rs}, active reservations {pend['risk']}"))
    j = await c.fetchrow(
        """SELECT (SELECT count(*) FROM autodesk.trade_fills f JOIN autodesk.trade_orders o USING (order_id)
                   WHERE f.account_id=$1 AND o.purpose='OPEN') AS open_fills,
                  (SELECT count(*) FROM autodesk.trade_journal_entries WHERE account_id=$1 AND kind='FILL') AS open_rows,
                  (SELECT count(*) FROM autodesk.trade_fills f JOIN autodesk.trade_orders o USING (order_id)
                   WHERE f.account_id=$1 AND o.purpose='CLOSE') AS close_fills,
                  (SELECT count(*) FROM autodesk.trade_journal_entries WHERE account_id=$1 AND kind='CLOSING_FILL') AS close_rows,
                  (SELECT count(*) FROM autodesk.trade_positions WHERE account_id=$1 AND status='CLOSED') AS closed,
                  (SELECT count(*) FROM autodesk.trade_journal_entries WHERE account_id=$1 AND kind='CLOSURE') AS closure_rows,
                  (SELECT count(*) FROM autodesk.trade_exit_records WHERE account_id=$1 AND how='settlement') AS settles,
                  (SELECT count(*) FROM autodesk.trade_journal_entries WHERE account_id=$1 AND kind='SETTLEMENT') AS settle_rows""",
        account_id)
    jd = abs(j["open_fills"] - j["open_rows"]) + abs(j["close_fills"] - j["close_rows"]) + abs(j["closed"] - j["closure_rows"]) \
        + abs(j["settles"] - j["settle_rows"])
    out.append(_chk("journal", Decimal(jd), f"fills {j['open_fills']}/{j['open_rows']}, closing fills {j['close_fills']}/"
                                            f"{j['close_rows']}, closures {j['closed']}/{j['closure_rows']}, settlements "
                                            f"{j['settles']}/{j['settle_rows']} (records/journal rows)"))
    trades = [r["trade_id"] for r in await c.fetch("SELECT trade_id FROM autodesk.trade_positions WHERE account_id=$1", account_id)]
    total = ZERO
    for t in trades:
        for k in await trade_checks(c, t):
            total += abs(Decimal(k["difference_rs"]))
    out.append(_chk("trades", total, f"sum of per-trade differences over {len(trades)} trade(s)"))
    return out


async def run(c, *, tenant_id: str, account_id: str, simulation_id: Optional[str], session, moment: str,
              sim_time: Optional[datetime]) -> dict:
    checks = await account_checks(c, tenant_id, account_id)
    ok = all(k["ok"] for k in checks)
    await c.execute("""INSERT INTO autodesk.reconciliation_runs (tenant_id, account_id, simulation_id, session_date, moment, ok,
                           checks, sim_time) VALUES ($1,$2,$3,$4,$5,$6,$7,$8)""",
                    tenant_id, account_id, simulation_id, session, moment, ok, checks, sim_time)
    if not ok:
        await store.emit(c, C.EventType.RECONCILIATION_FAILED, tenant_id=tenant_id, producer=PRODUCER, account_id=account_id,
                         simulation_id=simulation_id, sim_time=sim_time,
                         payload={"moment": moment, "checks": [k for k in checks if not k["ok"]]})
    return {"ok": ok, "checks": checks}


async def settle_trade(c, pos: dict, *, session, sim_time) -> bool:
    """A CLOSED trade whose checks are all 0.00 becomes SETTLED; otherwise RECONCILIATION_REQUIRED (PRD §8.2)."""
    from .closure import move_state
    checks = await trade_checks(c, pos["trade_id"])
    ok = all(k["ok"] for k in checks)
    jb = dict(tenant_id=pos["tenant_id"], account_id=pos["account_id"], simulation_id=pos["simulation_id"],
              trade_id=pos["trade_id"], sim_time=sim_time)
    await journal.record(c, **jb, kind="RECONCILIATION", ref_id=f"{pos['position_id']}:closure",
                         summary="ledger, records, quantities and reservations agree to 0.00" if ok else
                                 "a difference was found: " + "; ".join(k["detail"] for k in checks if not k["ok"]),
                         data={"checks": checks})
    if ok:
        await c.execute("UPDATE autodesk.trade_positions SET settled_at=COALESCE($2, now()) WHERE position_id=$1",
                        pos["position_id"], sim_time)
        await move_state(c, pos, C.LifecycleState.SETTLED, reason="reconciled to 0.00", session=session, sim_time=sim_time)
        await store.emit(c, C.EventType.POSITION_SETTLED, tenant_id=pos["tenant_id"], producer=PRODUCER,
                         account_id=pos["account_id"], simulation_id=pos["simulation_id"], correlation_id=pos["trade_id"],
                         sim_time=sim_time, payload={"trade_id": pos["trade_id"], "position_id": pos["position_id"]})
    else:
        await move_state(c, pos, C.LifecycleState.RECONCILIATION_REQUIRED, reason="a reconciliation difference",
                         session=session, sim_time=sim_time, detail={"checks": checks})
    return ok


async def resolve_orders(c, os_: list[dict], *, sim_time) -> int:
    n = 0
    for o in os_:
        if o["state"] != C.OrderState.UNKNOWN.value:
            continue
        await orders.move(c, o, C.OrderState.EXPIRED, sim_time=sim_time,
                          reason="reconciled: the paper venue holds no record of this order; it never worked")
        n += 1
    return n


async def resolve_unknown(c, *, tenant_id: str, account_id: str, sim_time: Optional[datetime]) -> int:
    """Opening orders left UNKNOWN on this account: end them EXPIRED and finish their intent (releasing what it held)."""
    rows = [dict(r) for r in await c.fetch("SELECT * FROM autodesk.trade_orders WHERE tenant_id=$1 AND account_id=$2 AND state='UNKNOWN' "
                                           "FOR UPDATE", tenant_id, account_id)]
    if not rows:
        return 0
    n = await resolve_orders(c, rows, sim_time=sim_time)
    from ..execution.settle import finish_intent
    for iid in sorted({o["intent_id"] for o in rows}):
        intent = dict(await c.fetchrow("SELECT * FROM autodesk.execution_intents WHERE intent_id=$1", iid))
        if intent["action"] != C.CLOSE_ACTION:
            await finish_intent(c, intent, as_of=sim_time or datetime.now(timezone.utc), sim_time=sim_time,
                                why="an order the paper venue never acknowledged")
    return n
