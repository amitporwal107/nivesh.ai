"""The Trade Lifecycle Manager (PRD §8; PHASE3_DESIGN §3–§7, §10). Deterministic; not an agent.

Simulation, wired by execution/settle.py when the gateway carries a lifecycle:
  sim_open        09:15 before openings: close requests, carried closings, gaps and objectives passed at the open
  sim_activate    after fills: positions with a completed opening get their exit state (from the plan and the actual fills)
  sim_close       15:30 after openings settle, before marks: the whole row -> level / objective / holding period / pre-expiry /
                  expiry settlement; then the trail for the next session
  sim_after_close after the snapshot: loss limits, reconciliation run
Live desk (settle.live_tick): live_pass on the tick's single quote read.

Every closing is a paper intent (action CLOSE) with one order per leg on the account's paper adapter, priced by
lifecycle/pricing.py from real rows or fresh quotes, booked by lifecycle/closure.py. A closing that cannot be priced does not
happen: it stays pending, flagged, and is tried again (next OPEN in a simulation, next fresh quote on the desk).
"""
from __future__ import annotations

import logging
from dataclasses import replace
from datetime import date, datetime, time as dtime, timedelta, timezone
from decimal import Decimal
from typing import Any, Awaitable, Callable, Optional

from services import exit_rules as XR

from .. import contracts as C
from .. import store
from ..execution import adapters as ad
from ..execution import capital, journal, orders
from ..execution import fill_model as fm
from ..execution.capital import rs
from ..market import calendar
from ..market.live_quotes import check_quote, in_fill_window
from ..market.session_bars import LegRef
from ..market.view import IST, DataUnavailable
from . import closure, controls, limits, pricing, recon
from . import rules as RL

log = logging.getLogger(__name__)
ZERO = Decimal("0")
LS = C.LifecycleState
H = C.PriceHow
R = C.CloseReason
PRODUCER = closure.PRODUCER
History = Callable[[str, datetime, int], Awaitable[list[dict]]]
LATE_IST = dtime(15, 0)      # live: holding-period and pre-expiry closings from this time of the due session


def _setup_from(d: dict) -> RL.Setup:
    return RL.Setup(trigger_key=d["trigger_key"], trigger_basis=d["trigger_basis"], side=d["side"], ratio=Decimal(d["ratio"]),
                    level=Decimal(d["level"]) if d.get("level") is not None else None, objectives=d["objectives"],
                    max_hold=d.get("max_hold"), trail=tuple(d["trail"]) if d.get("trail") else None, trend=d.get("trend"),
                    pre_expiry_sessions=d.get("pre_expiry_sessions"), entry_trigger_price=Decimal(d["entry_trigger_price"]),
                    structure=bool(d["structure"]), notes=list(d.get("notes") or []))


def _ref(key: Optional[str]) -> Optional[LegRef]:
    if not key:
        return None
    parts = key.split(":")
    if parts[0] == "EQ":
        return LegRef("EQ", parts[1])
    if parts[0] == "FUT":
        return LegRef("FUT", parts[1], date.fromisoformat(parts[2]))
    return LegRef(parts[0], parts[1], date.fromisoformat(parts[2]), Decimal(parts[3]))


def _leg_ref(lg: dict) -> LegRef:
    return LegRef(kind=lg["kind"], underlying=lg["underlying"], expiry=lg.get("expiry"), strike=lg.get("strike"))


async def _pre_expiry_session(expiry: date, start: date, n: int) -> tuple[date, str]:
    try:
        days = await calendar.sessions_between(start, expiry)
        basis = "exchange sessions"
    except Exception as e:  # noqa: BLE001 — stated in the exit state; it is a date, never a price
        days = [start + timedelta(days=i) for i in range((expiry - start).days + 1)
                if (start + timedelta(days=i)).weekday() < 5]
        basis = f"weekdays (holiday list unavailable: {type(e).__name__})"
    if not days:
        return start, basis
    return (days[-1 - n] if len(days) > n else days[0]), basis


