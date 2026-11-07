"""Desk Orchestrator (PRD §7, architecture §3.2): deterministic workflows that coordinate the five agents.

It coordinates; it does not calculate risk, approve or execute. Every agent output is schema-checked by the runtime
and domain-checked here before it is stored; a hard risk FAIL can never become an approval (DESIGN §6.3).

Workflows
  SESSION_CYCLE   one account, one session: phase_premarket → phase_scan → phase_proposals (the simulator calls the
                  phases at its clock steps; the desk API runs them back to back)
  PREMARKET_CHECK child: Tech Support → READY / DEGRADED / BLOCKED (BLOCKED ends the cycle: no new risk)
  MARKET_SCAN     child: AI Trader → signals (deduplicated)
  TRADE_PROPOSAL  child per signal: Trading Assistant → Risk & Ops (→ revise ≤ 2) → Middle Office → decision
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time as dtime, timedelta, timezone
from decimal import Decimal
from typing import Any, Awaitable, Callable, Optional

from .. import contracts as C
from .. import store
from ..agents.base import AgentContext
from ..market.view import IST, MarketView
from .runtime import TaskOutcome, TaskRunner, recover_interrupted

log = logging.getLogger(__name__)

MarketFactory = Callable[[datetime], MarketView]
BookLoader = Callable[..., Awaitable[Any]]

MAX_REVISIONS = 2
SCAN_PUBLISH_FLOOR = Decimal("50")     # signals below this are not stored at all (AI Trader suppresses them)
SESSION_CLOSE_IST = dtime(15, 30)
# Segments a signal of each kind can be traded in (an F&O stock's signal may still become a cash plan).
TRADABLE_IN = {"CASH": {"CASH", "FUTURES", "OPTIONS"}, "FUTURES": {"CASH", "FUTURES", "OPTIONS"},
               "OPTIONS": {"OPTIONS"}, "INDEX": {"FUTURES", "OPTIONS"}}


def session_close_utc(d: date) -> datetime:
    return datetime.combine(d, SESSION_CLOSE_IST, tzinfo=IST).astimezone(timezone.utc)


def reattemptable(wf: dict) -> bool:
    """A session cycle that ended BLOCKED at the pre-market stage — no scan, no proposals — produced nothing, so it
    must not use up the account's cycle for the session: a new request opens another attempt. Cycles that are
    RUNNING, COMPLETED or FAILED, or that got as far as a scan, are final (idempotent as before)."""
    out = wf.get("outcome") or {}
    return wf["state"] == C.WorkflowState.BLOCKED.value and "scan" not in out and "proposals" not in out


def _j(v: Any) -> Any:
    """JSON-mode view of a model / value."""
    return v.model_dump(mode="json") if hasattr(v, "model_dump") else v


class Orchestrator:
    def __init__(self, pool, agents: dict, market_factory: MarketFactory, *, settings=None,
                 load_book: Optional[BookLoader] = None, scope_builder: Optional[Callable[..., C.ApprovalScope]] = None,
                 task_deadline_s: float = 30.0, execution: Any = None):
        self.pool = pool
        self.agents = agents
        self.market_factory = market_factory
        self.settings = settings
        self.runner = TaskRunner(pool, agents)
        self._load_book = load_book
        self._scope_builder = scope_builder
        self.execution = execution          # execution.gateway.ExecutionGateway, or None: Phase 1 behaviour (plans stop at APPROVED)
        self.task_deadline_s = task_deadline_s
        self.scan_deadline_s = max(task_deadline_s, float(getattr(settings, "scan_deadline_s", 600.0) or 600.0))

    async def _execute(self, *, tenant_id: str, trade_id: str, plan_version: int, approval_id: str, as_of: datetime,
                       simulation_id: Optional[str]) -> Optional[dict]:
        """Hand an approved plan to the execution gateway: intent, controls, reservation, orders. On the live desk the
        orders are also submitted now; in a simulation they are submitted at the OPEN phase. None without a gateway."""
        if self.execution is None:
            return None
        intent = await self.execution.create_intent(tenant_id=tenant_id, trade_id=trade_id, plan_version=plan_version,
                                                    approval_id=approval_id, as_of=as_of)
        if intent["status"] == "VALIDATED" and simulation_id is None:
            intent = await self.execution.submit(tenant_id=tenant_id, intent_id=intent["intent_id"], as_of=as_of)
        return {"intent_id": intent["intent_id"], "status": intent["status"], "refusal_codes": intent["refusal_codes"],
                "reservation_id": intent["reservation_id"]}

    # ── wiring helpers ──────────────────────────────────────────────────────────────────────────────────────────

    async def load_book(self, c, tenant_id: str, account_id: str, as_of: datetime) -> Any:
        if self._load_book is None:
            from ..control.book import load_book
            self._load_book = load_book
        return await self._load_book(c, tenant_id, account_id, as_of)

    def build_scope(self, **kw) -> C.ApprovalScope:
        if self._scope_builder is None:
            from ..agents.middle_office import build_scope
            self._scope_builder = build_scope
        return self._scope_builder(**kw)

    async def register_agents(self) -> None:
        async with self.pool.acquire() as c:
            for a in self.agents.values():
                await store.register_agent(c, a.descriptor)

    async def recover(self) -> list[str]:
        return await recover_interrupted(self.pool)

    async def _ctx(self, *, tenant_id: str, wf: dict, as_of: datetime, inputs: dict,
                   policy_override: Optional[dict] = None) -> AgentContext:
        async with self.pool.acquire() as c:
            account = await store.get_account(c, tenant_id, wf["account_id"])
            pin = wf["input"]
            pol = await store.get_policy(c, tenant_id, pin["policy_id"], pin["policy_version"])
        body = dict(pol["body"])
        cap = (policy_override or {}).get("session_allowed_segments")
        if cap is not None:   # the pre-market report narrows (never widens) the policy for this session
            body["allowed_segments"] = [s for s in body["allowed_segments"] if s in cap]
        return AgentContext(tenant_id=tenant_id, account=account,
                            policy={"policy_id": pol["policy_id"], "version": pol["version"], "body": body},
                            market=self.market_factory(as_of), as_of=as_of, simulation_id=wf["simulation_id"],
                            workflow_id=wf["workflow_id"], inputs=inputs, settings=self.settings)

    def _spec(self, *, wf: dict, task_type: C.TaskType, as_of: datetime, entity_id: Optional[str] = None,
              input_refs: Optional[list[str]] = None, constraints: Optional[dict] = None, key: str) -> C.TaskSpec:
        return C.TaskSpec(workflow_id=wf["workflow_id"], simulation_id=wf["simulation_id"], tenant_id=wf["tenant_id"],
                          account_id=wf["account_id"], to_agent=C.TASK_OWNER[task_type], task_type=task_type,
                          entity_id=entity_id, input_refs=input_refs or [], constraints=constraints or {},
                          required_output_schema=C.TASK_OUTPUT_SCHEMA[task_type],
                          deadline_s=self.scan_deadline_s if task_type == C.TaskType.SCAN_MARKET else self.task_deadline_s,
                          sim_time=as_of if wf["simulation_id"] else None,
                          idempotency_key=f"{wf['workflow_id']}:{key}")

    async def _set_wf(self, tenant_id: str, wf_id: str, state: C.WorkflowState, *, outcome: Optional[dict] = None,
                      error: Optional[str] = None, producer: str = C.ORCHESTRATOR) -> dict:
        async with self.pool.acquire() as c:
            async with c.transaction():
                return await store.set_workflow_state(c, tenant_id=tenant_id, workflow_id=wf_id, state=state,
                                                      producer=producer, outcome=outcome, error=error)

    async def _child(self, cycle: dict, kind: C.WorkflowKind, key: str, *, as_of: datetime,
                     extra_input: Optional[dict] = None) -> tuple[dict, bool]:
        async with self.pool.acquire() as c:
            async with c.transaction():
                wf, created = await store.create_workflow(
                    c, tenant_id=cycle["tenant_id"], account_id=cycle["account_id"], kind=kind,
                    producer=C.ORCHESTRATOR, input={**cycle["input"], **(extra_input or {})},
                    simulation_id=cycle["simulation_id"], parent_workflow_id=cycle["workflow_id"],
                    correlation_id=cycle["correlation_id"], session_date=cycle["session_date"],
                    sim_time=as_of if cycle["simulation_id"] else None,
                    idempotency_key=f"{cycle['workflow_id']}:{key}")
                if created:
                    wf = await store.set_workflow_state(c, tenant_id=cycle["tenant_id"],
                                                        workflow_id=wf["workflow_id"], state=C.WorkflowState.RUNNING,
                                                        producer=C.ORCHESTRATOR)
        return wf, created

    # ── session cycle ───────────────────────────────────────────────────────────────────────────────────────────

    async def open_session_cycle(self, *, tenant_id: str, account_id: str, session_date: date, as_of: datetime,
                                 simulation_id: Optional[str] = None, universe: str = "FNO",
                                 symbols: Optional[list[str]] = None, max_proposals: Optional[int] = None,
                                 idempotency_key: Optional[str] = None, producer: str = C.ORCHESTRATOR) -> dict:
        async with self.pool.acquire() as c:
            async with c.transaction():
                account = await store.get_account(c, tenant_id, account_id)
                if (account["kind"] == C.AccountKind.SIMULATION.value) != (simulation_id is not None):
                    raise store.Conflict("simulation accounts run only inside their simulation")
                if simulation_id is not None and account["simulation_id"] != simulation_id:
                    raise store.Conflict("account does not belong to this simulation")
                if account["status"] != "ACTIVE":
                    raise store.Conflict(f"account is {account['status']}")
                pol = await store.get_policy(c, tenant_id, account["policy_id"])
                body = C.PolicyBody.model_validate(pol["body"])
                key = idempotency_key or f"{simulation_id or account_id}:{session_date.isoformat()}:cycle"
                attempt = 1
                if idempotency_key is None and simulation_id is None:
                    # A desk cycle that ended BLOCKED before any scan can be asked for again: attempt-2, attempt-3, …
                    # (the earlier workflows stay for the audit trail). One request at a time decides which key is next.
                    await c.execute("SELECT pg_advisory_xact_lock(hashtext($1))", key)
                    base, existing = key, await store.get_workflow_by_key(c, tenant_id, key)
                    while existing is not None and reattemptable(existing):
                        attempt += 1
                        key = f"{base}:attempt-{attempt}"
                        existing = await store.get_workflow_by_key(c, tenant_id, key)
                wf, created = await store.create_workflow(
                    c, tenant_id=tenant_id, account_id=account_id, kind=C.WorkflowKind.SESSION_CYCLE,
                    producer=producer, simulation_id=simulation_id, session_date=session_date,
                    sim_time=as_of if simulation_id else None, idempotency_key=key,
                    input={"session_date": session_date.isoformat(), "policy_id": pol["policy_id"],
                           "policy_version": pol["version"], "universe": universe, "symbols": symbols,
                           "max_proposals": max_proposals if max_proposals is not None
                           else body.max_proposals_per_session,
                           "operating_mode": account["operating_mode"],
                           **({"attempt": attempt} if attempt > 1 else {})})
                if created:
                    wf = await store.set_workflow_state(c, tenant_id=tenant_id, workflow_id=wf["workflow_id"],
                                                        state=C.WorkflowState.RUNNING, producer=producer)
        return wf

    async def _cycle(self, tenant_id: str, cycle_id: str) -> dict:
        async with self.pool.acquire() as c:
            wf = await store.get_workflow(c, tenant_id, cycle_id)
        if wf["kind"] != C.WorkflowKind.SESSION_CYCLE.value:
            raise store.Conflict("not a session cycle")
        return wf

    async def _db_ok(self) -> bool:
        try:
            async with self.pool.acquire() as c:
                return await c.fetchval("SELECT 1") == 1
        except Exception:  # noqa: BLE001
            return False

    async def phase_premarket(self, *, tenant_id: str, cycle_id: str, as_of: datetime) -> dict:
        cycle = await self._cycle(tenant_id, cycle_id)
        if cycle["state"] != C.WorkflowState.RUNNING.value:
            return {"skipped": f"cycle is {cycle['state']}"}
        sd = cycle["input"]["session_date"]
        wf, created = await self._child(cycle, C.WorkflowKind.PREMARKET_CHECK, "premarket", as_of=as_of)
        if not created and C.WorkflowState(wf["state"]) in C.WORKFLOW_TERMINAL:
            return wf["outcome"] or {}
        spec = self._spec(wf=wf, task_type=C.TaskType.PREMARKET_HEALTH_CHECK, as_of=as_of, key="ts")
        inputs = {"session_date": sd, "db_ok": await self._db_ok()}

        async def build(_s):
            return await self._ctx(tenant_id=tenant_id, wf=wf, as_of=as_of, inputs=inputs)

        def check(s, out: C.PremarketReport, ctx):
            return [] if out.session_date.isoformat() == sd else [f"report is for {out.session_date}, not {sd}"]

        res = await self.runner.run(spec, step="premarket", build_context=build, domain_check=check)
        if not res.ok:
            report = {"status": "BLOCKED", "allowed_segments": [], "reason": f"pre-market check did not complete: "
                                                                               f"{res.error}"}
        else:
            report = _j(res.output)
        blocked = report["status"] == C.HealthStatus.BLOCKED.value
        await self._set_wf(tenant_id, wf["workflow_id"],
                           C.WorkflowState.BLOCKED if blocked else C.WorkflowState.COMPLETED,
                           outcome={"premarket": report}, producer=C.AgentKey.TECH_SUPPORT.value)
        async with self.pool.acquire() as c:
            async with c.transaction():
                await store.emit(c, C.EventType.PREMARKET_BLOCKED if blocked else C.EventType.PREMARKET_READY,
                                 tenant_id=tenant_id, producer=C.ORCHESTRATOR, account_id=cycle["account_id"],
                                 simulation_id=cycle["simulation_id"], workflow_id=cycle["workflow_id"],
                                 correlation_id=cycle["correlation_id"],
                                 sim_time=as_of if cycle["simulation_id"] else None,
                                 payload={"session_date": sd, "status": report["status"],
                                          "allowed_segments": report.get("allowed_segments", [])})
                if blocked:
                    await store.set_workflow_state(c, tenant_id=tenant_id, workflow_id=cycle_id,
                                                   state=C.WorkflowState.BLOCKED, producer=C.ORCHESTRATOR,
                                                   outcome={"premarket": report, "result": "BLOCKED_NO_NEW_RISK"})
                else:
                    await store.set_workflow_state(c, tenant_id=tenant_id, workflow_id=cycle_id,
                                                   state=C.WorkflowState.RUNNING, producer=C.ORCHESTRATOR,
                                                   outcome={"premarket": report})
        return report

    async def phase_scan(self, *, tenant_id: str, cycle_id: str, as_of: datetime) -> dict:
        cycle = await self._cycle(tenant_id, cycle_id)
        if cycle["state"] != C.WorkflowState.RUNNING.value:
            return {"skipped": f"cycle is {cycle['state']}"}
        if not (cycle["outcome"] or {}).get("premarket"):
            raise store.Conflict("the pre-market check has not run for this cycle")
        inp = cycle["input"]
        sd = inp["session_date"]
        wf, created = await self._child(cycle, C.WorkflowKind.MARKET_SCAN, "scan", as_of=as_of)
        if not created and C.WorkflowState(wf["state"]) in C.WORKFLOW_TERMINAL:
            return wf["outcome"] or {}
        spec = self._spec(wf=wf, task_type=C.TaskType.SCAN_MARKET, as_of=as_of, key="ait",
                          constraints={"universe": inp["universe"]})
        inputs = {"session_date": sd, "universe": inp["universe"], "symbols": inp.get("symbols"),
                  "min_score": str(SCAN_PUBLISH_FLOOR)}

        async def build(_s):
            return await self._ctx(tenant_id=tenant_id, wf=wf, as_of=as_of, inputs=inputs)

        def check(s, out: C.ScanReport, ctx):
            errs = []
            if out.session_date.isoformat() != sd:
                errs.append(f"scan is for {out.session_date}, not {sd}")
            for sig in out.signals:
                if sig.tenant_id != tenant_id:
                    errs.append(f"{sig.instrument}: wrong tenant")
                if sig.simulation_id != cycle["simulation_id"]:
                    errs.append(f"{sig.instrument}: simulation id mismatch")
                if sig.account_id not in (None, cycle["account_id"]):
                    errs.append(f"{sig.instrument}: wrong account")
                if sig.data_as_of > as_of:
                    errs.append(f"{sig.instrument}: data_as_of {sig.data_as_of} is after {as_of} (future data)")
                if sig.session_date.isoformat() != sd:
                    errs.append(f"{sig.instrument}: session_date mismatch")
            return errs

        async def persist(c, out: C.ScanReport, task_row):
            stored = 0
            for sig in out.signals:
                sig = sig.model_copy(update={"account_id": cycle["account_id"]})
                _, created_sig = await store.insert_signal(c, sig, workflow_id=wf["workflow_id"],
                                                           task_id=task_row["task_id"],
                                                           producer=C.AgentKey.AI_TRADER.value)
                stored += int(created_sig)
            return f"scan://{wf['workflow_id']}?signals={stored}"

        res = await self.runner.run(spec, step="scan", build_context=build, domain_check=check, persist=persist)
        if not res.ok:
            await self._set_wf(tenant_id, wf["workflow_id"], C.WorkflowState.FAILED, error=res.error)
            await self._set_wf(tenant_id, cycle_id, C.WorkflowState.FAILED, error=f"scan failed: {res.error}")
            return {"error": res.error}
        out: C.ScanReport = res.output
        summary = {"universe": out.universe, "universe_size": out.universe_size, "scanned": out.scanned,
                   "signals": len(out.signals), "suppressed": len(out.suppressed), "scan_task_id": spec.task_id,
                   "data_as_of": out.data_as_of.isoformat(), "rule_version": out.rule_version}
        await self._set_wf(tenant_id, wf["workflow_id"], C.WorkflowState.COMPLETED, outcome=summary,
                           producer=C.AgentKey.AI_TRADER.value)
        await self._set_wf(tenant_id, cycle_id, C.WorkflowState.RUNNING,
                           outcome={**(cycle["outcome"] or {}), "scan": summary})
        return summary

    async def phase_proposals(self, *, tenant_id: str, cycle_id: str, as_of: datetime) -> dict:
        cycle = await self._cycle(tenant_id, cycle_id)
        if cycle["state"] != C.WorkflowState.RUNNING.value:
            return {"skipped": f"cycle is {cycle['state']}"}
        outcome = cycle["outcome"] or {}
        if "scan" not in outcome:
            raise store.Conflict("the scan has not run for this cycle")
        inp = cycle["input"]
        async with self.pool.acquire() as c:
            pol = await store.get_policy(c, tenant_id, inp["policy_id"], inp["policy_version"])
            scan_wf = await c.fetchrow("""SELECT workflow_id FROM autodesk.workflows WHERE parent_workflow_id=$1
                                          AND kind='MARKET_SCAN' AND tenant_id=$2""", cycle_id, tenant_id)
            scan_task = await store.get_task(c, tenant_id, outcome["scan"]["scan_task_id"])
            rows = await c.fetch(
                """SELECT * FROM autodesk.signals WHERE tenant_id=$1 AND workflow_id=$2 AND status='DETECTED'
                   AND signal_score >= $3 ORDER BY signal_score DESC, instrument, category""",
                tenant_id, scan_wf["workflow_id"], Decimal(str(pol["body"]["min_signal_score"])))
            stop = await store.entries_stopped(c, tenant_id, cycle["simulation_id"])
            if stop:
                await store.emit(c, C.EventType.ENTRIES_STOPPED, tenant_id=tenant_id, producer=C.ORCHESTRATOR,
                                 account_id=cycle["account_id"], workflow_id=cycle_id,
                                 payload={"stage": "proposals", "candidates": len(rows), "reason": stop["reason"]})
        if stop:
            summary = {"candidates": len(rows), "proposed": 0, "results": [],
                       "held_back": f"STOP_NEW_ENTRIES is active ({stop['reason']})"}
            await self._set_wf(tenant_id, cycle_id, C.WorkflowState.COMPLETED,
                               outcome={**outcome, "proposals": summary, "result": "CYCLE_COMPLETED"})
            return summary
        allowed = set((outcome.get("premarket") or {}).get("allowed_segments") or [])
        chosen, seen = [], set()
        for r in rows:
            if r["instrument"] in seen:
                continue
            if not (TRADABLE_IN[r["segment"]] & allowed):
                continue
            seen.add(r["instrument"])
            chosen.append(dict(r))
            if len(chosen) >= int(inp["max_proposals"]):
                break
        results = []
        for sig in chosen:
            wf = await self.run_trade_proposal(tenant_id=tenant_id, cycle=cycle, signal=sig, as_of=as_of,
                                               scan_task=scan_task)
            results.append({"workflow_id": wf["workflow_id"], "instrument": sig["instrument"], "state": wf["state"],
                            "result": (wf["outcome"] or {}).get("result")})
        summary = {"candidates": len(rows), "proposed": len(chosen), "results": results}
        await self._set_wf(tenant_id, cycle_id, C.WorkflowState.COMPLETED,
                           outcome={**outcome, "proposals": summary, "result": "CYCLE_COMPLETED"})
        return summary

    async def run_session_cycle(self, *, tenant_id: str, account_id: str, session_date: date, as_of: datetime,
                                simulation_id: Optional[str] = None, universe: str = "FNO",
                                symbols: Optional[list[str]] = None, max_proposals: Optional[int] = None,
                                idempotency_key: Optional[str] = None, producer: str = C.ORCHESTRATOR) -> dict:
        cycle = await self.open_session_cycle(tenant_id=tenant_id, account_id=account_id, session_date=session_date,
                                              as_of=as_of, simulation_id=simulation_id, universe=universe,
                                              symbols=symbols, max_proposals=max_proposals,
                                              idempotency_key=idempotency_key, producer=producer)
        for phase in (self.phase_premarket, self.phase_scan, self.phase_proposals):
            cycle = await self._cycle(tenant_id, cycle["workflow_id"])
            if cycle["state"] != C.WorkflowState.RUNNING.value:
                break
            await phase(tenant_id=tenant_id, cycle_id=cycle["workflow_id"], as_of=as_of)
        return await self._cycle(tenant_id, cycle["workflow_id"])

    # ── trade proposal ──────────────────────────────────────────────────────────────────────────────────────────

    async def run_trade_proposal(self, *, tenant_id: str, cycle: dict, signal: dict, as_of: datetime,
                                 scan_task: Optional[dict] = None) -> dict:
        sd = cycle["input"]["session_date"]
        async with self.pool.acquire() as c:
            stop = await store.entries_stopped(c, tenant_id, cycle["simulation_id"])
        if stop:
            raise store.Conflict(f"new entries are stopped (STOP_NEW_ENTRIES: {stop['reason']})")
        sig_model = C.Signal.model_validate(signal["body"])
        allowed = (cycle["outcome"] or {}).get("premarket", {}).get("allowed_segments")
        override = {"session_allowed_segments": list(allowed)} if allowed is not None else None
        wf, created = await self._child(cycle, C.WorkflowKind.TRADE_PROPOSAL, f"proposal:{signal['signal_id']}",
                                        as_of=as_of, extra_input={"signal_id": signal["signal_id"],
                                                                  "policy_override": override})
        if not created:
            return wf
        async with self.pool.acquire() as c:
            async with c.transaction():
                await store.set_signal_status(c, tenant_id=tenant_id, signal_id=signal["signal_id"],
                                              status=C.SignalStatus.CONSUMED, producer=C.ORCHESTRATOR)
        sig_json = _j(sig_model)
        session_close = session_close_utc(date.fromisoformat(sd))

        def ctx_for(inputs):
            async def build(_s):
                return await self._ctx(tenant_id=tenant_id, wf=wf, as_of=as_of, inputs=inputs,
                                       policy_override=override)
            return build

        def plan_check(s, out: C.StrategyProposal, ctx):
            if out.decision == "NO_TRADE":
                return []
            p = out.plan
            errs = []
            if p.account_id != wf["account_id"]:
                errs.append("plan is for another account")
            if p.signal_id != signal["signal_id"]:
                errs.append("plan does not reference the task's signal")
            if len(p.legs) > int(ctx.policy["body"]["max_legs"]):
                errs.append("more legs than the policy allows")
            if p.plan_expires_at > session_close + timedelta(minutes=1):
                errs.append("plan validity runs past the session close")
            if not p.provenance:
                errs.append("plan has no provenance")
            return errs

        async def fail(reason: str, plan_id: Optional[str] = None) -> dict:
            if plan_id:
                async with self.pool.acquire() as c:
                    await store.set_plan_status(c, tenant_id=tenant_id, trade_id=plan_id, status=C.PlanStatus.REJECTED)
            return await self._set_wf(tenant_id, wf["workflow_id"], C.WorkflowState.FAILED, error=reason,
                                      outcome={"result": "FAILED", "reason": reason, "trade_id": plan_id})

        async def handoff(frm: Optional[dict], to: dict, entity: Optional[str]):
            if frm is None:
                return
            async with self.pool.acquire() as c:
                async with c.transaction():
                    await store.record_handoff(c, tenant_id=tenant_id, workflow_id=wf["workflow_id"],
                                               simulation_id=wf["simulation_id"], from_task=frm, to_task=to,
                                               entity_id=entity)

        # 1. strategy
        spec = self._spec(wf=wf, task_type=C.TaskType.GENERATE_STRATEGY, as_of=as_of, entity_id=signal["signal_id"],
                          input_refs=[f"signal://{signal['signal_id']}"], key="ta:0")
        res = await self.runner.run(spec, step="plan", build_context=ctx_for({"session_date": sd, "signal": sig_json}),
                                    domain_check=plan_check)
        await handoff(scan_task, res.task, signal["signal_id"])
        if not res.ok:
            return await fail(f"strategy task: {res.error}")
        prop: C.StrategyProposal = res.output
        if prop.decision == "NO_TRADE":
            return await self._set_wf(tenant_id, wf["workflow_id"], C.WorkflowState.COMPLETED,
                                      outcome={"result": "NO_TRADE", "reasons": prop.reasons, "stage": "strategy"})
        async with self.pool.acquire() as c:
            async with c.transaction():
                plan = await store.create_plan(c, tenant_id=tenant_id, body=prop.plan,
                                               created_by=C.AgentKey.TRADING_ASSISTANT.value,
                                               simulation_id=wf["simulation_id"], workflow_id=wf["workflow_id"])
                await store.set_plan_status(c, tenant_id=tenant_id, trade_id=plan["trade_id"],
                                            status=C.PlanStatus.RISK_REVIEW)
        trade_id, version, body = plan["trade_id"], 1, prop.plan
        prev_task = res.task

        # 2. risk (with bounded revision)
        assessment: Optional[C.RiskAssessment] = None
        risk_task = None
        for revision in range(0, MAX_REVISIONS + 1):
            async with self.pool.acquire() as c:
                book = await self.load_book(c, tenant_id, wf["account_id"], as_of)
            book_json = book.to_json() if hasattr(book, "to_json") else _j(book)
            plan_ref = {"trade_id": trade_id, "version": version, "body": _j(body)}
            rspec = self._spec(wf=wf, task_type=C.TaskType.ASSESS_RISK, as_of=as_of, entity_id=trade_id,
                               input_refs=[f"plan://{trade_id}@{version}", f"book://{wf['account_id']}"],
                               key=f"risk:{version}")

            def risk_check(s, out: C.RiskAssessment, ctx, _v=version):
                errs = []
                if out.trade_id != trade_id or out.plan_version != _v:
                    errs.append("assessment is for another plan version")
                if out.account_id != wf["account_id"]:
                    errs.append("assessment is for another account")
                if out.simulation_id != wf["simulation_id"]:
                    errs.append("assessment simulation id mismatch")
                hard_fail = [ch.name for ch in out.checks if ch.hard and ch.outcome == C.CheckOutcome.FAIL]
                if out.verdict == C.RiskVerdict.PASS and hard_fail:
                    errs.append(f"verdict PASS with failed hard checks {hard_fail}")
                return errs

            async def risk_persist(c, out: C.RiskAssessment, task_row):
                await store.insert_risk_assessment(c, tenant_id=tenant_id, a=out, producer=C.AgentKey.RISK_OPS.value,
                                                   workflow_id=wf["workflow_id"])
                return f"assessment://{out.assessment_id}"

            rres = await self.runner.run(
                rspec, step="risk", domain_check=risk_check, persist=risk_persist,
                build_context=ctx_for({"session_date": sd, "plan": plan_ref, "book": book_json, "signal": sig_json}))
            await handoff(prev_task, rres.task, trade_id)
            if not rres.ok:
                return await fail(f"risk task: {rres.error}", trade_id)
            assessment, risk_task, prev_task = rres.output, rres.task, rres.task
            if assessment.verdict == C.RiskVerdict.PASS:
                break
            if revision == MAX_REVISIONS:
                async with self.pool.acquire() as c:
                    await store.set_plan_status(c, tenant_id=tenant_id, trade_id=trade_id, status=C.PlanStatus.REJECTED)
                return await self._set_wf(tenant_id, wf["workflow_id"], C.WorkflowState.COMPLETED, outcome={
                    "result": "NO_TRADE", "stage": "risk", "trade_id": trade_id, "plan_version": version,
                    "reasons": ["risk checks still failing after revisions: " + ", ".join(assessment.violations)]})
            async with self.pool.acquire() as c:
                await store.set_plan_status(c, tenant_id=tenant_id, trade_id=trade_id, status=C.PlanStatus.NEEDS_REVISION)
            vspec = self._spec(wf=wf, task_type=C.TaskType.REVISE_STRATEGY, as_of=as_of, entity_id=trade_id,
                               input_refs=[f"plan://{trade_id}@{version}", f"assessment://{assessment.assessment_id}"],
                               key=f"ta:{revision + 1}")
            vres = await self.runner.run(vspec, step="revise", domain_check=plan_check, build_context=ctx_for({
                "session_date": sd, "signal": sig_json, "plan": plan_ref, "assessment": _j(assessment),
                "revision": revision + 1}))
            await handoff(prev_task, vres.task, trade_id)
            if not vres.ok:
                return await fail(f"revision task: {vres.error}", trade_id)
            prev_task = vres.task
            if vres.output.decision == "NO_TRADE":
                async with self.pool.acquire() as c:
                    await store.set_plan_status(c, tenant_id=tenant_id, trade_id=trade_id, status=C.PlanStatus.REJECTED)
                return await self._set_wf(tenant_id, wf["workflow_id"], C.WorkflowState.COMPLETED, outcome={
                    "result": "NO_TRADE", "stage": "revision", "trade_id": trade_id, "reasons": vres.output.reasons})
            body = vres.output.plan
            async with self.pool.acquire() as c:
                async with c.transaction():
                    p = await store.revise_plan(c, tenant_id=tenant_id, trade_id=trade_id, body=body,
                                                created_by=C.AgentKey.TRADING_ASSISTANT.value,
                                                reason="risk: " + ", ".join(assessment.violations or
                                                                            [assessment.verdict.value]))
                    await store.set_plan_status(c, tenant_id=tenant_id, trade_id=trade_id,
                                                status=C.PlanStatus.RISK_REVIEW)
            version = p["current_version"]

        # 3. research mode stops before approval
        if wf["input"]["operating_mode"] == C.OperatingMode.RESEARCH.value:
            async with self.pool.acquire() as c:
                await store.set_plan_status(c, tenant_id=tenant_id, trade_id=trade_id, status=C.PlanStatus.RESEARCH_ONLY)
            return await self._set_wf(tenant_id, wf["workflow_id"], C.WorkflowState.COMPLETED, outcome={
                "result": "RESEARCH_ONLY", "trade_id": trade_id, "plan_version": version})

        # 4. approval (held back if STOP_NEW_ENTRIES was activated while this proposal ran)
        async with self.pool.acquire() as c:
            stop = await store.entries_stopped(c, tenant_id, wf["simulation_id"])
            if stop:
                async with c.transaction():
                    await store.set_plan_status(c, tenant_id=tenant_id, trade_id=trade_id,
                                                status=C.PlanStatus.REJECTED)
                    await store.emit(c, C.EventType.ENTRIES_STOPPED, tenant_id=tenant_id, producer=C.ORCHESTRATOR,
                                     account_id=wf["account_id"], workflow_id=wf["workflow_id"],
                                     correlation_id=trade_id,
                                     payload={"stage": "approval", "trade_id": trade_id, "plan_version": version,
                                              "reason": stop["reason"]})
        if stop:
            return await self._set_wf(tenant_id, wf["workflow_id"], C.WorkflowState.COMPLETED, outcome={
                "result": "ENTRIES_STOPPED", "trade_id": trade_id, "plan_version": version,
                "reason": f"STOP_NEW_ENTRIES is active ({stop['reason']})"})
        async with self.pool.acquire() as c:
            async with c.transaction():
                await store.set_plan_status(c, tenant_id=tenant_id, trade_id=trade_id,
                                            status=C.PlanStatus.AWAITING_APPROVAL)
                await store.emit(c, C.EventType.APPROVAL_REQUESTED, tenant_id=tenant_id, producer=C.ORCHESTRATOR,
                                 account_id=wf["account_id"], simulation_id=wf["simulation_id"],
                                 workflow_id=wf["workflow_id"], correlation_id=trade_id,
                                 sim_time=as_of if wf["simulation_id"] else None,
                                 payload={"trade_id": trade_id, "plan_version": version,
                                          "assessment_id": assessment.assessment_id})
        mspec = self._spec(wf=wf, task_type=C.TaskType.REVIEW_FOR_APPROVAL, as_of=as_of, entity_id=trade_id,
                           input_refs=[f"plan://{trade_id}@{version}", f"assessment://{assessment.assessment_id}"],
                           key=f"mo:{version}")

        def mo_check(s, out: C.ApprovalDecision, ctx, _v=version, _a=assessment):
            errs = []
            if out.trade_id != trade_id or out.plan_version != _v:
                errs.append("decision is for another plan version")
            if out.account_id != wf["account_id"] or out.simulation_id != wf["simulation_id"]:
                errs.append("decision account / simulation mismatch")
            if out.status == C.ApprovalStatus.APPROVED:
                # defence in depth: no approval without a PASS assessment of this exact version (AD-67)
                if _a.verdict != C.RiskVerdict.PASS or out.risk_assessment_id != _a.assessment_id:
                    errs.append("approval must reference the PASS assessment of this version")
                if out.scope.account_id != wf["account_id"] or out.scope.tenant_id != tenant_id:
                    errs.append("approval scope is for another account")
                if ctx.account["operating_mode"] != C.OperatingMode.AUTONOMOUS_PAPER.value:
                    errs.append("only AUTONOMOUS_PAPER accounts may be approved by the Middle Office")
            return errs

        async def mo_persist(c, out: C.ApprovalDecision, task_row):
            await store.insert_approval(c, tenant_id=tenant_id, d=out, producer=C.AgentKey.MIDDLE_OFFICE.value,
                                        workflow_id=wf["workflow_id"])
            return f"approval://{out.approval_id}"

        mres = await self.runner.run(mspec, step="approval", domain_check=mo_check, persist=mo_persist,
                                     build_context=ctx_for({"session_date": sd,
                                                            "plan": {"trade_id": trade_id, "version": version,
                                                                     "body": _j(body)},
                                                            "assessment": _j(assessment), "signal": sig_json}))
        await handoff(risk_task, mres.task, trade_id)
        if not mres.ok:
            return await fail(f"approval task: {mres.error}", trade_id)
        d: C.ApprovalDecision = mres.output
        if d.status == C.ApprovalStatus.APPROVED:
            async with self.pool.acquire() as c:
                await store.set_plan_status(c, tenant_id=tenant_id, trade_id=trade_id, status=C.PlanStatus.APPROVED)
            execution = await self._execute(tenant_id=tenant_id, trade_id=trade_id, plan_version=version,
                                            approval_id=d.approval_id, as_of=as_of, simulation_id=wf["simulation_id"])
            if execution is None:
                return await self._set_wf(tenant_id, wf["workflow_id"], C.WorkflowState.COMPLETED, outcome={
                    "result": "APPROVED_NO_EXECUTION", "trade_id": trade_id, "plan_version": version,
                    "approval_id": d.approval_id, "note": "no execution gateway is wired; the plan stops at APPROVED"},
                    producer=C.AgentKey.MIDDLE_OFFICE.value)
            return await self._set_wf(tenant_id, wf["workflow_id"], C.WorkflowState.COMPLETED, outcome={
                "result": "APPROVED", "trade_id": trade_id, "plan_version": version, "approval_id": d.approval_id,
                "execution": execution}, producer=C.AgentKey.MIDDLE_OFFICE.value)
        if d.status == C.ApprovalStatus.NEEDS_HUMAN_APPROVAL:
            return await self._set_wf(tenant_id, wf["workflow_id"], C.WorkflowState.WAITING_HUMAN, outcome={
                "result": "WAITING_HUMAN", "trade_id": trade_id, "plan_version": version,
                "approval_id": d.approval_id}, producer=C.AgentKey.MIDDLE_OFFICE.value)
        async with self.pool.acquire() as c:
            await store.set_plan_status(c, tenant_id=tenant_id, trade_id=trade_id, status=C.PlanStatus.REJECTED)
        return await self._set_wf(tenant_id, wf["workflow_id"], C.WorkflowState.COMPLETED, outcome={
            "result": d.status.value, "trade_id": trade_id, "plan_version": version, "approval_id": d.approval_id,
            "reasons": d.reasons}, producer=C.AgentKey.MIDDLE_OFFICE.value)

    # ── a person's decision on a pending approval ───────────────────────────────────────────────────────────────

    async def decide(self, *, tenant_id: str, approval_id: str, decision: str, reason: str, user_id: str,
                     now: Optional[datetime] = None, plan_hash: Optional[str] = None) -> dict:
        if decision not in ("APPROVE", "REJECT", "REQUEST_REVISION"):
            raise ValueError("decision must be APPROVE, REJECT or REQUEST_REVISION")
        async with self.pool.acquire() as c:
            async with c.transaction():
                req = await store.get_approval(c, tenant_id, approval_id)
                await c.execute("SELECT pg_advisory_xact_lock(hashtext($1))", approval_id)
                if req["status"] != C.ApprovalStatus.NEEDS_HUMAN_APPROVAL.value:
                    raise store.Conflict(f"approval {approval_id} is {req['status']}, not waiting for a person")
                if await store.is_answered(c, approval_id):
                    raise store.Conflict("this approval request has already been answered")
                if req["simulation_id"]:
                    sim = await store.get_simulation(c, tenant_id, req["simulation_id"])
                    if sim["status"] in ("STOPPED", "COMPLETED", "FAILED"):
                        raise store.Conflict(f"simulation is {sim['status']}")
                    now = sim["clock_sim_time"] or now
                now = now or datetime.now(timezone.utc)
                if req["expires_at"] and now > req["expires_at"]:
                    raise store.Conflict("the approval window has closed")
                plan = await store.get_plan(c, tenant_id, req["trade_id"])
                if plan["current_version"] != req["plan_version"]:
                    raise store.Conflict("the plan changed after this request; review the new version")
                wf = await store.get_workflow(c, tenant_id, plan["workflow_id"])
                if wf["state"] != C.WorkflowState.WAITING_HUMAN.value:
                    raise store.Conflict(f"workflow is {wf['state']}")
                account = await store.get_account(c, tenant_id, req["account_id"])
                assessment = await store.latest_risk_assessment(c, tenant_id, req["trade_id"], req["plan_version"])
                body = C.TradePlanBody.model_validate(plan["body"])
                if plan_hash is not None and plan_hash != C.plan_hash(body):
                    raise store.Conflict("the plan you reviewed is not the current version (plan hash differs)")
                if decision == "APPROVE":
                    stop = await store.entries_stopped(c, tenant_id, req["simulation_id"])
                    if stop:
                        raise store.Conflict(f"new entries are stopped (STOP_NEW_ENTRIES: {stop['reason']}); "
                                             "lift it to approve, or reject")
                    if account["status"] != "ACTIVE":
                        raise store.Conflict(f"account is {account['status']}")
                    if assessment is None or assessment["verdict"] != C.RiskVerdict.PASS.value:
                        raise store.Conflict("no PASS risk assessment for this plan version")
                    scope = self.build_scope(tenant_id=tenant_id, account=account, trade_id=req["trade_id"],
                                             plan_version=req["plan_version"], plan=body)
                    d = C.ApprovalDecision(trade_id=req["trade_id"], plan_version=req["plan_version"],
                                           account_id=req["account_id"], simulation_id=req["simulation_id"],
                                           status=C.ApprovalStatus.APPROVED, decided_by=f"user:{user_id}",
                                           reasons=[reason or "approved by a person"], scope=scope,
                                           risk_assessment_id=assessment["assessment_id"],
                                           expires_at=req["expires_at"] or body.plan_expires_at)
                    plan_status = C.PlanStatus.APPROVED
                    result = "APPROVED" if self.execution is not None else "APPROVED_NO_EXECUTION"
                elif decision == "REJECT":
                    d = C.ApprovalDecision(trade_id=req["trade_id"], plan_version=req["plan_version"],
                                           account_id=req["account_id"], simulation_id=req["simulation_id"],
                                           status=C.ApprovalStatus.REJECTED, decided_by=f"user:{user_id}",
                                           reasons=[reason or "rejected by a person"])
                    plan_status, result = C.PlanStatus.REJECTED, "REJECTED_BY_PERSON"
                else:
                    d = C.ApprovalDecision(trade_id=req["trade_id"], plan_version=req["plan_version"],
                                           account_id=req["account_id"], simulation_id=req["simulation_id"],
                                           status=C.ApprovalStatus.NEEDS_REVISION, decided_by=f"user:{user_id}",
                                           reasons=[reason or "revision requested"])
                    plan_status, result = C.PlanStatus.NEEDS_REVISION, "REVISION_REQUESTED"
                row = await store.insert_approval(c, tenant_id=tenant_id, d=d, producer=f"user:{user_id}",
                                                  workflow_id=wf["workflow_id"], supersedes_id=approval_id)
                await store.set_plan_status(c, tenant_id=tenant_id, trade_id=req["trade_id"], status=plan_status)
                await store.set_workflow_state(c, tenant_id=tenant_id, workflow_id=wf["workflow_id"],
                                               state=C.WorkflowState.COMPLETED, producer=f"user:{user_id}",
                                               outcome={**(wf["outcome"] or {}), "result": result,
                                                        "approval_id": d.approval_id})
        if decision == "APPROVE" and self.execution is not None:
            execution = await self._execute(tenant_id=tenant_id, trade_id=req["trade_id"], plan_version=req["plan_version"],
                                            approval_id=d.approval_id, as_of=now, simulation_id=req["simulation_id"])
            async with self.pool.acquire() as c:
                await c.execute("UPDATE autodesk.workflows SET outcome = COALESCE(outcome,'{}'::jsonb) || $3::jsonb, "
                                "updated_at=now() WHERE workflow_id=$1 AND tenant_id=$2", wf["workflow_id"], tenant_id,
                                __import__("json").dumps({"execution": execution}))
        return row

    # ── end of session (Phase 1: expire; Phase 2 adds reconciliation) ───────────────────────────────────────────

    async def close_session(self, *, tenant_id: str, account_id: str, session_date: date,
                            simulation_id: Optional[str], as_of: datetime) -> dict:
        counts = {"signals_expired": 0, "approvals_expired": 0, "plans_expired": 0, "workflows_expired": 0}
        async with self.pool.acquire() as c:
            async with c.transaction():
                sigs = await c.fetch("""SELECT signal_id FROM autodesk.signals WHERE tenant_id=$1 AND account_id=$2
                                        AND session_date=$3 AND status='DETECTED'
                                        AND simulation_id IS NOT DISTINCT FROM $4""",
                                     tenant_id, account_id, session_date, simulation_id)
                for s in sigs:
                    await store.set_signal_status(c, tenant_id=tenant_id, signal_id=s["signal_id"],
                                                  status=C.SignalStatus.EXPIRED, producer="SESSION_CLOSE",
                                                  reason="session closed")
                counts["signals_expired"] = len(sigs)
                pend = await c.fetch(
                    """SELECT a.* FROM autodesk.approvals a JOIN autodesk.workflows w
                         ON w.workflow_id = (SELECT workflow_id FROM autodesk.trade_plans WHERE trade_id=a.trade_id)
                       WHERE a.tenant_id=$1 AND a.account_id=$2 AND w.session_date=$3
                         AND a.status='NEEDS_HUMAN_APPROVAL'
                         AND NOT EXISTS (SELECT 1 FROM autodesk.approvals b WHERE b.supersedes_id=a.approval_id)""",
                    tenant_id, account_id, session_date)
                for a in pend:
                    d = C.ApprovalDecision(trade_id=a["trade_id"], plan_version=a["plan_version"],
                                           account_id=account_id, simulation_id=simulation_id,
                                           status=C.ApprovalStatus.REJECTED, decided_by="SYSTEM:session_close",
                                           reasons=["the approval window closed at the session close"])
                    await store.insert_approval(c, tenant_id=tenant_id, d=d, producer="SESSION_CLOSE",
                                                workflow_id=None, supersedes_id=a["approval_id"],
                                                event_type=C.EventType.APPROVAL_EXPIRED)
                counts["approvals_expired"] = len(pend)
                plans = await c.fetch(
                    """UPDATE autodesk.trade_plans p SET status='EXPIRED', updated_at=now()
                       FROM autodesk.workflows w
                       WHERE p.workflow_id=w.workflow_id AND p.tenant_id=$1 AND p.account_id=$2
                         AND w.session_date=$3 AND p.status IN ('AWAITING_APPROVAL','APPROVED','DRAFT','RISK_REVIEW',
                                                                'NEEDS_REVISION')
                       RETURNING p.trade_id""", tenant_id, account_id, session_date)
                counts["plans_expired"] = len(plans)
                wfs = await c.fetch("""SELECT workflow_id, outcome FROM autodesk.workflows WHERE tenant_id=$1
                                       AND account_id=$2 AND session_date=$3 AND state='WAITING_HUMAN'""",
                                    tenant_id, account_id, session_date)
                for w in wfs:
                    await store.set_workflow_state(c, tenant_id=tenant_id, workflow_id=w["workflow_id"],
                                                   state=C.WorkflowState.COMPLETED, producer="SESSION_CLOSE",
                                                   outcome={**(w["outcome"] or {}), "result": "EXPIRED"})
                counts["workflows_expired"] = len(wfs)
        return counts

    # ── re-run Risk & Ops on a stored plan version (POST /trade-plans/{id}/validate, POST /risk/assessments) ────────

    async def reassess(self, *, tenant_id: str, trade_id: str, version: Optional[int] = None,
                       as_of: Optional[datetime] = None) -> dict:
        """A fresh, stored assessment of one plan version. It changes no plan or approval state."""
        import uuid
        async with self.pool.acquire() as c:
            plan = await store.get_plan(c, tenant_id, trade_id, version)
            wf = await store.get_workflow(c, tenant_id, plan["workflow_id"])
            if wf["simulation_id"]:
                sim = await store.get_simulation(c, tenant_id, wf["simulation_id"])
                as_of = sim["clock_sim_time"] or as_of
            as_of = as_of or datetime.now(timezone.utc)
            book = await self.load_book(c, tenant_id, wf["account_id"], as_of)
            sig = await store.get_signal(c, tenant_id, plan["signal_id"]) if plan["signal_id"] else None
        v = plan["version"]
        spec = self._spec(wf=wf, task_type=C.TaskType.ASSESS_RISK, as_of=as_of, entity_id=trade_id,
                          input_refs=[f"plan://{trade_id}@{v}", f"book://{wf['account_id']}"],
                          key=f"reassess:{uuid.uuid4().hex[:12]}")
        inputs = {"session_date": wf["input"]["session_date"],
                  "plan": {"trade_id": trade_id, "version": v, "body": plan["body"]},
                  "book": book.to_json() if hasattr(book, "to_json") else _j(book),
                  "signal": sig["body"] if sig else None}
        override = wf["input"].get("policy_override")

        async def build(_s):
            return await self._ctx(tenant_id=tenant_id, wf=wf, as_of=as_of, inputs=inputs, policy_override=override)

        def check(s, out: C.RiskAssessment, ctx):
            return [] if (out.trade_id, out.plan_version) == (trade_id, v) else ["assessment is for another plan"]

        async def persist(c, out: C.RiskAssessment, task_row):
            await store.insert_risk_assessment(c, tenant_id=tenant_id, a=out, producer=C.AgentKey.RISK_OPS.value,
                                               workflow_id=wf["workflow_id"])
            return f"assessment://{out.assessment_id}"

        res = await self.runner.run(spec, step="reassess", build_context=build, domain_check=check, persist=persist)
        if not res.ok:
            raise store.Conflict(f"risk task did not complete: {res.error}")
        async with self.pool.acquire() as c:
            return await store.get_risk_assessment(c, tenant_id, res.output.assessment_id)
