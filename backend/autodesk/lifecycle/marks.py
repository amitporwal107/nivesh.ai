"""The live desk's final mark of the day (owner rule: live → Kite close → exchange EOD; PHASE3_DESIGN §10.2).

Phase 2 snapshots at 15:31 from the last live marks, but cash in F&O stocks stops at 15:15, the closing auction ends about 15:35
and F&O trades to 15:40, so that mark is provisional.
  final_mark      15:41 IST: one quote read for every open desk leg; a fresh answer marks it (KITE_CLOSE), otherwise the last
                  live mark stays (LIVE_LAST). The snapshot records its basis.
  eod_correction  after the exchange's files land (F&O 22:45 IST): each leg's exchange close for the session; where it differs
                  the leg is re-marked (EXCHANGE_EOD), a MARK journal row names both sources, the snapshot is rewritten and the old
                  one kept in equity_snapshot_revisions. A missing exchange row changes nothing and says so.
"""
from __future__ import annotations

import json
from datetime import datetime, time as dtime, timezone
from typing import Optional

from .. import contracts as C
from .. import store
from ..execution import journal, positions
from ..execution.settle import _leg_ref, snapshot
from ..market import calendar
from ..market.live_quotes import check_quote
from ..market.view import IST, DataUnavailable

FINAL_MARK_IST = dtime(15, 41)
EOD_CORRECTION_IST = dtime(22, 50)


def _session_today(now: datetime):
    d = now.astimezone(IST).date()
    try:
        return d if calendar.is_session(d) else None
    except calendar.CalendarUnavailable:
        return None


async def _accounts(c) -> list[dict]:
    return [dict(r) for r in await c.fetch("SELECT DISTINCT tenant_id, account_id FROM autodesk.trade_positions "
                                           "WHERE simulation_id IS NULL AND status='OPEN'")]


async def final_mark(gw, *, now: Optional[datetime] = None) -> dict:
    now = now or datetime.now(timezone.utc)
    day = _session_today(now)
    out = {"accounts": 0, "kite_close": 0, "live_last": 0}
    if day is None:
        return out
    async with gw.pool.acquire() as c:
        accts = await _accounts(c)
        legs = await positions.open_legs(c, desk_only=True)
    answer = await gw.live.quotes.quotes([_leg_ref(lg) for lg in legs], now) if gw.live is not None and legs else None
    for a in accts:
        async with gw.pool.acquire() as c:
            async with c.transaction():
                fresh = stale = 0
                for lg in [x for x in legs if x["account_id"] == a["account_id"]]:
                    q = answer.quotes.get(_leg_ref(lg).key) if answer is not None else None
                    if q is not None and check_quote(q, now) is None:
                        await positions.mark_leg(c, position_id=lg["position_id"], leg=lg, mark=q.ltp, at=now,
                                                 source=f"Kite close (quote after the session) {q.ref}")
                        fresh += 1
                    else:
                        stale += 1
                basis = "KITE_CLOSE" if fresh and not stale else "LIVE_LAST"
                await snapshot(c, tenant_id=a["tenant_id"], account_id=a["account_id"], session=day, as_of=now, simulation_id=None)
                await c.execute("UPDATE autodesk.equity_snapshots SET mark_basis=$3 WHERE account_id=$1 AND session_date=$2",
                                a["account_id"], day, basis)
                out["accounts"] += 1
                out["kite_close"] += fresh
                out["live_last"] += stale
    return out


async def eod_correction(gw, *, now: Optional[datetime] = None, bars=None) -> dict:
    """`bars`: a SessionBarSource over the exchange's published rows (the lifecycle manager's eod_bars by default)."""
    now = now or datetime.now(timezone.utc)
    day = _session_today(now)
    bars = bars or getattr(gw.lifecycle, "eod_bars", None)
    out = {"accounts": 0, "corrected_legs": 0, "missing_rows": 0}
    if day is None or bars is None:
        return out
    async with gw.pool.acquire() as c:
        accts = await _accounts(c)
    for a in accts:
        async with gw.pool.acquire() as c:
            async with c.transaction():
                old = await c.fetchrow("SELECT * FROM autodesk.equity_snapshots WHERE account_id=$1 AND session_date=$2",
                                       a["account_id"], day)
                changed = 0
                for lg in await positions.open_legs(c, account_id=a["account_id"], desk_only=True):
                    try:
                        b = await bars.bar(_leg_ref(lg), day, clock_session=day)
                    except DataUnavailable:
                        b = None
                    if b is None or not b.traded or b.close is None:
                        out["missing_rows"] += 1
                        continue
                    if lg["mark_price"] != b.close:
                        await positions.mark_leg(c, position_id=lg["position_id"], leg=lg, mark=b.close, at=now,
                                                 source=f"{b.source} close (exchange EOD)")
                        await journal.record(c, tenant_id=a["tenant_id"], account_id=a["account_id"], simulation_id=None,
                                             trade_id=lg["trade_id"], kind="MARK", ref_id=f"{lg['position_id']}:{lg['leg_id']}:{day}:eod",
                                             sim_time=None,
                                             summary=f"leg {lg['leg_id']} mark for {day} corrected from {lg['mark_price']} "
                                                     f"({lg['mark_source']}) to the exchange close {b.close}",
                                             data={"from": str(lg["mark_price"]), "to": str(b.close), "old_source": lg["mark_source"]})
                        changed += 1
                if old is None:
                    continue
                new = await snapshot(c, tenant_id=a["tenant_id"], account_id=a["account_id"], session=day, as_of=now,
                                     simulation_id=None)
                await c.execute("UPDATE autodesk.equity_snapshots SET mark_basis='EXCHANGE_EOD' WHERE account_id=$1 AND session_date=$2",
                                a["account_id"], day)
                await c.execute(
                    """INSERT INTO autodesk.equity_snapshot_revisions (account_id, session_date, tenant_id, simulation_id, old_basis,
                           new_basis, old_row, new_row) VALUES ($1,$2,$3,NULL,$4,'EXCHANGE_EOD',$5,$6)""",
                    a["account_id"], day, a["tenant_id"], old["mark_basis"], json.loads(json.dumps(dict(old), default=str)),
                    json.loads(json.dumps(new, default=str)))
                if changed:
                    await store.emit(c, C.EventType.MARK_CORRECTED, tenant_id=a["tenant_id"], producer="TRADE_LIFECYCLE_MANAGER",
                                     account_id=a["account_id"], payload={"session_date": day.isoformat(), "legs": changed})
                out["accounts"] += 1
                out["corrected_legs"] += changed
    return out
