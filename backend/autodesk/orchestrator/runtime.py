"""Task runtime: runs one agent task through the PRD task lifecycle (PRD §29.2, architecture §11.3).

  CREATED (persisted before dispatch) → ASSIGNED → ACCEPTED → RUNNING → RESULT_READY → VALIDATED → COMPLETED
  agent refuses the task          → REJECTED
  deadline passed                 → TIMED_OUT → RETRY_PENDING → ASSIGNED … (bounded) → ESCALATED
  agent raised                    → RETRY_PENDING … → FAILED (LookAheadError / ToolNotAllowed fail at once: defects)
  output fails schema or domain   → RETRY_PENDING … → FAILED   (an invalid output is never used downstream)
  agent reports BLOCKED/ESCALATED → BLOCKED → ESCALATED / ESCALATED

Each transition is its own short transaction, so the task's state is durable while the agent runs. The agent itself
runs outside any transaction and cannot write. On success, `persist(conn, parsed)` stores the domain records in the
same transaction as VALIDATED → COMPLETED.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from pydantic import BaseModel, ValidationError

from .. import contracts as C
from .. import store
from ..agents.base import Agent, AgentContext
from ..market.view import LookAheadError, ToolNotAllowed

log = logging.getLogger(__name__)

ContextBuilder = Callable[[C.TaskSpec], Awaitable[AgentContext]]
DomainCheck = Callable[[C.TaskSpec, BaseModel, AgentContext], list[str]]
Persist = Callable[[Any, BaseModel, dict], Awaitable[Optional[str]]]   # (conn, parsed, task_row) -> result_ref


@dataclass
class TaskOutcome:
    task: dict
    ok: bool
    output: Optional[BaseModel] = None
    result: Optional[C.AgentResult] = None
    error: Optional[str] = None

    @property
    def state(self) -> str:
        return self.task["state"]


class TaskRunner:
    def __init__(self, pool, agents: dict[C.AgentKey, Agent]):
        self.pool = pool
        self.agents = agents

    async def _move(self, spec: C.TaskSpec, to: C.TaskState, **fields) -> dict:
        async with self.pool.acquire() as c:
            async with c.transaction():
                return await store.transition_task(c, tenant_id=spec.tenant_id, task_id=spec.task_id, to=to,
                                                   producer=spec.to_agent.value if to != C.TaskState.ASSIGNED
                                                   else C.ORCHESTRATOR, fields=fields or None)

    async def _agent_status(self, agent: Agent, status: C.AgentStatus) -> None:
        try:
            async with self.pool.acquire() as c:
                await store.set_agent_status(c, agent.descriptor.agent_key.value, agent.descriptor.version, status)
        except Exception as e:  # status is informational; never fail a task on it
            log.warning("agent status update failed: %s", e)

    async def run(self, spec: C.TaskSpec, *, step: str, build_context: ContextBuilder,
                  domain_check: Optional[DomainCheck] = None, persist: Optional[Persist] = None) -> TaskOutcome:
        agent = self.agents.get(spec.to_agent)
        async with self.pool.acquire() as c:
            async with c.transaction():
                row, created = await store.create_task(c, spec, step=step)
        if not created and C.TaskState(row["state"]) in C.TASK_TERMINAL:
            return TaskOutcome(task=row, ok=row["state"] == C.TaskState.COMPLETED.value, error=row.get("error"))
        if agent is None:
            row = await self._move(spec, C.TaskState.CANCELLED, error=f"no agent registered for {spec.to_agent.value}")
            return TaskOutcome(task=row, ok=False, error=row["error"])

        d = agent.descriptor
        last_error: Optional[str] = None
        for attempt in range(1, spec.max_attempts + 1):
            row = await self._move(spec, C.TaskState.ASSIGNED, attempt=attempt)
            try:
                ctx = await build_context(spec)
            except Exception as e:  # inputs could not be resolved: the task cannot run at all
                last_error = f"context: {type(e).__name__}: {e}"
                row = await self._move(spec, C.TaskState.ESCALATED, error=last_error)
                return TaskOutcome(task=row, ok=False, error=last_error)
            reason = agent.accept(spec, ctx)
            if reason:
                row = await self._move(spec, C.TaskState.REJECTED, error=f"rejected by agent: {reason}")
                return TaskOutcome(task=row, ok=False, error=row["error"])
            await self._move(spec, C.TaskState.ACCEPTED, agent_version=d.version, model=d.model,
                             prompt_version=d.prompt_version)
            await self._move(spec, C.TaskState.RUNNING)
            restricted = agent.restrict(ctx.market)
            run_ctx = AgentContext(tenant_id=ctx.tenant_id, account=ctx.account, policy=ctx.policy, market=restricted,
                                   as_of=ctx.as_of, simulation_id=ctx.simulation_id, workflow_id=ctx.workflow_id,
                                   inputs=ctx.inputs, settings=ctx.settings)
            calls_before = len(ctx.market.tool_calls())
            await self._agent_status(agent, C.AgentStatus.BUSY)
            try:
                result = await asyncio.wait_for(agent.run(spec, run_ctx), timeout=float(spec.deadline_s))
            except asyncio.TimeoutError:
                last_error = f"deadline {spec.deadline_s}s exceeded"
                calls = _calls(ctx, calls_before)
                await self._move(spec, C.TaskState.TIMED_OUT, error=last_error, tool_calls=calls)
                if attempt < spec.max_attempts:
                    await self._move(spec, C.TaskState.RETRY_PENDING)
                    continue
                row = await self._move(spec, C.TaskState.ESCALATED, error=f"{last_error} on every attempt")
                await self._agent_status(agent, C.AgentStatus.DEGRADED)
                return TaskOutcome(task=row, ok=False, error=row["error"])
            except (LookAheadError, ToolNotAllowed) as e:   # an agent defect: never retried
                last_error = f"{type(e).__name__}: {e}"
                row = await self._move(spec, C.TaskState.FAILED, error=last_error, tool_calls=_calls(ctx, calls_before))
                await self._agent_status(agent, C.AgentStatus.DEGRADED)
                return TaskOutcome(task=row, ok=False, error=last_error)
            except Exception as e:  # noqa: BLE001 — recorded on the task, retried within bounds
                last_error = f"{type(e).__name__}: {e}"
                log.warning("task %s attempt %d raised: %s", spec.task_id, attempt, last_error)
                if attempt < spec.max_attempts:
                    await self._move(spec, C.TaskState.RETRY_PENDING, error=last_error,
                                     tool_calls=_calls(ctx, calls_before))
                    continue
                row = await self._move(spec, C.TaskState.FAILED, error=last_error, tool_calls=_calls(ctx, calls_before))
                await self._agent_status(agent, C.AgentStatus.DEGRADED)
                return TaskOutcome(task=row, ok=False, error=last_error)
            finally:
                await self._agent_status(agent, C.AgentStatus.IDLE)

            calls = _calls(ctx, calls_before) + [tc.model_dump(mode="json") for tc in result.tool_calls]
            if result.outcome in ("BLOCKED", "ESCALATED"):
                last_error = result.reason or result.outcome.lower()
                if result.outcome == "BLOCKED":
                    await self._move(spec, C.TaskState.BLOCKED, error=last_error, tool_calls=calls,
                                     result_summary=result.summary)
                row = await self._move(spec, C.TaskState.ESCALATED, error=last_error, tool_calls=calls,
                                       result_summary=result.summary)
                return TaskOutcome(task=row, ok=False, result=result, error=last_error)
            if result.outcome == "REJECTED":
                # a task refusal after starting is recorded as an escalation (REJECTED is only valid at acceptance)
                last_error = f"agent declined: {result.reason}"
                row = await self._move(spec, C.TaskState.ESCALATED, error=last_error, tool_calls=calls,
                                       result_summary=result.summary)
                return TaskOutcome(task=row, ok=False, result=result, error=last_error)

            await self._move(spec, C.TaskState.RESULT_READY, result=result.output, result_summary=result.summary,
                             evidence_refs=result.evidence_refs, tool_calls=calls)
            errors: list[str] = []
            parsed: Optional[BaseModel] = None
            if result.output_schema != spec.required_output_schema:
                errors.append(f"output schema {result.output_schema!r} != required {spec.required_output_schema!r}")
            else:
                try:
                    parsed = C.OUTPUT_SCHEMAS[spec.required_output_schema].model_validate(result.output)
                except ValidationError as e:
                    errors.append("schema: " + "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}"
                                                         for x in e.errors()[:8]))
            if parsed is not None and domain_check is not None:
                errors.extend(domain_check(spec, parsed, ctx))
            if errors:
                last_error = " | ".join(errors)
                validation = {"schema_ok": parsed is not None, "domain_ok": False, "errors": errors}
                if attempt < spec.max_attempts:
                    await self._move(spec, C.TaskState.RETRY_PENDING, validation=validation, error=last_error)
                    continue
                # RESULT_READY → FAILED is allowed; the invalid output stays on the task only as evidence
                row = await self._move(spec, C.TaskState.FAILED, validation=validation, error=last_error)
                return TaskOutcome(task=row, ok=False, result=result, error=last_error)

            async with self.pool.acquire() as c:
                async with c.transaction():
                    row = await store.transition_task(c, tenant_id=spec.tenant_id, task_id=spec.task_id,
                                                      to=C.TaskState.VALIDATED, producer=C.ORCHESTRATOR,
                                                      fields={"validation": {"schema_ok": True, "domain_ok": True,
                                                                             "errors": []}})
                    ref = await persist(c, parsed, row) if persist is not None else None
                    row = await store.transition_task(c, tenant_id=spec.tenant_id, task_id=spec.task_id,
                                                      to=C.TaskState.COMPLETED, producer=C.ORCHESTRATOR,
                                                      fields={"result_ref": ref} if ref else None)
            return TaskOutcome(task=row, ok=True, output=parsed, result=result)

        row = await self._move(spec, C.TaskState.ESCALATED, error=last_error or "attempts exhausted")
        return TaskOutcome(task=row, ok=False, error=row["error"])


def _calls(ctx: AgentContext, start: int) -> list[dict]:
    return [tc.model_dump(mode="json") for tc in ctx.market.tool_calls()[start:]]


async def recover_interrupted(pool, *, older_than_s: float = 0.0) -> list[str]:
    """Fail closed after a restart (TESTCASES AD-68): any task this process did not finish — ASSIGNED, ACCEPTED,
    RUNNING, RESULT_READY, VALIDATED, RETRY_PENDING, TIMED_OUT, BLOCKED — is escalated, and its workflow, if still
    open, is failed. Nothing half-approved survives a restart. Returns the task ids touched."""
    touched: list[str] = []
    async with pool.acquire() as c:
        rows = await c.fetch(
            """SELECT task_id, tenant_id, state FROM autodesk.agent_tasks
               WHERE state IN ('CREATED','ASSIGNED','ACCEPTED','RUNNING','RESULT_READY','VALIDATED','RETRY_PENDING',
                               'TIMED_OUT','BLOCKED')
                 AND updated_at < now() - make_interval(secs => $1)""", older_than_s)
    path = {  # shortest legal route to ESCALATED from each state
        "CREATED": ["CANCELLED"], "ASSIGNED": ["ESCALATED"], "ACCEPTED": ["RETRY_PENDING", "ESCALATED"],
        "RUNNING": ["ESCALATED"], "RESULT_READY": ["RETRY_PENDING", "ESCALATED"],
        "VALIDATED": ["COMPLETED"],   # validated output was already persisted in the same transaction
        "RETRY_PENDING": ["ESCALATED"], "TIMED_OUT": ["ESCALATED"], "BLOCKED": ["ESCALATED"],
    }
    for r in rows:
        async with pool.acquire() as c:
            async with c.transaction():
                for st in path[r["state"]]:
                    await store.transition_task(c, tenant_id=r["tenant_id"], task_id=r["task_id"],
                                                to=C.TaskState(st), producer="RECOVERY",
                                                fields={"error": "interrupted by restart"} if st != "COMPLETED" else None)
        touched.append(r["task_id"])
    async with pool.acquire() as c:
        wfs = await c.fetch(
            """SELECT DISTINCT w.workflow_id, w.tenant_id FROM autodesk.workflows w
               JOIN autodesk.agent_tasks t ON t.workflow_id = w.workflow_id
               WHERE t.task_id = ANY($1::text[]) AND w.state IN ('CREATED','RUNNING')""", touched)
    for w in wfs:
        async with pool.acquire() as c:
            async with c.transaction():
                await store.set_workflow_state(c, tenant_id=w["tenant_id"], workflow_id=w["workflow_id"],
                                               state=C.WorkflowState.FAILED, producer="RECOVERY",
                                               error="interrupted by restart; no action was approved by it")
                await c.execute("""UPDATE autodesk.trade_plans SET status='REJECTED', updated_at=now()
                                   WHERE workflow_id=$1 AND status IN ('DRAFT','RISK_REVIEW','NEEDS_REVISION')""",
                                w["workflow_id"])
    return touched