class LifecycleManager:
    def __init__(self, pool, *, params: fm.FillParams = fm.DEFAULT_PARAMS, history: Optional[History] = None,
                 eod_bars: Any = None):
        self.pool, self.params, self.history = pool, params, history
        self.eod_bars = eod_bars        # live desk: the exchange's published rows (trail, sessions held, EOD correction)
        self.history_reads: list[tuple[str, str, int]] = []     # (symbol, as_of, bars) published before the clock

    # ── reading ──────────────────────────────────────────────────────────────────────────────────────────────────

    async def _bar(self, gw, ref: LegRef, session: date):
        """The clock session's row, or (None, why). The reader refuses any other session (LookAheadError propagates)."""
        try:
            b = await gw.sim.bars.bar(ref, session, clock_session=session)
        except DataUnavailable as e:
            return None, f"the data platform did not answer ({e})"
        if b is None:
            return None, "the exchange has no row for it in this session"
        return b, ""

    async def _open_positions(self, c, tenant_id: str, account_id: str) -> list[dict]:
        return [dict(r) for r in await c.fetch(
            """SELECT p.*, x.trade_id AS has_state FROM autodesk.trade_positions p
               LEFT JOIN autodesk.trade_exit_state x USING (trade_id)
               WHERE p.tenant_id=$1 AND p.account_id=$2 AND p.status='OPEN' ORDER BY p.opened_at, p.position_id""",
            tenant_id, account_id)]

    async def _legs(self, c, position_id: str) -> list[dict]:
        return [dict(r) for r in await c.fetch(
            "SELECT * FROM autodesk.trade_position_legs WHERE position_id=$1 ORDER BY leg_id", position_id)]

    async def _xs(self, c, trade_id: str) -> Optional[dict]:
        r = await c.fetchrow("SELECT * FROM autodesk.trade_exit_state WHERE trade_id=$1 FOR UPDATE", trade_id)
        return dict(r) if r else None

    # ── activation (PRD §8.3) ────────────────────────────────────────────────────────────────────────────────────

    async def activate(self, gw, c, pos: dict, *, session: date, as_of: datetime, sim_time: Optional[datetime],
                       filled_at_open: bool) -> dict:
        """Exit state from the exact approved plan version and the actual fills. Reads only what the open allows."""
        plan = await store.get_plan(c, pos["tenant_id"], pos["trade_id"], pos["plan_version"])
        body = plan["body"]
        legs = await self._legs(c, pos["position_id"])
        und = legs[0]["underlying"]
        fut_prev = und_prev = und_open = None
        reads: list[str] = []
        if gw.sim is not None and pos["simulation_id"]:
            if any(lg["kind"] != "EQ" for lg in legs):
                ub, why = await self._bar(gw, LegRef("EQ", und), session)
                if ub is not None:
                    und_prev, und_open = ub.prev_close, ub.open           # both known at the open
                else:
                    reads.append(f"underlying row: {why}")
                if len(legs) == 1 and legs[0]["kind"] == "FUT":
                    fb, why = await self._bar(gw, _leg_ref(legs[0]), session)
                    fut_prev = fb.prev_close if fb is not None else None
                    if fb is None:
                        reads.append(f"future row: {why}")
        else:
            und_open = None
        s = RL.setup(body, legs, fut_prev_close=fut_prev, und_prev_close=und_prev, und_open=und_open)
        notes = list(s.notes) + reads
        warmup: list[dict] = []
        if s.trail and s.trigger_key and self.history is not None:
            try:
                warmup = await self.history(und, as_of, s.trail[1] + 1)
                self.history_reads.append((und, as_of.isoformat(), len(warmup)))
            except Exception as e:  # noqa: BLE001 — the trail then seeds itself from the sessions held, as exit-rules-v1 does
                notes.append(f"published history for the ATR was not available ({type(e).__name__}); the trail seeds itself")
        rules = RL.make_rules(s, 0)
        st = RL.start_state(s, rules, session=session, warmup=warmup)
        expiries = sorted({lg["expiry"] for lg in legs if lg.get("expiry")})
        pre = None
        if s.pre_expiry_sessions is not None and expiries:
            pre, basis = await _pre_expiry_session(expiries[0], session, s.pre_expiry_sessions)
            notes.append(f"closing session before expiry {expiries[0]}: {pre} ({s.pre_expiry_sessions} sessions before, on {basis})")
        first = session if filled_at_open else session + timedelta(days=1)
        await c.execute(
            """INSERT INTO autodesk.trade_exit_state (trade_id, position_id, tenant_id, account_id, simulation_id, trigger_key,
                   trigger_basis, side, level_ratio, rules, state, objectives, next_objective, first_step_session,
                   pre_expiry_session, notes)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,0,$13,$14,$15) ON CONFLICT (trade_id) DO NOTHING""",
            pos["trade_id"], pos["position_id"], pos["tenant_id"], pos["account_id"], pos["simulation_id"], s.trigger_key,
            s.trigger_basis, s.side, s.ratio, {"setup": s.to_json(), "versions": {"rules": XR.VERSION,
                                                                                  "trail": XR.TRAIL_ATR_VERSION if s.trail else None,
                                                                                  "trend": XR.TREND_EMA_VERSION if s.trend else None,
                                                                                  "fill": fm.VERSION}},
            RL.state_to_json(st), s.objectives, first, pre, notes)
        await closure.first_state(c, pos, reason="managed from its confirmed fills", session=session, sim_time=sim_time,
                                  detail={"trigger": s.trigger_key, "level": str(s.level) if s.level else None})
        lvl = f"invalidation level {s.level} on {s.trigger_key}" if s.level is not None else "no invalidation level"
        objs = ", ".join(f"{o['level']} ({Decimal(o['fraction']) * 100:.0f}%)" for o in s.objectives) or "none"
        await journal.record(c, tenant_id=pos["tenant_id"], account_id=pos["account_id"], simulation_id=pos["simulation_id"],
                             trade_id=pos["trade_id"], kind="LIFECYCLE", ref_id=f"{pos['position_id']}:activated", sim_time=sim_time,
                             summary=f"managed from {session}: {lvl}; objectives {objs}; holding {s.max_hold or '—'} sessions"
                                     + (f"; closing session before expiry {pre}" if pre else "")
                                     + (f"; trail {s.trail[0]:g} × ATR{s.trail[1]}" if s.trail else ""),
                             data={"setup": s.to_json(), "notes": notes})
        await store.emit(c, C.EventType.POSITION_ACTIVATED, tenant_id=pos["tenant_id"], producer=PRODUCER,
                         account_id=pos["account_id"], simulation_id=pos["simulation_id"], correlation_id=pos["trade_id"],
                         sim_time=sim_time, payload={"position_id": pos["position_id"], "trade_id": pos["trade_id"],
                                                     "trigger": s.trigger_key, "level": str(s.level) if s.level else None})
        return await self._xs(c, pos["trade_id"])

    async def sim_activate(self, gw, *, tenant_id: str, account_id: str, session: date, as_of: datetime,
                           filled_at_open: bool) -> int:
        n = 0
        async with self.pool.acquire() as c:
            ids = [r["trade_id"] for r in await c.fetch(
                """SELECT p.trade_id FROM autodesk.trade_positions p WHERE p.tenant_id=$1 AND p.account_id=$2 AND p.status='OPEN'
                   AND NOT EXISTS (SELECT 1 FROM autodesk.trade_exit_state x WHERE x.trade_id=p.trade_id)
                   AND NOT EXISTS (SELECT 1 FROM autodesk.execution_intents i WHERE i.trade_id=p.trade_id
                                   AND i.status IN ('CREATED','VALIDATED','SUBMITTED'))
                   ORDER BY p.opened_at, p.trade_id""", tenant_id, account_id)]
        for tid in ids:
            async with self.pool.acquire() as c:
                async with c.transaction():
                    await capital.lock_account(c, tenant_id, account_id)
                    pos = dict(await c.fetchrow("SELECT * FROM autodesk.trade_positions WHERE trade_id=$1 FOR UPDATE", tid))
                    await self.activate(gw, c, pos, session=session, as_of=as_of, sim_time=as_of if pos["simulation_id"] else None,
                                        filled_at_open=filled_at_open)
                    n += 1
        return n

    # ── simulation: OPEN ─────────────────────────────────────────────────────────────────────────────────────────

    async def sim_open(self, gw, *, tenant_id: str, simulation_id: str, account_id: str, session: date, as_of: datetime,
                       seed: int) -> dict:
        """Before the session's openings: requests and controls, carried closings, then gaps / objectives passed at the open."""
        out = {"closings": 0, "closed": 0, "waiting": 0, "unknown_resolved": 0}
        async with self.pool.acquire() as c:
            async with c.transaction():
                out["unknown_resolved"] = await recon.resolve_unknown(c, tenant_id=tenant_id, account_id=account_id,
                                                                      sim_time=as_of)
            positions = [p for p in await self._open_positions(c, tenant_id, account_id) if p["has_state"]]
        for p in positions:
            async with self.pool.acquire() as c:
                async with c.transaction():
                    await capital.lock_account(c, tenant_id, account_id)
                    pos = dict(await c.fetchrow("SELECT * FROM autodesk.trade_positions WHERE trade_id=$1 FOR UPDATE", p["trade_id"]))
                    if pos["status"] != "OPEN":
                        continue
                    xs = await self._xs(c, pos["trade_id"])
                    r = await self._open_one(gw, c, pos, xs, session=session, as_of=as_of, seed=seed)
                    for k in out:
                        out[k] += r.get(k, 0)
        return out

    async def _open_one(self, gw, c, pos: dict, xs: dict, *, session: date, as_of: datetime, seed: int) -> dict:
        s = _setup_from(xs["rules"]["setup"])
        st = RL.state_from_json(xs["state"])
        legs = await self._legs(c, pos["position_id"])
        req = await controls.close_request_for(c, pos)
        d: Optional[RL.Decision] = None
        qty: Optional[dict] = None
        if req is not None:
            d = RL.Decision(reason=C.CloseReason(req["reason"]), how=H.OPEN, fraction=Decimal("1"), detail=req["note"])
        elif xs["pending"]:
            pend = xs["pending"]
            d = RL.Decision(reason=C.CloseReason(pend["reason"]), how=H.OPEN, fraction=Decimal("1"),
                            objective_index=pend.get("objective_index"), detail=f"carried from {pend.get('since')}")
            qty = {k: int(v) for k, v in (pend.get("qty") or {}).items()}
        elif s.trigger_key and session >= xs["first_step_session"] and not st.closed:
            tb, why = await self._bar(gw, _ref(s.trigger_key), session)
            if tb is None or tb.open is None or not tb.traded:
                await self._note(c, pos, xs, f"{session} open: the trigger row could not be read ({why or 'no trade'}); "
                                             f"nothing decided at the open", session=session)
                return {}
            d = RL.at_open(s, st, xs["next_objective"], tb.open, session)      # sees the open only
        if d is None:
            return {}
        return await self._execute(gw, c, pos, xs, s, st, legs, d, session=session, at=as_of, sim_time=as_of, seed=seed,
                                   qty=qty, request=req)

    # ── simulation: CLOSE ────────────────────────────────────────────────────────────────────────────────────────

    async def sim_close(self, gw, *, tenant_id: str, simulation_id: str, account_id: str, session: date, as_of: datetime,
                        seed: int) -> dict:
        out = {"closings": 0, "closed": 0, "waiting": 0, "settled": 0, "stepped": 0, "level_moves": 0}
        async with self.pool.acquire() as c:
            positions = [p for p in await self._open_positions(c, tenant_id, account_id) if p["has_state"]]
        for p in positions:
            async with self.pool.acquire() as c:
                async with c.transaction():
                    await capital.lock_account(c, tenant_id, account_id)
                    pos = dict(await c.fetchrow("SELECT * FROM autodesk.trade_positions WHERE trade_id=$1 FOR UPDATE", p["trade_id"]))
                    if pos["status"] != "OPEN":
                        continue
                    xs = await self._xs(c, pos["trade_id"])
                    r = await self._close_one(gw, c, pos, xs, session=session, as_of=as_of, seed=seed)
                    for k in out:
                        out[k] += r.get(k, 0)
        return out

    async def _close_one(self, gw, c, pos: dict, xs: dict, *, session: date, as_of: datetime, seed: int) -> dict:
        s = _setup_from(xs["rules"]["setup"])
        st = RL.state_from_json(xs["state"])
        legs = await self._legs(c, pos["position_id"])
        expiring = any(lg.get("expiry") == session and lg["quantity"] > 0 for lg in legs)
        if xs["pending"]:
            if expiring:                                    # a contract that expires is settled, not carried
                return await self._settle(gw, c, pos, xs, legs, session=session, sim_time=as_of)
            return {}                                       # a decided closing waits for the next open
        if session < xs["first_step_session"] and not expiring:
            return {}
        frozen = await controls.modifications_suspended(c, pos)
        if s.trigger_key:
            tb, why = await self._bar(gw, _ref(s.trigger_key), session)
            if tb is None or not tb.traded or tb.high is None or tb.low is None:
                if expiring:
                    return await self._settle(gw, c, pos, xs, legs, session=session, sim_time=as_of)
                await self._note(c, pos, xs, f"{session}: the trigger row could not be used ({why or 'no trade'}); the levels "
                                             f"stay in force and this session is not counted", session=session)
                return {}
        else:
            tb = None
        try:
            step = RL.at_close(s, st, xs["next_objective"], tb, session, expired=expiring, freeze_trail=frozen)
        except XR.IncompleteBar as e:
            await self._note(c, pos, xs, f"{session}: {e}", session=session)
            return {}
        out = {"stepped": 1}
        if st.stop != step.state.stop and not step.state.closed:
            out["level_moves"] = 1
            await self._level_moved(c, pos, st, step.state, session=session, sim_time=as_of)
        d, then = step.decision, step.then
        if d is None and xs["pre_expiry_session"] and session >= xs["pre_expiry_session"] and not expiring:
            d = RL.Decision(reason=R.PRE_EXPIRY, how=H.CLOSE, fraction=Decimal("1"),
                            detail=f"{s.pre_expiry_sessions} sessions before the earliest expiry")
        await self._save_state(c, xs, step.state, session=session)
        xs = await self._xs(c, pos["trade_id"])
        if d is None:
            return out
        if d.how == H.SETTLEMENT:
            r = await self._settle(gw, c, pos, xs, legs, session=session, sim_time=as_of)
            return {**out, **r}
        r = await self._execute(gw, c, pos, xs, s, step.state, legs, d, session=session, at=as_of, sim_time=as_of, seed=seed)
        for k, v in r.items():
            out[k] = out.get(k, 0) + v
        if expiring and r.get("waiting"):                   # could not close on expiry day: settle at the exchange's data
            pos = dict(await c.fetchrow("SELECT * FROM autodesk.trade_positions WHERE trade_id=$1", pos["trade_id"]))
            r3 = await self._settle(gw, c, pos, await self._xs(c, pos["trade_id"]), await self._legs(c, pos["position_id"]),
                                    session=session, sim_time=as_of)
            for k, v in r3.items():
                out[k] = out.get(k, 0) + v
            return out
        if then is not None and r.get("closings"):
            pos = dict(await c.fetchrow("SELECT * FROM autodesk.trade_positions WHERE trade_id=$1", pos["trade_id"]))
            if pos["status"] == "OPEN":
                xs = await self._xs(c, pos["trade_id"])
                r2 = await self._execute(gw, c, pos, xs, s, step.state, await self._legs(c, pos["position_id"]), then,
                                         session=session, at=as_of, sim_time=as_of, seed=seed)
                for k, v in r2.items():
                    out[k] = out.get(k, 0) + v
        return out

    async def sim_after_close(self, gw, *, tenant_id: str, simulation_id: Optional[str], account_id: str, session: date,
                              as_of: datetime) -> dict:
        async with self.pool.acquire() as c:
            async with c.transaction():
                lim = await limits.evaluate(c, tenant_id=tenant_id, account_id=account_id, session=session,
                                            sim_time=as_of if simulation_id else None)
                rc = await recon.run(c, tenant_id=tenant_id, account_id=account_id, simulation_id=simulation_id,
                                     session=session, moment="session close", sim_time=as_of if simulation_id else None)
        return {"limits": lim, "reconciliation_ok": rc["ok"]}

    # ── one closing unit ─────────────────────────────────────────────────────────────────────────────────────────

    async def _execute(self, gw, c, pos: dict, xs: dict, s: RL.Setup, st: XR.State, legs: list[dict], d: RL.Decision, *,
                       session: date, at: datetime, sim_time: Optional[datetime], seed: int,
                       qty: Optional[dict] = None, quotes: Optional[dict] = None, request: Optional[dict] = None) -> dict:
        """Closing intent + one order per leg + pricing + booking, all in the caller's transaction. All legs or none."""
        live = quotes is not None
        open_legs = [lg for lg in legs if lg["quantity"] > 0]
        if not open_legs:
            return {}
        if live:     # no intent until every leg has a fresh quote: a closing waits without leaving orders behind
            missing = [lg["leg_id"] for lg in open_legs if check_quote(quotes.get(_leg_ref(lg).key), at) is not None]
            if missing:
                if not xs["pending"]:
                    await self._set_pending(c, xs, d, {lg["leg_id"]: lg["quantity"] for lg in open_legs} if qty is None else qty,
                                            session, why=f"no fresh quote for leg(s) {', '.join(missing)}")
                    await self._flag(c, pos, "QUOTE_STALE", f"closing waits for a fresh quote of leg(s) {', '.join(missing)}")
                return {"waiting": 1}
        if qty is None:
            want = {lg["leg_id"]: RL.lots_to_close(lg["quantity"], lg["lot_size"], d.fraction) for lg in open_legs}
        else:
            want = {lg["leg_id"]: min(int(qty.get(lg["leg_id"], 0)), lg["quantity"]) for lg in open_legs}
        want = {k: v for k, v in want.items() if v > 0}
        if not want:
            return {}
        tenant_id, trade_id = pos["tenant_id"], pos["trade_id"]
        n = 1 + await c.fetchval("SELECT count(*) FROM autodesk.execution_intents WHERE trade_id=$1 AND action=$2",
                                 trade_id, C.CLOSE_ACTION)
        key = f"{trade_id}:{C.CLOSE_ACTION}:{session.isoformat()}:{d.reason.value}:{n}"
        account = await store.get_account(c, tenant_id, pos["account_id"])
        adapter = gw.adapter_for(account)
        what = C.CLOSE_REASON_TEXT[d.reason]
        ctrl = [{"name": "reduce_only", "outcome": "PASS", "code": None, "detail": "closes held quantity only"},
                {"name": "authority", "outcome": "PASS", "code": None,
                 "detail": f"{C.CLOSE_AUTHORITY[d.reason]}: {what}"}]
        spec = {"reason": d.reason.value, "how": d.how.value, "fraction": str(d.fraction), "level": str(d.level) if d.level else None,
                "legs": {k: v for k, v in want.items()}, "detail": d.detail}
        intent = await c.fetchrow(
            """INSERT INTO autodesk.execution_intents (intent_id, tenant_id, account_id, simulation_id, trade_id, plan_version,
                   execution_mode, adapter, action, session_date, status, controls, order_spec, idempotency_key, sim_time)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,'VALIDATED',$11,$12,$13,$14)
               ON CONFLICT (tenant_id, idempotency_key) DO NOTHING RETURNING *""",
            C.new_id("INT"), tenant_id, pos["account_id"], pos["simulation_id"], trade_id, pos["plan_version"],
            ad.EXECUTION_MODE_OF_KIND[account["kind"]], ad.route_name(account), C.CLOSE_ACTION, session, ctrl, spec, key,
            sim_time)
        if intent is None:
            return {}                                       # the same closing was already decided: never twice
        intent = dict(intent)
        basket = len(want) > 1
        jb = dict(tenant_id=tenant_id, account_id=pos["account_id"], simulation_id=pos["simulation_id"], trade_id=trade_id,
                  sim_time=sim_time)
        await journal.record(c, **jb, kind="CLOSING_DECISION", ref_id=intent["intent_id"],
                             summary=f"closing {', '.join(f'{v} of leg {k}' for k, v in want.items())} by {what}"
                                     + (f" at level {d.level}" if d.level is not None else "") + f" ({d.how.value} price)"
                                     + (f"; {d.detail}" if d.detail else ""),
                             data=spec)
        await store.emit(c, C.EventType.CLOSING_DECIDED, tenant_id=tenant_id, producer=PRODUCER, account_id=pos["account_id"],
                         simulation_id=pos["simulation_id"], correlation_id=trade_id, sim_time=sim_time,
                         payload={"trade_id": trade_id, "intent_id": intent["intent_id"], **spec})
        if C.LifecycleState(pos["lifecycle_state"]) != LS.EXIT_PENDING:
            pos = await closure.move_state(c, pos, LS.EXIT_PENDING, reason=f"closing decided by {what}", session=session,
                                           sim_time=sim_time)
        # orders, through the account's paper adapter (submit only; nothing here can reach a broker)
        os_: list[tuple[dict, dict]] = []
        for lg in open_legs:
            q = want.get(lg["leg_id"])
            if not q:
                continue
            o = await self._insert_order(c, intent, pos, lg, q, d, basket=basket, sim_time=sim_time)
            try:
                await adapter.submit(o, o["idempotency_key"])
            except Exception as e:  # noqa: BLE001 — an adapter failure leaves the order UNKNOWN, resolved below, never retried blindly
                o = await orders.move(c, o, C.OrderState.UNKNOWN, reason=f"adapter failure: {type(e).__name__}: {e}",
                                      sim_time=sim_time)
                os_.append((o, lg))
                continue
            o = await orders.move(c, o, C.OrderState.ACKNOWLEDGED, reason="the paper adapter accepted it", sim_time=sim_time)
            o = await orders.move(c, o, C.OrderState.OPEN, reason="working at the paper venue", sim_time=sim_time)
            os_.append((o, lg))
        if any(o["state"] == "UNKNOWN" for o, _ in os_):
            await recon.resolve_orders(c, [o for o, _ in os_], sim_time=sim_time)
            await self._end(c, intent, [o for o, _ in os_], "NOT_FILLED", why="the paper adapter failed", sim_time=sim_time)
            pos = await closure.move_state(c, pos, LS.EXECUTION_ERROR, reason="the paper adapter failed on a closing order",
                                           session=session, sim_time=sim_time)
            await self._set_pending(c, xs, d, want, session, why="adapter failure")
            return {"waiting": 1}
        # pricing
        priced: list[tuple[dict, dict, fm.Decision]] = []
        for o, lg in os_:
            view = pricing.leg_view(lg, o["quantity"], ref=o["ref_price"])
            if live:
                q = quotes.get(view.key)
                problem = check_quote(q, at)
                dec = fm.rest(problem, "no fresh quote for this leg") if problem else \
                    fm.decide_quote(view, q, self.params, whole=basket)
            else:
                b, why = await self._bar(gw, _leg_ref(lg), session)
                lvl = d.level if d.how in (H.LEVEL, H.OBJECTIVE) else None
                rng = pricing.rng_for(seed, session, view.key, d.reason.value, n, view.side)
                dec = pricing.price_row(view, b, d.how, level=lvl, params=self.params, rng=rng) if b is not None else \
                    fm.rest("CLOSE_BLOCKED_NO_DATA", why)
            priced.append((o, lg, dec))
        blocked = [(o, lg, dec) for o, lg, dec in priced if dec.action != "FILL" or (basket and dec.qty < o["quantity"])]
        if blocked:
            first = blocked[0][2]
            code = first.code or "CLOSE_BLOCKED_NO_DATA"
            why = f"leg {blocked[0][1]['leg_id']}: {first.reason or 'not every leg could close in full'}"
            if basket or all(dec.action != "FILL" for _o, _lg, dec in priced):
                for o, _lg, _dec in priced:
                    await orders.note_no_fill(c, o, code, why, sim_time)
                    await orders.move(c, await orders.get_order(c, tenant_id, o["order_id"]), C.OrderState.EXPIRED,
                                      reason=f"{code}: {why}", sim_time=sim_time)
                await self._end(c, intent, [o for o, _, _ in priced], "NOT_FILLED", why=why, sim_time=sim_time)
                await self._set_pending(c, xs, d, want, session, why=f"{code}: {why}")
                await self._flag(c, pos, code, why)
                if live:
                    return {"waiting": 1}
                await journal.record(c, **jb, kind="LIFECYCLE", ref_id=f"{intent['intent_id']}:waiting",
                                     summary=f"closing could not be priced ({code}): {why}; it is carried to the next open",
                                     data={"code": code})
                return {"waiting": 1}
        # book the fills
        results, fraction_done, closes_all = [], Decimal("1"), True
        for o, lg, dec in priced:
            fresh = await orders.get_order(c, tenant_id, o["order_id"], for_update=True)
            fill_id, value, _ch, fees = await closure.insert_fill(c, intent_id=intent["intent_id"], order=fresh, d=dec, at=at,
                                                                  sim_time=sim_time)
            res = await closure.book_leg(c, pos=pos, leg=lg, qty=dec.qty, price=dec.price, value=value, fees=fees,
                                         ref_type="FILL", ref_id=fill_id, sim_time=sim_time, memo=f"closing by {what}")
            res["source"] = dec.source
            results.append(res)
            fraction_done = min(fraction_done, Decimal(dec.qty) / Decimal(lg["quantity"]))
            closes_all = closes_all and dec.qty == lg["quantity"]
            await journal.record(c, **jb, kind="CLOSING_FILL", ref_id=fill_id,
                                 summary=f"{'long' if lg['side'] == 'LONG' else 'short'} leg {lg['leg_id']}: {dec.qty} "
                                         f"{lg['underlying']} {lg['kind']} closed at {dec.price} (simulated), charges {fees}, "
                                         f"gross {res['realized_gross_rs']}",
                                 data={"price": str(dec.price), "quantity": dec.qty, "source": dec.source})
            await store.emit(c, C.EventType.ORDER_FILLED, tenant_id=tenant_id, producer=PRODUCER, account_id=pos["account_id"],
                             simulation_id=pos["simulation_id"], correlation_id=trade_id, sim_time=sim_time,
                             payload={"fill_id": fill_id, "order_id": o["order_id"], "trade_id": trade_id, "leg_id": lg["leg_id"],
                                      "quantity": dec.qty, "price": str(dec.price), "charges_rs": str(fees),
                                      "purpose": C.OrderPurpose.CLOSE.value, "fill_kind": "SIMULATED",
                                      "price_source": dec.source})
        left_legs = [lg for lg in open_legs if lg["leg_id"] not in want]
        closes_all = closes_all and not left_legs
        pos = await closure.release_unit(c, pos=pos, fraction=fraction_done, closes_all=closes_all, ref_id=intent["intent_id"],
                                         sim_time=sim_time, memo=f"closing by {what}")
        rec = await closure.record(c, pos=pos, intent_id=intent["intent_id"], reason=d.reason, how=d.how, session=session,
                                   legs=results, fraction=fraction_done, trigger_price=d.trigger_price, level=d.level,
                                   gapped=d.gapped, both_in_range=d.both_in_range, sim_time=sim_time)
        part = [o for o, lg, dec in priced if dec.qty < o["quantity"]]
        for o in part:
            await orders.move(c, await orders.get_order(c, tenant_id, o["order_id"]), C.OrderState.EXPIRED,
                              reason="the rest of this closing is carried to the next session", sim_time=sim_time)
        await self._end(c, intent, [o for o, _, _ in priced], "PARTIALLY_FILLED" if part else "FILLED", why=what,
                        sim_time=sim_time)
        if request is not None and rec["left"] == 0:
            await controls.request_done(c, trade_id)
        pos = rec["position"]
        if rec["left"] == 0:
            pos = await closure.move_state(c, pos, LS.CLOSED, reason=f"no quantity left ({what})", session=session,
                                           sim_time=sim_time)
            await c.execute("UPDATE autodesk.trade_exit_state SET pending=NULL, state=$2, updated_at=now() WHERE trade_id=$1",
                            trade_id, RL.state_to_json(replace(st, closed=True)))
            ok = await recon.settle_trade(c, pos, session=session, sim_time=sim_time)
            return {"closings": 1, "closed": 1, "settled_ok": int(ok)}
        pos = await closure.move_state(c, pos, LS.PARTIAL_EXIT, reason=f"{rec['left']} units left after {what}",
                                       session=session, sim_time=sim_time)
        if part:
            rest = {o["leg_id"]: o["quantity"] - dec.qty for o, _lg, dec in priced if dec.qty < o["quantity"]}
            await self._set_pending(c, xs, d, rest, session, why="volume share reached")
        else:
            nxt = (d.objective_index + 1) if d.objective_index is not None else xs["next_objective"]
            await c.execute("UPDATE autodesk.trade_exit_state SET pending=NULL, next_objective=$2, updated_at=now() "
                            "WHERE trade_id=$1", trade_id, nxt)
        return {"closings": 1}

    async def _insert_order(self, c, intent: dict, pos: dict, lg: dict, qty: int, d: RL.Decision, *, basket: bool,
                            sim_time) -> dict:
        oid = C.new_id("ORD")
        side = pricing.CLOSE_SIDE[lg["side"]]
        ref = lg["mark_price"] or lg["avg_price"]
        row = dict(await c.fetchrow(
            """INSERT INTO autodesk.trade_orders (order_id, intent_id, tenant_id, account_id, simulation_id, trade_id, plan_version,
                   leg_id, kind, underlying, expiry, strike, side, lots, lot_size, quantity, order_type, limit_price, ref_price,
                   state, session_date, idempotency_key, sim_time, purpose, close_reason, trigger_price)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,NULL,$18,'CREATED',$19,$20,$21,$22,$23,$24)
               RETURNING *""",
            oid, intent["intent_id"], pos["tenant_id"], pos["account_id"], pos["simulation_id"], pos["trade_id"],
            pos["plan_version"], lg["leg_id"], lg["kind"], lg["underlying"], lg["expiry"], lg["strike"], side,
            qty // lg["lot_size"], lg["lot_size"], qty, "BASKET_LEG" if basket else "MARKET", Decimal(str(ref)),
            intent["session_date"], f"{intent['idempotency_key']}:{lg['leg_id']}", sim_time, C.OrderPurpose.CLOSE.value,
            d.reason.value, d.level))
        await orders._history(c, row, None, C.OrderState.CREATED, "closing order from the lifecycle manager", sim_time)
        row = await orders.move(c, row, C.OrderState.VALIDATED, reason="reduces held quantity only", sim_time=sim_time)
        return await orders.move(c, row, C.OrderState.SUBMITTED, reason=f"sent to the {ad.route_name(await store.get_account(c, pos['tenant_id'], pos['account_id']))} adapter",
                                 sim_time=sim_time)

    async def _end(self, c, intent: dict, os_: list[dict], result: str, *, why: str, sim_time) -> None:
        await c.execute("UPDATE autodesk.execution_intents SET status='COMPLETED', result=$2, updated_at=now() WHERE intent_id=$1",
                        intent["intent_id"], result)
        await store.emit(c, C.EventType.EXECUTION_INTENT_COMPLETED, tenant_id=intent["tenant_id"], producer=PRODUCER,
                         account_id=intent["account_id"], simulation_id=intent["simulation_id"],
                         correlation_id=intent["trade_id"], sim_time=sim_time,
                         payload={"intent_id": intent["intent_id"], "trade_id": intent["trade_id"], "result": result,
                                  "action": C.CLOSE_ACTION, "why": why})

    async def _set_pending(self, c, xs: dict, d: RL.Decision, qty: dict, session: date, *, why: str) -> None:
        await c.execute("UPDATE autodesk.trade_exit_state SET pending=$2, updated_at=now() WHERE trade_id=$1", xs["trade_id"],
                        {"reason": d.reason.value, "qty": {k: int(v) for k, v in qty.items()}, "since": session.isoformat(),
                         "objective_index": d.objective_index, "why": why})

    async def _flag(self, c, pos: dict, code: str, why: str) -> None:
        await c.execute("""UPDATE autodesk.trade_positions SET flags = flags || $2::jsonb, updated_at=now() WHERE position_id=$1""",
                        pos["position_id"], [{"code": code, "detail": why}])

    async def _note(self, c, pos: dict, xs: dict, text: str, *, session: date) -> None:
        await c.execute("UPDATE autodesk.trade_exit_state SET notes = notes || $2::jsonb, updated_at=now() WHERE trade_id=$1",
                        xs["trade_id"], [text])

    async def _save_state(self, c, xs: dict, st: XR.State, *, session: date) -> None:
        await c.execute("UPDATE autodesk.trade_exit_state SET state=$2, last_session=$3, updated_at=now() WHERE trade_id=$1",
                        xs["trade_id"], RL.state_to_json(st), session)

    async def _level_moved(self, c, pos: dict, old: XR.State, new: XR.State, *, session: date, sim_time) -> None:
        await journal.record(c, tenant_id=pos["tenant_id"], account_id=pos["account_id"], simulation_id=pos["simulation_id"],
                             trade_id=pos["trade_id"], kind="LIFECYCLE", ref_id=f"{pos['position_id']}:level:{new.stop_version}",
                             sim_time=sim_time,
                             summary=f"trailing level moved from {old.stop} to {new.stop} after the {session} close, in force "
                                     f"from the next session (version {new.stop_version})",
                             data={"from": old.stop, "to": new.stop, "version": new.stop_version})
        await store.emit(c, C.EventType.LEVEL_TIGHTENED, tenant_id=pos["tenant_id"], producer=PRODUCER, account_id=pos["account_id"],
                         simulation_id=pos["simulation_id"], correlation_id=pos["trade_id"], sim_time=sim_time,
                         payload={"trade_id": pos["trade_id"], "from": old.stop, "to": new.stop, "version": new.stop_version})

    # ── expiry settlement (PHASE3_DESIGN §6) ─────────────────────────────────────────────────────────────────────

    async def _settle(self, gw, c, pos: dict, xs: dict, legs: list[dict], *, session: date, sim_time) -> dict:
        due = [lg for lg in legs if lg.get("expiry") == session and lg["quantity"] > 0]
        if not due:
            return {}
        prices: dict[str, tuple[Decimal, str]] = {}
        problems: list[str] = []
        und = due[0]["underlying"]
        und_close: Optional[Decimal] = None
        if any(lg["kind"] in ("CE", "PE") for lg in due):
            ub, why = await self._bar(gw, LegRef("EQ", und), session)
            if ub is None or ub.close is None or not ub.traded:
                problems.append(f"no closing price of {und} on {session} ({why or 'no trade'})")
            else:
                und_close = ub.close
                fb, _w = await self._bar(gw, LegRef("FUT", und, session), session)
                if fb is not None and fb.settle:
                    if abs(fb.settle - und_close) / und_close > Decimal("0.0005"):
                        problems.append(f"{und} close {und_close} and the expiring future's settlement {fb.settle} differ by "
                                        f"more than 0.05%")
        for lg in due:
            if lg["kind"] == "FUT":
                fb, why = await self._bar(gw, _leg_ref(lg), session)
                if fb is None or not fb.settle:
                    problems.append(f"leg {lg['leg_id']}: no settlement price in the {session} F&O row ({why or 'empty'})")
                else:
                    prices[lg["leg_id"]] = (fb.settle, f"{fb.source} settlement price {fb.settle}")
            elif und_close is not None:
                v = pricing.intrinsic(lg["kind"], Decimal(str(lg["strike"])), und_close)
                prices[lg["leg_id"]] = (v, f"intrinsic value against the {session} close of {und} {und_close}")
        if problems:
            why = "; ".join(problems)
            await self._flag(c, pos, "SETTLEMENT_DATA_MISSING", why)
            if C.LifecycleState(pos["lifecycle_state"]) != LS.RECONCILIATION_REQUIRED:
                await closure.move_state(c, pos, LS.RECONCILIATION_REQUIRED, reason=f"settlement data missing: {why}",
                                         session=session, sim_time=sim_time)
            await journal.record(c, tenant_id=pos["tenant_id"], account_id=pos["account_id"], simulation_id=pos["simulation_id"],
                                 trade_id=pos["trade_id"], kind="LIFECYCLE", ref_id=f"{pos['position_id']}:settle-missing:{session}",
                                 sim_time=sim_time, summary=f"not settled: {why}; no price is assumed, tried again at the next close",
                                 data={"problems": problems})
            return {"waiting": 1}
        results = []
        ref_id = f"{pos['trade_id']}:SETTLEMENT:{session.isoformat()}"
        for lg in due:
            px, src = prices[lg["leg_id"]]
            value = rs(px * lg["quantity"])
            from ..execution import costs
            fees = rs(costs.charges(lg["kind"], pricing.CLOSE_SIDE[lg["side"]], value)["total"])
            res = await closure.book_leg(c, pos=pos, leg=lg, qty=lg["quantity"], price=px, value=value, fees=fees,
                                         ref_type="SETTLEMENT", ref_id=ref_id, sim_time=sim_time, memo="settled at expiry")
            res["source"] = src
            results.append(res)
        closes_all = len(due) == len([lg for lg in legs if lg["quantity"] > 0])
        pos = await closure.release_unit(c, pos=pos, fraction=Decimal("1"), closes_all=closes_all, ref_id=ref_id,
                                         sim_time=sim_time, memo="settled at expiry")
        if C.LifecycleState(pos["lifecycle_state"]) not in (LS.EXIT_PENDING,):
            if LS.EXIT_PENDING in C.LIFECYCLE_TRANSITIONS[C.LifecycleState(pos["lifecycle_state"])]:
                pos = await closure.move_state(c, pos, LS.EXIT_PENDING, reason="contract expiry", session=session,
                                               sim_time=sim_time)
        rec = await closure.record(c, pos=pos, intent_id=None, reason=R.EXPIRY, how=H.SETTLEMENT, session=session,
                                   legs=results, fraction=Decimal("1"), sim_time=sim_time)
        if rec["left"] == 0:
            pos = await closure.move_state(c, rec["position"], LS.CLOSED, reason="settled at contract expiry", session=session,
                                           sim_time=sim_time)
            await c.execute("UPDATE autodesk.trade_exit_state SET pending=NULL, updated_at=now() WHERE trade_id=$1",
                            pos["trade_id"])
            await recon.settle_trade(c, pos, session=session, sim_time=sim_time)
            return {"settled": 1, "closed": 1}
        return {"settled": 1}

    # ── controls acting on entries (gateway hook) ────────────────────────────────────────────────────────────────

    async def entry_blocks(self, c, *, tenant_id: str, account: dict, strategy: str, session: date,
                           as_of: datetime) -> list[tuple[str, str, str]]:
        """(control name, refusal code, detail) for each lifecycle control or loss limit that refuses a new intent."""
        out = await controls.entry_blocks(c, tenant_id=tenant_id, account=account, strategy=strategy)
        out += await limits.entry_blocks(c, tenant_id=tenant_id, account_id=account["account_id"], session=session,
                                         as_of=as_of, live=account["simulation_id"] is None)
        return out

    # ── live desk (PHASE3_DESIGN §10.1) ──────────────────────────────────────────────────────────────────────────

    async def live_refs(self, c, *, tenant_id: Optional[str] = None) -> list[LegRef]:
        """Trigger rows and legs of open desk positions: added to the tick's single quote read."""
        refs: list[LegRef] = []
        rows = await c.fetch("""SELECT x.trigger_key, l.kind, l.underlying, l.expiry, l.strike FROM autodesk.trade_exit_state x
                                JOIN autodesk.trade_positions p USING (trade_id)
                                JOIN autodesk.trade_position_legs l ON l.position_id = p.position_id
                                WHERE p.simulation_id IS NULL AND p.status='OPEN' AND l.quantity > 0
                                  AND ($1::text IS NULL OR p.tenant_id=$1)""", tenant_id)
        for r in rows:
            if r["trigger_key"]:
                refs.append(_ref(r["trigger_key"]))
            refs.append(_leg_ref(dict(r)))
        return refs

    async def live_pass(self, gw, *, quotes: dict, now: datetime, tenant_id: Optional[str] = None) -> dict:
        """One pass over open desk positions on the tick's fresh quotes. No fresh quote, no closing fill: it waits."""
        out = {"closings": 0, "closed": 0, "waiting": 0, "activated": 0}
        today = now.astimezone(IST).date()
        async with self.pool.acquire() as c:
            accts = [dict(r) for r in await c.fetch(
                """SELECT DISTINCT tenant_id, account_id FROM autodesk.trade_positions WHERE simulation_id IS NULL AND status='OPEN'
                   AND ($1::text IS NULL OR tenant_id=$1)""", tenant_id)]
        for a in accts:
            out["activated"] += await self.sim_activate(gw, tenant_id=a["tenant_id"], account_id=a["account_id"], session=today,
                                                        as_of=now, filled_at_open=False)
            async with self.pool.acquire() as c:
                positions = [p for p in await self._open_positions(c, a["tenant_id"], a["account_id"]) if p["has_state"]]
            for p in positions:
                async with self.pool.acquire() as c:
                    async with c.transaction():
                        await capital.lock_account(c, a["tenant_id"], a["account_id"])
                        pos = dict(await c.fetchrow("SELECT * FROM autodesk.trade_positions WHERE trade_id=$1 FOR UPDATE",
                                                    p["trade_id"]))
                        if pos["status"] != "OPEN":
                            continue
                        xs = await self._xs(c, pos["trade_id"])
                        r = await self._live_one(gw, c, pos, xs, quotes=quotes, now=now, today=today)
                        for k, v in r.items():
                            out[k] = out.get(k, 0) + v
        return out

    async def _live_daily(self, c, pos: dict, xs: dict, s: RL.Setup, st: XR.State, today: date) -> XR.State:
        """Once per session: step the previous session's exchange row (published) for the trail and the sessions held. A
        level that row shows crossed while no fresh quote was there becomes a pending closing (the conservative reading)."""
        if self.eod_bars is None or not s.trigger_key or st.closed:
            return st
        prev = None
        try:
            d = today - timedelta(days=1)
            for _ in range(10):
                if calendar.is_session(d):
                    prev = d
                    break
                d -= timedelta(days=1)
        except calendar.CalendarUnavailable:
            return st
        if prev is None or prev < xs["first_step_session"] or (xs["last_session"] and xs["last_session"] >= prev):
            return st
        try:
            b = await self.eod_bars.bar(_ref(s.trigger_key), prev, clock_session=prev)
        except DataUnavailable:
            b = None
        if b is None or not b.traded or b.high is None or b.low is None:
            return st
        step = RL.at_close(s, st, xs["next_objective"], b, prev, freeze_trail=await controls.modifications_suspended(c, pos))
        if step.decision is not None and step.decision.reason in (R.STOP, R.TRAILING_STOP) and not xs["pending"]:
            await self._set_pending(c, xs, step.decision, {lg["leg_id"]: lg["quantity"] for lg in await self._legs(c, pos["position_id"])},
                                    today, why=f"the {prev} exchange row crossed the level while no fresh quote closed it")
        new = step.state if step.decision is None else replace(st, sessions_held=st.sessions_held + 1)
        if st.stop != new.stop and not new.closed:
            await self._level_moved(c, pos, st, new, session=prev, sim_time=None)
        await self._save_state(c, xs, new, session=prev)
        return new

    async def _live_one(self, gw, c, pos: dict, xs: dict, *, quotes: dict, now: datetime, today: date) -> dict:
        s = _setup_from(xs["rules"]["setup"])
        st = await self._live_daily(c, pos, xs, s, RL.state_from_json(xs["state"]), today)
        xs = await self._xs(c, pos["trade_id"])
        legs = [lg for lg in await self._legs(c, pos["position_id"]) if lg["quantity"] > 0]
        if not legs or not all(in_fill_window(lg["kind"], now) for lg in legs):
            return {}
        req = await controls.close_request_for(c, pos)
        d: Optional[RL.Decision] = None
        qty = None
        late = now.astimezone(IST).time() >= LATE_IST
        if req is not None:
            d = RL.Decision(reason=C.CloseReason(req["reason"]), how=H.QUOTE, fraction=Decimal("1"), detail=req["note"])
        elif xs["pending"]:
            pend = xs["pending"]
            d = RL.Decision(reason=C.CloseReason(pend["reason"]), how=H.QUOTE, fraction=Decimal("1"),
                            objective_index=pend.get("objective_index"), detail=f"waiting since {pend.get('since')}")
            qty = {k: int(v) for k, v in (pend.get("qty") or {}).items()}
        elif s.trigger_key:
            q = quotes.get(_ref(s.trigger_key).key)
            if check_quote(q, now) is not None:
                return {"waiting": 0}
            ltp = q.ltp
            long = s.side == "long"
            if st.stop is not None and (ltp <= Decimal(str(st.stop)) if long else ltp >= Decimal(str(st.stop))):
                d = RL.Decision(reason=R.TRAILING_STOP if XR._raised(st, RL.make_rules(s, xs["next_objective"])) else R.STOP,
                                how=H.QUOTE, fraction=Decimal("1"), level=Decimal(str(st.stop)), trigger_price=ltp)
            elif xs["next_objective"] < len(s.objectives):
                lvl = Decimal(s.objectives[xs["next_objective"]]["level"])
                if (ltp > lvl) if long else (ltp < lvl):
                    d = RL.Decision(reason=R.TARGET, how=H.QUOTE, objective_index=xs["next_objective"], level=lvl,
                                    trigger_price=ltp, fraction=Decimal(s.objectives[xs["next_objective"]]["fraction"]))
        if d is None and late and s.max_hold and st.sessions_held + 1 >= s.max_hold:
            d = RL.Decision(reason=R.TIME, how=H.QUOTE, fraction=Decimal("1"), detail=f"{s.max_hold} sessions held")
        if d is None and late and xs["pre_expiry_session"] and today >= xs["pre_expiry_session"]:
            d = RL.Decision(reason=R.PRE_EXPIRY, how=H.QUOTE, fraction=Decimal("1"))
        if d is None:
            return {}
        return await self._execute(gw, c, pos, xs, s, st, legs, d, session=today, at=now, sim_time=None, seed=0, qty=qty,
                                   quotes=quotes, request=req)


def pit_history(market_factory) -> History:
    """ATR warm-up from the agents' point-in-time view: daily bars published before `as_of` only (it refuses later data)."""
    async def history(symbol: str, as_of: datetime, n: int) -> list[dict]:
        bars = await market_factory(as_of).daily_bars(symbol, sessions=n)
        return [{"date": b.day, "open": float(b.open), "high": float(b.high), "low": float(b.low), "close": float(b.close)}
                for b in bars]
    return history
