"""Trading Desk Simulator (PRD §28; DESIGN §6.4, PHASE2_DESIGN §5–§6).

A simulation owns one SIMULATION account (isolated by simulation_id) and a clock that walks each session's schedule:

    PREMARKET 08:30 → SCAN 08:45 → PROPOSALS 09:00 → OPEN 09:15 → CLOSE 15:30 → EOD 18:00   (IST)

At each step the orchestrator runs the workflows due, with a market view bound to the step's sim time, so agents see
only data published by then. With an execution gateway, OPEN submits what was approved and fills it from the session's
row, CLOSE settles resting orders, expires the rest and marks positions; with none they do nothing (Phase 1 behaviour).
EOD expires the session's unused signals and unanswered approvals.

One step runs at a time per simulation (advisory lock). `step_seq` is the cursor into the schedule, so a step is never
run twice and a stopped simulation never moves again.
"""
from __future__ import annotations

import logging
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Awaitable, Callable, Optional

from .. import contracts as C
from .. import store
from ..accounts import open_account
from ..market.view import IST

log = logging.getLogger(__name__)

SessionsProvider = Callable[[date, date], Awaitable[list[date]]]
MAX_SESSIONS = 30          # Phase 1 bound per simulation (each session runs up to ~N agent tasks per signal)

PHASE2_LIMITATIONS = [
    "Decisions are made before the open on the previous session's end-of-day data; there is no intraday replay "
    "(stored intraday history is about ten days and has no cash stocks).",
    "Every fill is simulated from the session's daily row (open, high, low, close, traded quantity): no order book, no "
    "queue position, spreads are proxies. A resting limit fills only if price traded through it, at the limit.",
    "The fill engine knows the session's traded quantity at 09:15, as a capacity assumption only (agents never see it). "
    "The moment a resting fill happened within the session is not known.",
    "Several-leg plans fill all-or-none at the open. Closing positions (stops, levels, trailing) and settlement at a "
    "contract's expiry are Phase 3: positions stay open and are marked at each session's close, so P&L is unrealized only "
    "and no closing costs are counted. A leg that did not trade keeps its last mark, flagged stale.",
    "Option premiums are the contract's own bhavcopy open; untraded strikes are rejected. Price bands, ticks and spreads "
    "are proxies (no band file, one 0.05 tick).",
    "Futures margin is an estimate (policy futures_margin_pct), not exchange SPAN. Costs are desk-cost-v2.",
    "Daily-loss, weekly-loss and drawdown limits are not enforced: they act on P&L from Phase 3, with the trade lifecycle.",
    "Sector is the latest index-constituent industry, not point-in-time.",
]

PHASE3_LIMITATIONS = PHASE2_LIMITATIONS[:3] + [
    "Several-leg plans fill all-or-none at the open and close as one unit. Positions are managed from their fills to closure "
    "(docs/autodesk/PHASE3_DESIGN.md): the invalidation level, objectives (partial in whole lots), the ATR trail, the holding "
    "period, the sessions-before-expiry rule and settlement at expiry, each judged only on what the clock allows.",
    "End-of-day rows cannot show when a level traded inside the session: a level touched inside the row closes shares and "
    "futures at the level (an open through it at the open), option structures at their legs' closes; an objective fills "
    "only if price traded through it; the level and an objective in one row count as the level.",
    "Futures levels are the plan's underlying levels translated by the entry session's basis (future ÷ share previous "
    "closes). Option final settlement uses the share's close on expiry day; missing settlement data is never assumed.",
    PHASE2_LIMITATIONS[4], PHASE2_LIMITATIONS[5],
    "Daily-loss, weekly-loss and drawdown limits act on P&L: a daily breach refuses new intents that session and the next, a "
    "weekly one until the week ends, a drawdown breach suspends the account until a person lifts it.",
    PHASE2_LIMITATIONS[7],
]

LIMITATIONS = [
    "Decisions are made before the open on the previous session's end-of-day data; there is no intraday replay "
    "(stored intraday history is about ten days and has no cash stocks).",
    "This run has no paper execution (no execution gateway was wired): approved plans are not filled, so there is no P&L, "
    "no capital reservation and the daily-loss / weekly-loss / drawdown checks are skipped.",
    "Option premiums are the previous session's bhavcopy closes of contracts that traded; untraded strikes are skipped.",
    "Futures margin is an estimate (policy futures_margin_pct), not exchange SPAN.",
    "Sector is the latest index-constituent industry, not point-in-time.",
]


