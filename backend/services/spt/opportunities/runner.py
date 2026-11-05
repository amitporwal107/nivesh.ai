"""The slice-A loop (DESIGN.md §2: `start()` / `stop()`, wired by the integrator in server.py).

One round, on the worker holding the leader lock (scan_builder.signals.get_store().lead, key LEADER_KEY):
    1 catch_up     ingest any list mark / strong signal of today (and, on the first round, the two days before: Redis keeps
                   three) that the hook did not store (signals/hook.catch_up; idempotent)
    2 consolidate  place the new normalized events into opportunities (the days still inside a window)
    3 validate     validate / revalidate what is due, at most SPT_VALIDATE_MAX_PER_ROUND, strong and positional first
    4 expire       window ended; a daily close below a strong plan's stop
    5 outcomes     (P1, services/spt/outcomes/tracker.py) the evening run, once NSE's end-of-day file for the day is in
Every step is wrapped: a failing step is logged with its type, recorded in `errors`, and the round goes on; a round never
raises. The leader lock is re-asserted (and its TTL extended) before each step; a worker that lost it stops the round
("<step>: leader_lost"), so a long round never runs alongside another worker's. Each round writes `spt_state` {_id: "spt_a", at, leader, round_ms, counts, errors} for the morning check.

Cadence: every LOOP_S (30 s) in the session (09:15–15:30 IST weekdays), every IDLE_S (5 min) outside it.
Flag: on where APP_ENV=staging; SPT_A_ENABLED=0 turns it off, =1 turns it on elsewhere.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional

from .. import constants as C
from ..signals import clock, hook
from . import consolidate as cons
from . import inputs as inputs_mod
from . import validate as val

logger = logging.getLogger(__name__)

LEADER_KEY = "nivesh:spt:a:leader"
LEADER_TTL_S = 120
LOOP_S = 30.0
IDLE_S = 300.0
STATE_ID = "spt_a"
CATCH_UP_BACK_DAYS = 2
OVERLAP_S = 180

_task: Optional["asyncio.Task[Any]"] = None
_ME = f"{os.getpid()}:{uuid.uuid4().hex[:8]}"
_mem: Dict[str, Any] = {"first_round": True, "received_since": None}


def enabled(env: Optional[Dict[str, str]] = None) -> bool:
    env = os.environ if env is None else env
    flag = (env.get("SPT_A_ENABLED") or "").strip()
    if flag == "0":
        return False
    return flag == "1" or (env.get("APP_ENV") or "").strip().lower() == "staging"


def max_per_round(env: Optional[Dict[str, str]] = None) -> int:
    if env is None:
        from services.spt import settings                 # the admin's market-wide settings over os.environ
        env = settings.overlay()
    raw = env.get("SPT_VALIDATE_MAX_PER_ROUND")
    try:
        n = int(raw) if raw not in (None, "") else val.MAX_PER_ROUND
    except ValueError:
        return val.MAX_PER_ROUND
    return n if 1 <= n <= 1000 else val.MAX_PER_ROUND


def active_days(now: datetime, sessions: int) -> List[str]:
    """The IST days whose signals can still be inside a window: today and the `sessions` weekdays before it."""
    today = clock.ist_day(now)
    out, d = [today.isoformat()], today
    while len(out) < sessions + 1:
        d -= timedelta(days=1)
        if d.weekday() < 5:
            out.append(d.isoformat())
    return out


def _db():
    from deps import db
    return db


async def round_once(db, now: datetime, *, scan_store: Any = None, inputs: Optional[inputs_mod.MarketInputs] = None,
                     me: str = _ME, outcomes: Optional[Callable[..., Awaitable[Dict[str, Any]]]] = None,
                     env: Optional[Dict[str, str]] = None) -> Optional[Dict[str, Any]]:
    """One round (see the module docstring). None when another worker leads; else {counts, errors}."""
    from services.scan_builder import signals as SIG
    s = scan_store or SIG.get_store()
    if not await s.lead(LEADER_KEY, me, LEADER_TTL_S, time.time()):
        return None
    t0 = time.monotonic()
    inputs = inputs or inputs_mod.get_inputs()
    counts: Dict[str, Any] = {}
    errors: List[str] = []
    today = clock.ist_day(now).isoformat()
    sessions = clock.window_sessions(env)

    lost = {"v": False}

    async def step(name: str, fn: Callable[[], Awaitable[Any]]) -> None:
        if lost["v"]:
            return
        if not await s.lead(LEADER_KEY, me, LEADER_TTL_S, time.time()):    # re-assert (and extend) the lock per step
            lost["v"] = True
            errors.append(f"{name}: leader_lost")
            return
        try:
            counts[name] = await fn()
        except Exception as e:  # noqa: BLE001 — one step failing never stops the round or the loop
            logger.warning("spt loop: %s failed (%s)", name, type(e).__name__)
            errors.append(f"{name}: {type(e).__name__}")

    back = [d for d in active_days(now, CATCH_UP_BACK_DAYS)] if _mem["first_round"] else [today]

    async def catch_up() -> Dict[str, Any]:
        out = {}
        for d in back:
            out[d] = await hook.catch_up(db, d, scan_store=s, now=now)
        return out

    await step("catch_up", catch_up)
    if "catch_up" in counts:
        _mem["first_round"] = False
    started = now
    await step("consolidate", lambda: cons.consolidate(db, days=active_days(now, sessions), now=now, sessions=sessions,
                                                       received_since=_mem["received_since"]))
    if "consolidate" in counts:
        _mem["received_since"] = clock.utc_iso(started - timedelta(seconds=OVERLAP_S))
    await step("validate", lambda: val.validate_due(db, now=now, inputs=inputs, limit=max_per_round(env), env=env))
    await step("expire", lambda: val.expire(db, now=now, inputs=inputs))
    if outcomes is not None:
        await step("outcomes", lambda: outcomes(db, now=now, inputs=inputs, scan_store=s))
    state = {"at": clock.utc_iso(now), "leader": me, "round_ms": int((time.monotonic() - t0) * 1000), "counts": counts,
             "errors": errors, "in_session": clock.in_session(now)}
    if not errors:
        state["last_ok_at"] = state["at"]
    try:
        await db[C.STATE].update_one({"_id": STATE_ID}, {"$set": state}, upsert=True)
    except Exception as e:  # noqa: BLE001 — the state doc is for the morning check; the round's work stands
        logger.warning("spt loop: spt_state not written (%s)", type(e).__name__)
    return {"counts": counts, "errors": errors}


async def outcomes_step(db, *, now: datetime, inputs: inputs_mod.MarketInputs, scan_store: Any = None) -> Dict[str, Any]:
    """Step 5 (P1): the evening signal outcomes (services/spt/outcomes/tracker.evening)."""
    from services.spt.outcomes import tracker
    return await tracker.evening(db, now=now, inputs=inputs, scan_store=scan_store)


async def _loop() -> None:
    while True:
        now = datetime.now(timezone.utc)
        try:
            from services.spt import settings
            await settings.refresh(_db())                  # every worker, before the leader check (settings.py)
            await round_once(_db(), now, outcomes=outcomes_step, env=settings.overlay())
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — round_once never raises by design; this is the last guard, logged with its trace
            logger.exception("spt loop: a round failed")
        await asyncio.sleep(LOOP_S if clock.in_session(datetime.now(timezone.utc)) else IDLE_S)


def start() -> bool:
    """Start the loop on this worker when enabled (server startup). True if started."""
    global _task
    if not enabled() or (_task is not None and not _task.done()):
        return False
    _task = asyncio.get_running_loop().create_task(_loop())
    logger.info("spt signals/opportunities: loop started (every %.0f s in the session, one leader across workers)", LOOP_S)
    return True


def stop() -> None:
    if _task is not None and not _task.done():
        _task.cancel()
