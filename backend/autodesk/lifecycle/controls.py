"""Emergency controls beyond STOP_NEW_ENTRIES, close requests, and withdrawing pending openings (PRD §10.4; PHASE3_DESIGN §7).

None of them cancels a protective closing or removes a level. Tenant-wide controls (scope '*') act on desk accounts only;
account-scoped ones act on any account, including a simulation's (that is how the drawdown limit acts in a replay)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from .. import contracts as C
from .. import store

PRODUCER = "TRADE_LIFECYCLE_MANAGER"
LC = C.LifecycleControl


async def set_control(c, *, tenant_id: str, control: C.LifecycleControl, scope: str, active: bool, reason: str,
                      actor: str) -> dict:
    """Idempotent: setting the state it already has changes and records nothing."""
    await c.execute("SELECT pg_advisory_xact_lock(hashtext($1))", f"lifecycle_control:{tenant_id}:{control.value}:{scope}")
    cur = await c.fetchrow("SELECT * FROM autodesk.lifecycle_controls WHERE tenant_id=$1 AND control=$2 AND scope=$3",
                           tenant_id, control.value, scope)
    if cur is not None and cur["active"] == active:
        return {**dict(cur), "changed": False}
    if cur is None and not active:
        return {"tenant_id": tenant_id, "control": control.value, "scope": scope, "active": False, "changed": False}
    row = await c.fetchrow(
        """INSERT INTO autodesk.lifecycle_controls (tenant_id, control, scope, active, reason, changed_by, changed_at)
           VALUES ($1,$2,$3,$4,$5,$6,now())
           ON CONFLICT (tenant_id, control, scope) DO UPDATE SET active=EXCLUDED.active, reason=EXCLUDED.reason,
               changed_by=EXCLUDED.changed_by, changed_at=EXCLUDED.changed_at RETURNING *""",
        tenant_id, control.value, scope, active, reason, actor)
    acc = await c.fetchrow("SELECT simulation_id FROM autodesk.accounts WHERE account_id=$1", scope)
    await store.emit(c, C.EventType.LIFECYCLE_CONTROL_CHANGED, tenant_id=tenant_id, producer=actor,
                     account_id=scope if acc is not None else None, simulation_id=acc["simulation_id"] if acc else None,
                     payload={"control": control.value, "scope": scope, "active": active, "reason": reason})
    for p in await c.fetch("""SELECT p.tenant_id, p.account_id, p.simulation_id, p.trade_id FROM autodesk.trade_positions p
                              WHERE p.tenant_id=$1 AND p.status='OPEN' AND (p.account_id=$2 OR ($2='*' AND p.simulation_id IS NULL)
                                    OR p.strategy_type=$2)""", tenant_id, scope):
        from ..execution import journal
        await journal.record(c, tenant_id=p["tenant_id"], account_id=p["account_id"], simulation_id=p["simulation_id"],
                             trade_id=p["trade_id"], kind="CONTROL",
                             ref_id=f"{control.value}:{scope}:{'on' if active else 'off'}:{row['changed_at'].isoformat()}",
                             summary=f"{control.value} {'activated' if active else 'lifted'} by {actor}: {reason}",
                             data={"control": control.value, "scope": scope, "active": active})
    return {**dict(row), "changed": True}


async def list_controls(c, tenant_id: str) -> list[dict]:
    return [dict(r) for r in await c.fetch("SELECT * FROM autodesk.lifecycle_controls WHERE tenant_id=$1 ORDER BY control, scope",
                                           tenant_id)]


async def _active(c, tenant_id: str, control: C.LifecycleControl, scopes: list[str]) -> Optional[dict]:
    r = await c.fetchrow("""SELECT * FROM autodesk.lifecycle_controls WHERE tenant_id=$1 AND control=$2 AND active
                            AND scope = ANY($3::text[]) ORDER BY changed_at DESC LIMIT 1""", tenant_id, control.value, scopes)
    return dict(r) if r else None


def _scopes(account: dict) -> list[str]:
    return [account["account_id"]] + (["*"] if account.get("simulation_id") is None else [])


async def entry_blocks(c, *, tenant_id: str, account: dict, strategy: str) -> list[tuple[str, str, str]]:
    out = []
    sc = _scopes(account)
    for ctl, code in ((LC.SUSPEND_ACCOUNT, "ACCOUNT_SUSPENDED"), (LC.REDUCE_ONLY, "REDUCE_ONLY")):
        r = await _active(c, tenant_id, ctl, sc)
        if r:
            out.append((ctl.value.lower(), code, f"{ctl.value} is active ({r['reason']})"))
    r = await _active(c, tenant_id, LC.SUSPEND_STRATEGY, [strategy])
    if r and account.get("simulation_id") is None:            # tenant-wide: desk accounts only
        out.append(("suspend_strategy", "STRATEGY_SUSPENDED", f"{strategy} is suspended ({r['reason']})"))
    return out


async def modifications_suspended(c, pos: dict) -> bool:
    acc = {"account_id": pos["account_id"], "simulation_id": pos["simulation_id"]}
    return await _active(c, pos["tenant_id"], LC.SUSPEND_AUTOMATED_MODIFICATIONS, _scopes(acc)) is not None


async def close_request_for(c, pos: dict) -> Optional[dict]:
    """A pending request to close the whole position, or REDUCE_ONLY on its account (a risk-control closing)."""
    r = await c.fetchrow("SELECT * FROM autodesk.close_requests WHERE trade_id=$1 AND status='PENDING'", pos["trade_id"])
    if r is not None:
        return dict(r)
    acc = {"account_id": pos["account_id"], "simulation_id": pos["simulation_id"]}
    ro = await _active(c, pos["tenant_id"], LC.REDUCE_ONLY, _scopes(acc))
    if ro is not None:
        return {"trade_id": pos["trade_id"], "reason": C.CloseReason.RISK_CONTROL.value, "note": f"REDUCE_ONLY: {ro['reason']}",
                "synthetic": True}
    return None


async def request_close(c, *, pos: dict, reason: C.CloseReason, note: str, actor: str) -> dict:
    row = await c.fetchrow(
        """INSERT INTO autodesk.close_requests (trade_id, tenant_id, account_id, reason, note, requested_by, status)
           VALUES ($1,$2,$3,$4,$5,$6,'PENDING') ON CONFLICT (trade_id) DO NOTHING RETURNING *""",
        pos["trade_id"], pos["tenant_id"], pos["account_id"], reason.value, note, actor)
    if row is None:
        return {**dict(await c.fetchrow("SELECT * FROM autodesk.close_requests WHERE trade_id=$1", pos["trade_id"])),
                "changed": False}
    return {**dict(row), "changed": True}


async def request_done(c, trade_id: str) -> None:
    await c.execute("UPDATE autodesk.close_requests SET status='DONE', done_at=now() WHERE trade_id=$1 AND status='PENDING'",
                    trade_id)


async def cancel_pending_openings(gw, *, tenant_id: str, reason: str, as_of: Optional[datetime] = None) -> list[str]:
    """Withdraw every working opening order of the tenant's desk accounts. Closing orders are never touched."""
    as_of = as_of or datetime.now(timezone.utc)
    async with gw.pool.acquire() as c:
        ids = [r["order_id"] for r in await c.fetch(
            """SELECT order_id FROM autodesk.trade_orders WHERE tenant_id=$1 AND simulation_id IS NULL AND purpose=$2
               AND state IN ('VALIDATED','OPEN','PARTIALLY_FILLED') ORDER BY created_at""",
            tenant_id, C.OrderPurpose.OPEN.value)]
    done: list[str] = []
    for oid in ids:
        try:
            await gw.withdraw(tenant_id=tenant_id, order_id=oid, as_of=as_of)
            done.append(oid)
        except store.Conflict:          # a sibling leg's withdrawal ended it already
            continue
    return done