def phase_time(day: date, hhmm: str) -> datetime:
    h, m = (int(x) for x in hhmm.split(":"))
    return datetime(day.year, day.month, day.day, h, m, tzinfo=IST).astimezone(timezone.utc)


class SimulationManager:
    def __init__(self, pool, orchestrator, sessions_provider: SessionsProvider,
                 versions: Optional[Callable[[], dict]] = None, execution: Any = None):
        self.pool = pool
        self.orch = orchestrator
        self.execution = execution      # execution.gateway.ExecutionGateway; None = Phase 1 behaviour (OPEN and CLOSE do nothing)
        self.sessions_provider = sessions_provider
        self._versions = versions or (lambda: {})

    # ── lifecycle ───────────────────────────────────────────────────────────────────────────────────────────────

    async def create(self, *, tenant_id: str, cfg: C.SimulationConfig, user_id: str) -> dict:
        sessions = await self.sessions_provider(cfg.start_date, cfg.end_date)
        if not sessions:
            raise ValueError("no trading sessions in the chosen date range")
        if len(sessions) > MAX_SESSIONS:
            raise ValueError(f"at most {MAX_SESSIONS} sessions per simulation in Phase 1 (got {len(sessions)})")
        if cfg.symbols is not None and not (1 <= len(cfg.symbols) <= 50):
            raise ValueError("symbols: 1 to 50 instruments")
        async with self.pool.acquire() as c:
            async with c.transaction():
                versions = dict(self._versions())
                sim = await store.create_simulation(c, tenant_id=tenant_id, cfg=cfg, created_by=f"user:{user_id}",
                                                    versions=versions)
                acc = await open_account(c, tenant_id=tenant_id, name=f"Simulation · {cfg.name}",
                                         kind=C.AccountKind.SIMULATION, mode=cfg.operating_mode,
                                         capital=cfg.starting_capital_rs, created_by=f"user:{user_id}",
                                         policy_id=cfg.policy_id, simulation_id=sim["simulation_id"])
                pol = await store.get_policy(c, tenant_id, acc["policy_id"])
                versions["policy"] = {"policy_id": pol["policy_id"], "version": pol["version"],
                                      "sha256": pol["body_sha256"]}
                await c.execute("""UPDATE autodesk.simulations SET account_id=$2, versions=$3,
                                   config = config || jsonb_build_object('sessions', $4::jsonb) WHERE simulation_id=$1""",
                                sim["simulation_id"], acc["account_id"], versions,
                                [d.isoformat() for d in sessions])
                return await store.get_simulation(c, tenant_id, sim["simulation_id"])

    async def _set_status(self, tenant_id: str, sid: str, *, allowed_from: set[str], to: C.SimulationStatus,
                          user: str, **cols) -> dict:
        async with self.pool.acquire() as c:
            async with c.transaction():
                sim = await store.get_simulation(c, tenant_id, sid, for_update=True)
                if sim["status"] not in allowed_from:
                    raise store.Conflict(f"simulation is {sim['status']}; cannot move to {to.value}")
                return await store.update_simulation(c, tenant_id=tenant_id, simulation_id=sid, producer=user,
                                                     status=to, **cols)

    async def start(self, *, tenant_id: str, sid: str, user_id: str) -> dict:
        return await self._set_status(tenant_id, sid, allowed_from={"CREATED"}, to=C.SimulationStatus.RUNNING,
                                      user=f"user:{user_id}", started_at=datetime.now(timezone.utc))

    async def pause(self, *, tenant_id: str, sid: str, user_id: str) -> dict:
        return await self._set_status(tenant_id, sid, allowed_from={"RUNNING"}, to=C.SimulationStatus.PAUSED,
                                      user=f"user:{user_id}")

    async def resume(self, *, tenant_id: str, sid: str, user_id: str) -> dict:
        return await self._set_status(tenant_id, sid, allowed_from={"PAUSED"}, to=C.SimulationStatus.RUNNING,
                                      user=f"user:{user_id}")

    async def stop(self, *, tenant_id: str, sid: str, user_id: str) -> dict:
        """Stops safely: the cursor stays where it is; no further step runs. Nothing outside the simulation is touched."""
        return await self._set_status(tenant_id, sid, allowed_from={"CREATED", "RUNNING", "PAUSED"},
                                      to=C.SimulationStatus.STOPPED, user=f"user:{user_id}",
                                      ended_at=datetime.now(timezone.utc))

    # ── clock ───────────────────────────────────────────────────────────────────────────────────────────────────

    @staticmethod
    def schedule(sim: dict) -> list[tuple[date, C.ClockPhase, str]]:
        days = [date.fromisoformat(d) for d in sim["config"]["sessions"]]
        return [(d, ph, hhmm) for d in days for ph, hhmm in C.CLOCK_SCHEDULE_IST]

    async def step(self, *, tenant_id: str, sid: str, unit: str = "PHASE", user_id: str = "system") -> dict:
        """Run the next phase ('PHASE') or the rest of the current session ('SESSION')."""
        if unit not in ("PHASE", "SESSION"):
            raise ValueError("unit must be PHASE or SESSION")
        lock_conn = await self.pool.acquire()
        try:
            got = await lock_conn.fetchval("SELECT pg_try_advisory_lock(hashtext($1))", sid)
            if not got:
                raise store.Conflict("a step is already running for this simulation")
            try:
                ran = []
                while True:
                    r = await self._one_phase(tenant_id, sid)
                    if r is None:
                        break
                    ran.append(r)
                    if unit == "PHASE" or r["phase"] == C.ClockPhase.EOD.value or r.get("completed"):
                        break
                async with self.pool.acquire() as c:
                    sim = await store.get_simulation(c, tenant_id, sid)
                return {"simulation_id": sid, "status": sim["status"], "steps": ran, "step_seq": sim["step_seq"],
                        "clock_sim_time": sim["clock_sim_time"], "clock_phase": sim["clock_phase"]}
            finally:
                await lock_conn.execute("SELECT pg_advisory_unlock(hashtext($1))", sid)
        finally:
            await self.pool.release(lock_conn)

    async def _one_phase(self, tenant_id: str, sid: str) -> Optional[dict]:
        async with self.pool.acquire() as c:
            sim = await store.get_simulation(c, tenant_id, sid)
        if sim["status"] != C.SimulationStatus.RUNNING.value:
            if sim["status"] in ("CREATED", "PAUSED", "STOPPED", "COMPLETED", "FAILED"):
                raise store.Conflict(f"simulation is {sim['status']}; it does not step")
        sched = self.schedule(sim)
        seq = sim["step_seq"]
        if seq >= len(sched):
            return None
        day, phase, hhmm = sched[seq]
        t = phase_time(day, hhmm)
        cfg = sim["config"]
        acc = sim["account_id"]
        wf_ids: list[str] = []
        detail: dict[str, Any] = {}
        try:
            if phase == C.ClockPhase.PREMARKET:
                cycle = await self.orch.open_session_cycle(
                    tenant_id=tenant_id, account_id=acc, session_date=day, as_of=t, simulation_id=sid,
                    universe=cfg["universe"], symbols=cfg.get("symbols"),
                    max_proposals=cfg["max_proposals_per_session"], idempotency_key=f"{sid}:{day.isoformat()}:cycle",
                    producer="SIMULATION_CLOCK")
                wf_ids.append(cycle["workflow_id"])
                detail = await self.orch.phase_premarket(tenant_id=tenant_id, cycle_id=cycle["workflow_id"], as_of=t)
            elif phase in (C.ClockPhase.SCAN, C.ClockPhase.PROPOSALS):
                cycle_id = await self._cycle_id(tenant_id, sid, day)
                wf_ids.append(cycle_id)
                fn = self.orch.phase_scan if phase == C.ClockPhase.SCAN else self.orch.phase_proposals
                detail = await fn(tenant_id=tenant_id, cycle_id=cycle_id, as_of=t)
                if phase == C.ClockPhase.PROPOSALS:
                    wf_ids += [r["workflow_id"] for r in detail.get("results", [])]
            elif phase == C.ClockPhase.OPEN and self.execution is not None:
                from ..execution import settle
                detail = await settle.run_open(self.execution, tenant_id=tenant_id, simulation_id=sid, session=day, as_of=t)
            elif phase == C.ClockPhase.CLOSE and self.execution is not None:
                from ..execution import settle
                detail = await settle.run_close(self.execution, tenant_id=tenant_id, simulation_id=sid, session=day, as_of=t)
            elif phase == C.ClockPhase.EOD:
                detail = await self.orch.close_session(tenant_id=tenant_id, account_id=acc, session_date=day,
                                                       simulation_id=sid, as_of=t)
        except store.Conflict as e:
            detail = {"skipped": str(e)}
        except Exception as e:  # noqa: BLE001 — the simulation records the failure and stops moving
            log.exception("simulation %s failed at %s %s", sid, day, phase.value)
            async with self.pool.acquire() as c:
                async with c.transaction():
                    await store.update_simulation(c, tenant_id=tenant_id, simulation_id=sid, producer="SIMULATION_CLOCK",
                                                  status=C.SimulationStatus.FAILED,
                                                  error=f"{day} {phase.value}: {type(e).__name__}: {e}",
                                                  ended_at=datetime.now(timezone.utc))
            return {"session_date": day.isoformat(), "phase": phase.value, "sim_time": t.isoformat(),
                    "error": f"{type(e).__name__}: {e}"}
        completed = seq + 1 >= len(sched)
        async with self.pool.acquire() as c:
            async with c.transaction():
                await store.add_clock_event(c, tenant_id=tenant_id, simulation_id=sid, seq=seq + 1, session_date=day,
                                            phase=phase, sim_time=t, workflows=wf_ids)
                cols: dict[str, Any] = {"step_seq": seq + 1, "clock_sim_time": t, "clock_session": day,
                                        "clock_phase": phase.value}
                if completed:
                    cols.update(status=C.SimulationStatus.COMPLETED, ended_at=datetime.now(timezone.utc))
                await store.update_simulation(c, tenant_id=tenant_id, simulation_id=sid, producer="SIMULATION_CLOCK",
                                              **cols)
        if completed:
            res = await self.results(tenant_id=tenant_id, sid=sid)
            async with self.pool.acquire() as c:
                await c.execute("UPDATE autodesk.simulations SET results=$2 WHERE simulation_id=$1", sid, res)
        return {"session_date": day.isoformat(), "phase": phase.value, "sim_time": t.isoformat(),
                "workflows": wf_ids, "detail": _plain(detail), "completed": completed}

    async def _cycle_id(self, tenant_id: str, sid: str, day: date) -> str:
        async with self.pool.acquire() as c:
            wid = await c.fetchval("""SELECT workflow_id FROM autodesk.workflows WHERE tenant_id=$1
                                      AND idempotency_key=$2""", tenant_id, f"{sid}:{day.isoformat()}:cycle")
        if wid is None:
            raise store.Conflict(f"no session cycle for {day}")
        return wid

    async def run_to_end(self, *, tenant_id: str, sid: str, user_id: str = "system") -> dict:
        """Accelerated replay: step phase by phase until the end, a pause, a stop or a failure."""
        steps = 0
        while True:
            async with self.pool.acquire() as c:
                sim = await store.get_simulation(c, tenant_id, sid)
            if sim["status"] != C.SimulationStatus.RUNNING.value:
                break
            try:
                r = await self.step(tenant_id=tenant_id, sid=sid, unit="SESSION", user_id=user_id)
            except store.Conflict:   # paused / stopped mid-run, or another step holds the lock
                break
            steps += len(r["steps"])
            if not r["steps"]:
                break
        async with self.pool.acquire() as c:
            sim = await store.get_simulation(c, tenant_id, sid)
        return {"simulation_id": sid, "status": sim["status"], "phases_run": steps, "step_seq": sim["step_seq"]}

    # ── read side ───────────────────────────────────────────────────────────────────────────────────────────────

    async def results(self, *, tenant_id: str, sid: str) -> dict:
        async with self.pool.acquire() as c:
            sim = await store.get_simulation(c, tenant_id, sid)
            sig = await c.fetch("SELECT category, status, segment FROM autodesk.signals WHERE simulation_id=$1", sid)
            plans = await c.fetch("SELECT status, strategy_type FROM autodesk.trade_plans WHERE simulation_id=$1", sid)
            apr = await c.fetch("SELECT status, decided_by FROM autodesk.approvals WHERE simulation_id=$1", sid)
            tasks = await c.fetch("""SELECT to_agent, state, attempt, latency_ms, error FROM autodesk.agent_tasks
                                     WHERE simulation_id=$1""", sid)
            hand = await c.fetchval("SELECT count(*) FROM autodesk.agent_handoffs WHERE simulation_id=$1", sid)
            pm = await c.fetch("""SELECT session_date, outcome FROM autodesk.workflows WHERE simulation_id=$1
                                  AND kind='PREMARKET_CHECK' ORDER BY session_date""", sid)
            clock = await c.fetchval("SELECT count(*) FROM autodesk.simulation_clock_events WHERE simulation_id=$1", sid)
        agents: dict[str, dict] = defaultdict(lambda: {"tasks": 0, "completed": 0, "failed": 0, "escalated": 0,
                                                       "rejected": 0, "retried": 0, "latency_ms": []})
        violations = 0
        for t in tasks:
            a = agents[t["to_agent"]]
            a["tasks"] += 1
            a["completed"] += t["state"] == "COMPLETED"
            a["failed"] += t["state"] == "FAILED"
            a["escalated"] += t["state"] == "ESCALATED"
            a["rejected"] += t["state"] == "REJECTED"
            a["retried"] += (t["attempt"] or 0) > 1
            if t["latency_ms"] is not None:
                a["latency_ms"].append(t["latency_ms"])
            if t["error"] and ("ToolNotAllowed" in t["error"] or "LookAheadError" in t["error"]):
                violations += 1
        for a in agents.values():
            lat = a.pop("latency_ms")
            a["avg_latency_ms"] = round(sum(lat) / len(lat)) if lat else None
        pm_status = Counter(((r["outcome"] or {}).get("premarket") or {}).get("status", "UNKNOWN") for r in pm)
        lim = list(LIMITATIONS if self.execution is None else
                   PHASE3_LIMITATIONS if getattr(self.execution, "lifecycle", None) is not None else PHASE2_LIMITATIONS)
        if sim["config"].get("universe", "FNO") != "FNO" and not sim["config"].get("symbols"):
            lim.append("Index universes use today's index members (membership has no history): survivorship bias.")
        out = {
            "simulation_id": sid, "status": sim["status"], "mode": sim["mode"],
            "sessions_total": len(sim["config"].get("sessions", [])), "phases_run": clock,
            "premarket": dict(pm_status),
            "signals": {"total": len(sig), "by_category": dict(Counter(r["category"] for r in sig)),
                        "by_status": dict(Counter(r["status"] for r in sig)),
                        "by_segment": dict(Counter(r["segment"] for r in sig))},
            "plans": {"total": len(plans), "by_status": dict(Counter(r["status"] for r in plans)),
                      "by_strategy": dict(Counter(r["strategy_type"] for r in plans))},
            "approvals": {"by_status": dict(Counter(r["status"] for r in apr)),
                          "by_decider": dict(Counter(r["decided_by"].split("@")[0].split(":")[0] for r in apr))},
            "agents": dict(agents), "handoffs": hand, "policy_violation_attempts": violations,
            "versions": sim["versions"], "data": {"first_session": (sim["config"].get("sessions") or [None])[0],
                                                  "last_session": (sim["config"].get("sessions") or [None])[-1],
                                                  "universe": sim["config"].get("universe"),
                                                  "symbols": sim["config"].get("symbols")},
            "limitations": lim,
            "execution": "none in Phase 1 (no orders, fills or P&L)",
        }
        if self.execution is not None:
            from ..execution import reports
            async with self.pool.acquire() as c:
                out["execution_summary"] = await reports.execution_summary(c, tenant_id, sid, self.execution.params)
            out["execution"] = "paper execution: simulated fills, see execution_summary"
        return out


def _plain(v: Any) -> Any:
    if isinstance(v, dict):
        return {k: _plain(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_plain(x) for x in v]
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return str(v)
    return v
