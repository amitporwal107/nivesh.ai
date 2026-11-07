"""Daily, weekly and drawdown limits measured on the ledger and the session snapshots (PRD §8.5; PHASE3_DESIGN §8).

No second P&L: equity is capital.balances() (ledger + marks); references are the account's equity_snapshots.
  daily     equity − the previous session's snapshot equity (opening capital if none), as % of that reference
  weekly    equity − the last snapshot before the IST week (Monday) began
  drawdown  (running peak of the snapshots and now − equity) ÷ peak
Actions: a daily breach refuses new intents for that session and the next; a weekly breach until the week ends; a drawdown
breach activates SUSPEND_ACCOUNT for the account (a person lifts it). Closings are never blocked by a limit.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

from .. import contracts as C
from .. import store
from ..execution.capital import balances, rs
from . import controls

ZERO = Decimal("0")
L = C.LossLimit


def _pct(loss: Decimal, ref: Decimal) -> Decimal:
    return (loss / ref * 100).quantize(Decimal("0.001")) if ref > 0 else ZERO


async def _snapshots(c, account_id: str) -> list[dict]:
    return [dict(r) for r in await c.fetch("SELECT session_date, equity_rs FROM autodesk.equity_snapshots WHERE account_id=$1 "
                                           "ORDER BY session_date", account_id)]


def measure_from(snaps: list[dict], start: Decimal, session: date, equity: Decimal, pol: C.PolicyBody) -> dict:
    """The three measures as of `session` with equity `equity`. Pure."""
    before = [s for s in snaps if s["session_date"] < session]
    ref_d = before[-1]["equity_rs"] if before else start
    monday = session - timedelta(days=session.weekday())
    wk = [s for s in snaps if s["session_date"] < monday]
    ref_w = wk[-1]["equity_rs"] if wk else start
    peak = max([start, equity] + [s["equity_rs"] for s in snaps if s["session_date"] <= session])
    out = {}
    for name, ref, lim in ((L.DAILY, ref_d, pol.daily_loss_pct), (L.WEEKLY, ref_w, pol.weekly_loss_pct),
                           (L.DRAWDOWN, peak, pol.max_drawdown_pct)):
        loss = max(ref - equity, ZERO)
        pct = _pct(loss, ref)
        out[name.value] = {"limit_pct": str(lim), "reference_rs": str(rs(ref)), "equity_rs": str(rs(equity)),
                           "loss_rs": str(rs(loss)), "loss_pct": str(pct), "breached": pct >= lim and loss > 0,
                           "basis": {"daily": "previous session's snapshot", "weekly": "last snapshot before the week began",
                                     "drawdown": "running peak of the snapshots"}[name.value]}
    return out


async def _policy(c, tenant_id: str, account_id: str) -> tuple[dict, C.PolicyBody]:
    acc = await store.get_account(c, tenant_id, account_id)
    pol = C.PolicyBody.model_validate((await store.get_policy(c, tenant_id, acc["policy_id"]))["body"])
    return acc, pol


async def current(c, *, tenant_id: str, account_id: str, session: date) -> dict:
    acc, pol = await _policy(c, tenant_id, account_id)
    v = await balances(c, tenant_id, account_id)
    snaps = await _snapshots(c, account_id)
    start = Decimal(str(acc["starting_capital_rs"])) + v.adjustments_rs
    m = measure_from(snaps, start, session, v.equity_rs, pol)
    blocks = await entry_blocks(c, tenant_id=tenant_id, account_id=account_id, session=session, as_of=None,
                                live=acc["simulation_id"] is None)
    return {"account_id": account_id, "session_date": session.isoformat(), "measures": m,
            "blocks": [{"control": n, "code": k, "detail": d} for n, k, d in blocks],
            "marks_stale_legs": len(v.stale_legs)}


async def evaluate(c, *, tenant_id: str, account_id: str, session: date, sim_time: Optional[datetime]) -> dict:
    """After a session snapshot: measure; announce a breach once per limit and session; drawdown suspends the account."""
    acc, pol = await _policy(c, tenant_id, account_id)
    snaps = await _snapshots(c, account_id)
    today = next((s for s in snaps if s["session_date"] == session), None)
    if today is None:
        return {}
    v = await balances(c, tenant_id, account_id)
    m = measure_from(snaps, Decimal(str(acc["starting_capital_rs"])) + v.adjustments_rs, session, today["equity_rs"], pol)
    for name, x in m.items():
        if not x["breached"]:
            continue
        seen = await c.fetchval("""SELECT 1 FROM autodesk.events WHERE account_id=$1 AND event_type=$2
                                   AND payload->>'limit'=$3 AND payload->>'session_date'=$4 LIMIT 1""",
                                account_id, C.EventType.LIMIT_BREACHED.value, name, session.isoformat())
        if seen:
            continue
        await store.emit(c, C.EventType.LIMIT_BREACHED, tenant_id=tenant_id, producer="RISK_LIMITS", account_id=account_id,
                         simulation_id=acc["simulation_id"], sim_time=sim_time,
                         payload={"limit": name, "session_date": session.isoformat(), **x,
                                  "action": "SUSPEND_ACCOUNT" if name == L.DRAWDOWN.value else "new intents refused"})
        if name == L.DRAWDOWN.value:
            await controls.set_control(c, tenant_id=tenant_id, control=C.LifecycleControl.SUSPEND_ACCOUNT, scope=account_id,
                                       active=True, actor="RISK_LIMITS",
                                       reason=f"drawdown {x['loss_pct']}% reached the {x['limit_pct']}% limit on {session}")
    return {k: {"loss_pct": x["loss_pct"], "breached": x["breached"]} for k, x in m.items()}


async def entry_blocks(c, *, tenant_id: str, account_id: str, session: date, as_of: Optional[datetime],
                       live: bool) -> list[tuple[str, str, str]]:
    """Loss limits that refuse a new intent for `session`. Daily: a breach at the previous session's close (and, live, today's
    equity against it). Weekly: a breach at any close of this IST week, or at the previous session's close."""
    acc, pol = await _policy(c, tenant_id, account_id)
    snaps = await _snapshots(c, account_id)
    start = Decimal(str(acc["starting_capital_rs"]))
    before = [s for s in snaps if s["session_date"] < session]
    out: list[tuple[str, str, str]] = []
    if before:
        prev = before[-1]
        m = measure_from(snaps, start, prev["session_date"], prev["equity_rs"], pol)
        if m[L.DAILY.value]["breached"]:
            out.append(("daily_loss", C.LOSS_LIMIT_CODE[L.DAILY],
                        f"the {prev['session_date']} session lost {m['daily']['loss_pct']}% (limit {pol.daily_loss_pct}%): "
                        f"no new intent this session"))
        monday = session - timedelta(days=session.weekday())
        weekly_hit = m[L.WEEKLY.value]["breached"]
        why = f"{m['weekly']['loss_pct']}% at the {prev['session_date']} close"
        for s in before:
            if s["session_date"] >= monday and not weekly_hit:
                mw = measure_from(snaps, start, s["session_date"], s["equity_rs"], pol)
                if mw[L.WEEKLY.value]["breached"]:
                    weekly_hit, why = True, f"{mw['weekly']['loss_pct']}% at the {s['session_date']} close"
        if weekly_hit:
            out.append(("weekly_loss", C.LOSS_LIMIT_CODE[L.WEEKLY],
                        f"the week lost {why} (limit {pol.weekly_loss_pct}%): no new intent until the week ends"))
    if live:
        v = await balances(c, tenant_id, account_id)
        m = measure_from(snaps, start, session, v.equity_rs, pol)
        if m[L.DAILY.value]["breached"] and not any(k == C.LOSS_LIMIT_CODE[L.DAILY] for _n, k, _d in out):
            out.append(("daily_loss", C.LOSS_LIMIT_CODE[L.DAILY],
                        f"today's loss {m['daily']['loss_pct']}% reached the {pol.daily_loss_pct}% limit"))
    return out
