"""Repository functions for the `autodesk` schema.

Rules:
- Every read filters by tenant_id (tenant isolation, PRD §18.1). A row of another tenant is "not found".
- Every state change appends an event in the SAME transaction (transactional outbox, architecture §6.3).
- Task state changes are checked against contracts.TASK_TRANSITIONS; an illegal move raises IllegalTransition.
- Immutable rows (plan versions, policy versions, risk assessments, approvals, events) are only ever INSERTed.

Functions take an asyncpg connection (`c`) so callers control the transaction; `autodesk.db.pool()` gives one.
"""
from __future__ import annotations

import hashlib
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

import asyncpg

from . import contracts as C
from .db import dumps


class NotFound(LookupError):
    pass


class IllegalTransition(RuntimeError):
    pass


class Conflict(RuntimeError):
    pass


def sha256(v: Any) -> str:
    return hashlib.sha256(dumps(v).encode()).hexdigest()


def _row(r: Optional[asyncpg.Record]) -> Optional[dict]:
    return dict(r) if r is not None else None


# ── events ───────────────────────────────────────────────────────────────────────────────────────────────────────────

async def append_event(c: asyncpg.Connection, ev: C.EventEnvelope) -> int:
    return await c.fetchval(
        """INSERT INTO autodesk.events (event_id, event_type, event_version, occurred_at, sim_time, tenant_id, account_id,
               simulation_id, workflow_id, correlation_id, causation_id, producer, payload)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13) RETURNING seq""",
        ev.event_id, ev.event_type.value, ev.event_version, ev.occurred_at, ev.sim_time, ev.tenant_id, ev.account_id,
        ev.simulation_id, ev.workflow_id, ev.correlation_id, ev.causation_id, ev.producer, ev.payload)


async def emit(c: asyncpg.Connection, event_type: C.EventType, *, tenant_id: str, producer: str,
               payload: Optional[dict] = None, account_id: Optional[str] = None, simulation_id: Optional[str] = None,
               workflow_id: Optional[str] = None, correlation_id: Optional[str] = None,
               causation_id: Optional[str] = None, sim_time: Optional[datetime] = None) -> int:
    return await append_event(c, C.EventEnvelope(
        event_type=event_type, tenant_id=tenant_id, producer=producer, payload=payload or {}, account_id=account_id,
        simulation_id=simulation_id, workflow_id=workflow_id, correlation_id=correlation_id, causation_id=causation_id,
        sim_time=sim_time))


async def list_events(c: asyncpg.Connection, tenant_id: str, *, simulation_id: Optional[str] = None,
                      workflow_id: Optional[str] = None, after_seq: int = 0, limit: int = 500) -> list[dict]:
    q = ["SELECT * FROM autodesk.events WHERE tenant_id=$1 AND seq>$2"]
    args: list[Any] = [tenant_id, after_seq]
    if simulation_id is not None:
        args.append(simulation_id); q.append(f"AND simulation_id=${len(args)}")
    if workflow_id is not None:
        args.append(workflow_id); q.append(f"AND workflow_id=${len(args)}")
    args.append(min(max(limit, 1), 5000)); q.append(f"ORDER BY seq LIMIT ${len(args)}")
    return [dict(r) for r in await c.fetch(" ".join(q), *args)]


# ── policies ─────────────────────────────────────────────────────────────────────────────────────────────────────────

async def create_policy(c: asyncpg.Connection, *, tenant_id: str, name: str, body: dict, created_by: str,
                        scope_type: str = "TENANT", scope_ref: Optional[str] = None, reason: str = "initial") -> dict:
    policy_id = C.new_id("POL")
    await c.execute("""INSERT INTO autodesk.policies (policy_id, tenant_id, name, scope_type, scope_ref, current_version)
                       VALUES ($1,$2,$3,$4,$5,1)""", policy_id, tenant_id, name, scope_type, scope_ref)
    await c.execute("""INSERT INTO autodesk.policy_versions (policy_id, version, body, body_sha256, created_by, reason)
                       VALUES ($1,1,$2,$3,$4,$5)""", policy_id, body, sha256(body), created_by, reason)
    await emit(c, C.EventType.POLICY_VERSION_CREATED, tenant_id=tenant_id, producer=created_by,
               payload={"policy_id": policy_id, "version": 1, "reason": reason})
    return {"policy_id": policy_id, "version": 1, "body": body}


async def add_policy_version(c: asyncpg.Connection, *, tenant_id: str, policy_id: str, body: dict, created_by: str,
                             reason: str) -> dict:
    head = await c.fetchrow("SELECT * FROM autodesk.policies WHERE policy_id=$1 AND tenant_id=$2 FOR UPDATE",
                            policy_id, tenant_id)
    if head is None:
        raise NotFound(policy_id)
    v = head["current_version"] + 1
    await c.execute("""INSERT INTO autodesk.policy_versions (policy_id, version, body, body_sha256, created_by, reason)
                       VALUES ($1,$2,$3,$4,$5,$6)""", policy_id, v, body, sha256(body), created_by, reason)
    await c.execute("UPDATE autodesk.policies SET current_version=$2, updated_at=now() WHERE policy_id=$1", policy_id, v)
    await emit(c, C.EventType.POLICY_VERSION_CREATED, tenant_id=tenant_id, producer=created_by,
               payload={"policy_id": policy_id, "version": v, "reason": reason})
    return {"policy_id": policy_id, "version": v, "body": body}


async def get_policy(c: asyncpg.Connection, tenant_id: str, policy_id: str, version: Optional[int] = None) -> dict:
    head = await c.fetchrow("SELECT * FROM autodesk.policies WHERE policy_id=$1 AND tenant_id=$2", policy_id, tenant_id)
    if head is None:
        raise NotFound(policy_id)
    v = version or head["current_version"]
    row = await c.fetchrow("SELECT * FROM autodesk.policy_versions WHERE policy_id=$1 AND version=$2", policy_id, v)
    if row is None:
        raise NotFound(f"{policy_id}@{v}")
    return {"policy_id": policy_id, "name": head["name"], "scope_type": head["scope_type"], "version": v,
            "current_version": head["current_version"], "body": row["body"], "body_sha256": row["body_sha256"],
            "created_at": row["created_at"], "created_by": row["created_by"], "reason": row["reason"]}


async def list_policies(c: asyncpg.Connection, tenant_id: str) -> list[dict]:
    return [dict(r) for r in await c.fetch(
        "SELECT * FROM autodesk.policies WHERE tenant_id=$1 ORDER BY created_at", tenant_id)]


# ── accounts ─────────────────────────────────────────────────────────────────────────────────────────────────────────

async def create_account(c: asyncpg.Connection, *, tenant_id: str, name: str, kind: C.AccountKind,
                         operating_mode: C.OperatingMode, starting_capital_rs: Decimal, policy_id: str,
                         created_by: str, simulation_id: Optional[str] = None) -> dict:
    account_id = C.new_id("ACC")
    await c.execute(
        """INSERT INTO autodesk.accounts (account_id, tenant_id, name, kind, operating_mode, starting_capital_rs,
               simulation_id, policy_id, created_by) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)""",
        account_id, tenant_id, name, kind.value, operating_mode.value, starting_capital_rs, simulation_id, policy_id,
        created_by)
    await emit(c, C.EventType.ACCOUNT_CREATED, tenant_id=tenant_id, producer=created_by, account_id=account_id,
               simulation_id=simulation_id,
               payload={"kind": kind.value, "operating_mode": operating_mode.value,
                        "starting_capital_rs": str(starting_capital_rs), "policy_id": policy_id})
    return await get_account(c, tenant_id, account_id)


async def get_account(c: asyncpg.Connection, tenant_id: str, account_id: str) -> dict:
    r = await c.fetchrow("SELECT * FROM autodesk.accounts WHERE account_id=$1 AND tenant_id=$2", account_id, tenant_id)
    if r is None:
        raise NotFound(account_id)
    return dict(r)


async def list_accounts(c: asyncpg.Connection, tenant_id: str, *, include_simulation: bool = False) -> list[dict]:
    q = "SELECT * FROM autodesk.accounts WHERE tenant_id=$1"
    if not include_simulation:
        q += " AND kind <> 'SIMULATION'"
    return [dict(r) for r in await c.fetch(q + " ORDER BY created_at", tenant_id)]


async def set_account_mode(c: asyncpg.Connection, *, tenant_id: str, account_id: str, mode: C.OperatingMode,
                           actor: str, reason: str) -> dict:
    cur = await get_account(c, tenant_id, account_id)
    if cur["kind"] == C.AccountKind.SIMULATION.value:
        raise Conflict("a simulation account's mode is fixed by its simulation config")
    await c.execute("UPDATE autodesk.accounts SET operating_mode=$3, updated_at=now() WHERE account_id=$1 AND tenant_id=$2",
                    account_id, tenant_id, mode.value)
    await emit(c, C.EventType.ACCOUNT_MODE_CHANGED, tenant_id=tenant_id, producer=actor, account_id=account_id,
               payload={"from": cur["operating_mode"], "to": mode.value, "reason": reason})
    return await get_account(c, tenant_id, account_id)


# ── agent registry ───────────────────────────────────────────────────────────────────────────────────────────────────

async def register_agent(c: asyncpg.Connection, d: C.AgentDescriptor) -> None:
    await c.execute(
        """INSERT INTO autodesk.agent_registry (agent_key, version, kind, model, prompt_version, descriptor)
           VALUES ($1,$2,$3,$4,$5,$6)
           ON CONFLICT (agent_key, version) DO UPDATE SET descriptor=EXCLUDED.descriptor""",
        d.agent_key.value, d.version, d.kind, d.model, d.prompt_version, d.model_dump(mode="json"))


async def set_agent_status(c: asyncpg.Connection, agent_key: str, version: str, status: C.AgentStatus) -> None:
    await c.execute("""UPDATE autodesk.agent_registry SET status=$3, last_heartbeat=now()
                       WHERE agent_key=$1 AND version=$2""", agent_key, version, status.value)


async def list_agents(c: asyncpg.Connection) -> list[dict]:
    return [dict(r) for r in await c.fetch("SELECT * FROM autodesk.agent_registry ORDER BY agent_key, registered_at DESC")]


# ── workflows ────────────────────────────────────────────────────────────────────────────────────────────────────────

async def create_workflow(c: asyncpg.Connection, *, tenant_id: str, account_id: str, kind: C.WorkflowKind,
                          producer: str, input: Optional[dict] = None, simulation_id: Optional[str] = None,
                          parent_workflow_id: Optional[str] = None, correlation_id: Optional[str] = None,
                          session_date: Optional[date] = None, sim_time: Optional[datetime] = None,
                          idempotency_key: Optional[str] = None) -> tuple[dict, bool]:
    """Returns (workflow, created). With an idempotency key already used, returns the existing workflow."""
    if idempotency_key:
        ex = await c.fetchrow("SELECT * FROM autodesk.workflows WHERE idempotency_key=$1 AND tenant_id=$2",
                              idempotency_key, tenant_id)
        if ex is not None:
            return dict(ex), False
    wid = C.new_id("WF")
    await c.execute(
        """INSERT INTO autodesk.workflows (workflow_id, tenant_id, account_id, simulation_id, kind, state,
               parent_workflow_id, correlation_id, session_date, sim_time, input, idempotency_key)
           VALUES ($1,$2,$3,$4,$5,'CREATED',$6,$7,$8,$9,$10,$11)""",
        wid, tenant_id, account_id, simulation_id, kind.value, parent_workflow_id, correlation_id or wid,
        session_date, sim_time, input or {}, idempotency_key)
    await emit(c, C.EventType.WORKFLOW_STARTED, tenant_id=tenant_id, producer=producer, account_id=account_id,
               simulation_id=simulation_id, workflow_id=wid, correlation_id=correlation_id or wid, sim_time=sim_time,
               payload={"kind": kind.value, "parent_workflow_id": parent_workflow_id,
                        "session_date": session_date.isoformat() if session_date else None})
    return await get_workflow(c, tenant_id, wid), True


async def get_workflow(c: asyncpg.Connection, tenant_id: str, workflow_id: str) -> dict:
    r = await c.fetchrow("SELECT * FROM autodesk.workflows WHERE workflow_id=$1 AND tenant_id=$2", workflow_id, tenant_id)
    if r is None:
        raise NotFound(workflow_id)
    return dict(r)


async def set_workflow_state(c: asyncpg.Connection, *, tenant_id: str, workflow_id: str, state: C.WorkflowState,
                             producer: str, outcome: Optional[dict] = None, error: Optional[str] = None) -> dict:
    cur = await c.fetchrow("SELECT * FROM autodesk.workflows WHERE workflow_id=$1 AND tenant_id=$2 FOR UPDATE",
                           workflow_id, tenant_id)
    if cur is None:
        raise NotFound(workflow_id)
    if C.WorkflowState(cur["state"]) in C.WORKFLOW_TERMINAL:
        raise IllegalTransition(f"workflow {workflow_id} is already {cur['state']}")
    terminal = state in C.WORKFLOW_TERMINAL
    await c.execute(
        """UPDATE autodesk.workflows SET state=$2, outcome=COALESCE($3, outcome), error=COALESCE($4, error),
               updated_at=now(), completed_at=CASE WHEN $5 THEN now() ELSE completed_at END WHERE workflow_id=$1""",
        workflow_id, state.value, outcome, error, terminal)
    await emit(c, C.EventType.WORKFLOW_FAILED if state == C.WorkflowState.FAILED else C.EventType.WORKFLOW_STATE_CHANGED,
               tenant_id=tenant_id, producer=producer, account_id=cur["account_id"], simulation_id=cur["simulation_id"],
               workflow_id=workflow_id, correlation_id=cur["correlation_id"], sim_time=cur["sim_time"],
               payload={"from": cur["state"], "to": state.value, "outcome": outcome, "error": error})
    return await get_workflow(c, tenant_id, workflow_id)


async def list_workflows(c: asyncpg.Connection, tenant_id: str, *, account_id: Optional[str] = None,
                         simulation_id: Optional[str] = None, parent_workflow_id: Optional[str] = None,
                         kind: Optional[str] = None, limit: int = 200) -> list[dict]:
    q, args = ["SELECT * FROM autodesk.workflows WHERE tenant_id=$1"], [tenant_id]
    for col, val in (("account_id", account_id), ("simulation_id", simulation_id),
                     ("parent_workflow_id", parent_workflow_id), ("kind", kind)):
        if val is not None:
            args.append(val); q.append(f"AND {col}=${len(args)}")
    args.append(min(max(limit, 1), 1000)); q.append(f"ORDER BY created_at LIMIT ${len(args)}")
    return [dict(r) for r in await c.fetch(" ".join(q), *args)]


# ── agent tasks ──────────────────────────────────────────────────────────────────────────────────────────────────────

async def create_task(c: asyncpg.Connection, spec: C.TaskSpec, *, step: Optional[str] = None) -> tuple[dict, bool]:
    """Persist BEFORE dispatch (handoff protocol step 2). Idempotent on spec.idempotency_key."""
    if spec.idempotency_key:
        ex = await c.fetchrow("SELECT * FROM autodesk.agent_tasks WHERE idempotency_key=$1 AND tenant_id=$2",
                              spec.idempotency_key, spec.tenant_id)
        if ex is not None:
            return dict(ex), False
    await c.execute(
        """INSERT INTO autodesk.agent_tasks (task_id, workflow_id, simulation_id, tenant_id, account_id, from_agent,
               to_agent, task_type, step, entity_id, input_refs, constraints, required_output_schema, state,
               max_attempts, deadline_s, sim_time, idempotency_key)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,'CREATED',$14,$15,$16,$17)""",
        spec.task_id, spec.workflow_id, spec.simulation_id, spec.tenant_id, spec.account_id, spec.from_agent,
        spec.to_agent.value, spec.task_type.value, step, spec.entity_id, spec.input_refs, spec.constraints,
        spec.required_output_schema, spec.max_attempts, spec.deadline_s, spec.sim_time, spec.idempotency_key)
    await emit(c, C.EventType.TASK_CREATED, tenant_id=spec.tenant_id, producer=C.ORCHESTRATOR,
               account_id=spec.account_id, simulation_id=spec.simulation_id, workflow_id=spec.workflow_id,
               sim_time=spec.sim_time,
               payload={"task_id": spec.task_id, "task_type": spec.task_type.value, "to_agent": spec.to_agent.value,
                        "from_agent": spec.from_agent, "entity_id": spec.entity_id, "step": step,
                        "input_refs": spec.input_refs})
    return await get_task(c, spec.tenant_id, spec.task_id), True


async def get_task(c: asyncpg.Connection, tenant_id: str, task_id: str) -> dict:
    r = await c.fetchrow("SELECT * FROM autodesk.agent_tasks WHERE task_id=$1 AND tenant_id=$2", task_id, tenant_id)
    if r is None:
        raise NotFound(task_id)
    return dict(r)


_TS_COLUMN = {C.TaskState.ASSIGNED: "assigned_at", C.TaskState.ACCEPTED: "accepted_at",
              C.TaskState.RUNNING: "started_at"}


async def transition_task(c: asyncpg.Connection, *, tenant_id: str, task_id: str, to: C.TaskState,
                          producer: str, fields: Optional[dict] = None) -> dict:
    """Move a task along TASK_TRANSITIONS. `fields` may set: result, result_summary, result_ref, evidence_refs,
    tool_calls, validation, error, agent_version, model, prompt_version, attempt."""
    cur = await c.fetchrow("SELECT * FROM autodesk.agent_tasks WHERE task_id=$1 AND tenant_id=$2 FOR UPDATE",
                           task_id, tenant_id)
    if cur is None:
        raise NotFound(task_id)
    frm = C.TaskState(cur["state"])
    if to not in C.TASK_TRANSITIONS[frm]:
        raise IllegalTransition(f"task {task_id}: {frm.value} → {to.value} is not allowed")
    allowed = {"result", "result_summary", "result_ref", "evidence_refs", "tool_calls", "validation", "error",
               "agent_version", "model", "prompt_version", "attempt"}
    fields = dict(fields or {})
    bad = set(fields) - allowed
    if bad:
        raise ValueError(f"unknown task fields: {sorted(bad)}")
    sets, args = ["state=$2", "updated_at=now()"], [task_id, to.value]
    for k, v in fields.items():
        args.append(v); sets.append(f"{k}=${len(args)}")
    if to in _TS_COLUMN:
        sets.append(f"{_TS_COLUMN[to]}=now()")
    if to in C.TASK_TERMINAL:
        sets.append("completed_at=now()")
        sets.append("latency_ms=(EXTRACT(EPOCH FROM (now()-created_at))*1000)::int")
    await c.execute(f"UPDATE autodesk.agent_tasks SET {', '.join(sets)} WHERE task_id=$1", *args)
    await emit(c, C.EventType.TASK_STATE_CHANGED, tenant_id=tenant_id, producer=producer,
               account_id=cur["account_id"], simulation_id=cur["simulation_id"], workflow_id=cur["workflow_id"],
               sim_time=cur["sim_time"],
               payload={"task_id": task_id, "task_type": cur["task_type"], "agent": cur["to_agent"],
                        "from": frm.value, "to": to.value, "error": fields.get("error"),
                        "summary": fields.get("result_summary")})
    return await get_task(c, tenant_id, task_id)


async def list_tasks(c: asyncpg.Connection, tenant_id: str, *, workflow_id: Optional[str] = None,
                     agent: Optional[str] = None, simulation_id: Optional[str] = None, limit: int = 200) -> list[dict]:
    q, args = ["SELECT * FROM autodesk.agent_tasks WHERE tenant_id=$1"], [tenant_id]
    for col, val in (("workflow_id", workflow_id), ("to_agent", agent), ("simulation_id", simulation_id)):
        if val is not None:
            args.append(val); q.append(f"AND {col}=${len(args)}")
    args.append(min(max(limit, 1), 2000)); q.append(f"ORDER BY created_at DESC LIMIT ${len(args)}")
    return [dict(r) for r in await c.fetch(" ".join(q), *args)]


async def record_handoff(c: asyncpg.Connection, *, tenant_id: str, workflow_id: str, simulation_id: Optional[str],
                         from_task: dict, to_task: dict, entity_id: Optional[str]) -> str:
    if from_task["workflow_id"] != workflow_id or to_task["workflow_id"] != workflow_id:
        raise Conflict("a handoff must stay inside one workflow")
    hid = C.new_id("HND")
    await c.execute(
        """INSERT INTO autodesk.agent_handoffs (handoff_id, workflow_id, simulation_id, tenant_id, from_task_id,
               to_task_id, from_agent, to_agent, entity_id) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)""",
        hid, workflow_id, simulation_id, tenant_id, from_task["task_id"], to_task["task_id"], from_task["to_agent"],
        to_task["to_agent"], entity_id)
    await emit(c, C.EventType.HANDOFF_RECORDED, tenant_id=tenant_id, producer=C.ORCHESTRATOR,
               simulation_id=simulation_id, workflow_id=workflow_id,
               payload={"handoff_id": hid, "from_task_id": from_task["task_id"], "to_task_id": to_task["task_id"],
                        "from_agent": from_task["to_agent"], "to_agent": to_task["to_agent"], "entity_id": entity_id})
    return hid


async def list_handoffs(c: asyncpg.Connection, tenant_id: str, *, workflow_id: Optional[str] = None,
                        simulation_id: Optional[str] = None) -> list[dict]:
    q, args = ["SELECT * FROM autodesk.agent_handoffs WHERE tenant_id=$1"], [tenant_id]
    if workflow_id is not None:
        args.append(workflow_id); q.append(f"AND workflow_id=${len(args)}")
    if simulation_id is not None:
        args.append(simulation_id); q.append(f"AND simulation_id=${len(args)}")
    return [dict(r) for r in await c.fetch(" ".join(q) + " ORDER BY created_at", *args)]


# ── signals ──────────────────────────────────────────────────────────────────────────────────────────────────────────

async def insert_signal(c: asyncpg.Connection, s: C.Signal, *, workflow_id: Optional[str], task_id: Optional[str],
                        producer: str) -> tuple[dict, bool]:
    """Duplicate suppression (AT-013): the dedupe key is unique; a second detection returns the first row."""
    key = s.dedupe_key()
    ex = await c.fetchrow("SELECT * FROM autodesk.signals WHERE dedupe_key=$1", key)
    if ex is not None:
        return dict(ex), False
    await c.execute(
        """INSERT INTO autodesk.signals (signal_id, tenant_id, account_id, simulation_id, workflow_id, task_id, instrument,
               exchange, segment, direction, timeframe, category, signal_score, calibrated_probability, body,
               session_date, data_as_of, rule_version, model_version, expires_at, status, dedupe_key)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22)""",
        s.signal_id, s.tenant_id, s.account_id, s.simulation_id, workflow_id, task_id, s.instrument, s.exchange,
        s.segment.value, s.direction.value, s.timeframe.value, s.category.value, s.signal_score,
        s.calibrated_probability, s.model_dump(mode="json"), s.session_date, s.data_as_of, s.rule_version,
        s.model_version, s.expires_at, s.status.value, key)
    await emit(c, C.EventType.SIGNAL_DETECTED, tenant_id=s.tenant_id, producer=producer, account_id=s.account_id,
               simulation_id=s.simulation_id, workflow_id=workflow_id,
               payload={"signal_id": s.signal_id, "instrument": s.instrument, "segment": s.segment.value,
                        "direction": s.direction.value, "category": s.category.value,
                        "signal_score": str(s.signal_score), "data_as_of": s.data_as_of.isoformat()})
    return await get_signal(c, s.tenant_id, s.signal_id), True


async def get_signal(c: asyncpg.Connection, tenant_id: str, signal_id: str) -> dict:
    r = await c.fetchrow("SELECT * FROM autodesk.signals WHERE signal_id=$1 AND tenant_id=$2", signal_id, tenant_id)
    if r is None:
        raise NotFound(signal_id)
    return dict(r)


async def set_signal_status(c: asyncpg.Connection, *, tenant_id: str, signal_id: str, status: C.SignalStatus,
                            producer: str, reason: str = "") -> None:
    r = await c.fetchrow("""UPDATE autodesk.signals SET status=$3, updated_at=now()
                            WHERE signal_id=$1 AND tenant_id=$2 RETURNING account_id, simulation_id, workflow_id""",
                         signal_id, tenant_id, status.value)
    if r is None:
        raise NotFound(signal_id)
    if status in (C.SignalStatus.EXPIRED, C.SignalStatus.SUPPRESSED):
        await emit(c, C.EventType.SIGNAL_EXPIRED if status == C.SignalStatus.EXPIRED else C.EventType.SIGNAL_SUPPRESSED,
                   tenant_id=tenant_id, producer=producer, account_id=r["account_id"],
                   simulation_id=r["simulation_id"], workflow_id=r["workflow_id"],
                   payload={"signal_id": signal_id, "reason": reason})


async def list_signals(c: asyncpg.Connection, tenant_id: str, *, simulation_id: Optional[str] = None,
                       account_id: Optional[str] = None, session_date: Optional[date] = None,
                       status: Optional[str] = None, segment: Optional[str] = None, min_score: Optional[Decimal] = None,
                       limit: int = 200) -> list[dict]:
    q, args = ["SELECT * FROM autodesk.signals WHERE tenant_id=$1"], [tenant_id]
    if simulation_id is not None:
        args.append(simulation_id); q.append(f"AND simulation_id=${len(args)}")
    else:
        q.append("AND simulation_id IS NULL")   # desk signals and simulated signals never mix in one list
    for col, val in (("account_id", account_id), ("session_date", session_date), ("status", status),
                     ("segment", segment)):
        if val is not None:
            args.append(val); q.append(f"AND {col}=${len(args)}")
    if min_score is not None:
        args.append(min_score); q.append(f"AND signal_score>=${len(args)}")
    args.append(min(max(limit, 1), 2000)); q.append(f"ORDER BY session_date DESC, signal_score DESC LIMIT ${len(args)}")
    return [dict(r) for r in await c.fetch(" ".join(q), *args)]


# ── trade plans ──────────────────────────────────────────────────────────────────────────────────────────────────────

async def create_plan(c: asyncpg.Connection, *, tenant_id: str, body: C.TradePlanBody, created_by: str,
                      simulation_id: Optional[str], workflow_id: Optional[str]) -> dict:
    trade_id = C.new_id("TRD")
    await c.execute(
        """INSERT INTO autodesk.trade_plans (trade_id, tenant_id, account_id, simulation_id, workflow_id, signal_id,
               instrument, strategy_type, current_version, status) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,1,'DRAFT')""",
        trade_id, tenant_id, body.account_id, simulation_id, workflow_id, body.signal_id, body.instrument,
        body.strategy_type.value)
    await _insert_version(c, trade_id, 1, body, created_by, None, None)
    await emit(c, C.EventType.TRADE_PLAN_CREATED, tenant_id=tenant_id, producer=created_by, account_id=body.account_id,
               simulation_id=simulation_id, workflow_id=workflow_id, correlation_id=trade_id,
               payload={"trade_id": trade_id, "version": 1, "strategy_type": body.strategy_type.value,
                        "instrument": body.instrument, "max_loss_rs": str(body.max_loss_rs)})
    return await get_plan(c, tenant_id, trade_id)


async def _insert_version(c, trade_id, version, body: C.TradePlanBody, created_by, reason, supersedes):
    data = body.model_dump(mode="json")
    await c.execute(
        """INSERT INTO autodesk.trade_plan_versions (trade_id, version, body, body_sha256, strategy_type, max_loss_rs,
               max_profit_rs, capital_required_rs, created_by, change_reason, supersedes_version)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)""",
        trade_id, version, data, sha256(data), body.strategy_type.value, body.max_loss_rs, body.max_profit_rs,
        body.capital_required_rs, created_by, reason, supersedes)


async def revise_plan(c: asyncpg.Connection, *, tenant_id: str, trade_id: str, body: C.TradePlanBody,
                      created_by: str, reason: str) -> dict:
    head = await c.fetchrow("SELECT * FROM autodesk.trade_plans WHERE trade_id=$1 AND tenant_id=$2 FOR UPDATE",
                            trade_id, tenant_id)
    if head is None:
        raise NotFound(trade_id)
    if head["status"] in ("APPROVED", "REJECTED", "EXPIRED", "RESEARCH_ONLY"):
        raise Conflict(f"plan {trade_id} is {head['status']}; a new version needs a new workflow")
    if body.account_id != head["account_id"]:
        raise Conflict("a revision cannot move a plan to another account")
    v = head["current_version"] + 1
    await _insert_version(c, trade_id, v, body, created_by, reason, head["current_version"])
    await c.execute("""UPDATE autodesk.trade_plans SET current_version=$2, strategy_type=$3, status='DRAFT',
                       updated_at=now() WHERE trade_id=$1""", trade_id, v, body.strategy_type.value)
    await emit(c, C.EventType.TRADE_PLAN_REVISED, tenant_id=tenant_id, producer=created_by,
               account_id=head["account_id"], simulation_id=head["simulation_id"], workflow_id=head["workflow_id"],
               correlation_id=trade_id,
               payload={"trade_id": trade_id, "version": v, "supersedes": v - 1, "reason": reason,
                        "strategy_type": body.strategy_type.value, "max_loss_rs": str(body.max_loss_rs)})
    return await get_plan(c, tenant_id, trade_id)


async def set_plan_status(c: asyncpg.Connection, *, tenant_id: str, trade_id: str, status: C.PlanStatus) -> None:
    r = await c.execute("UPDATE autodesk.trade_plans SET status=$3, updated_at=now() WHERE trade_id=$1 AND tenant_id=$2",
                        trade_id, tenant_id, status.value)
    if r.endswith(" 0"):
        raise NotFound(trade_id)


async def get_plan(c: asyncpg.Connection, tenant_id: str, trade_id: str, version: Optional[int] = None) -> dict:
    head = await c.fetchrow("SELECT * FROM autodesk.trade_plans WHERE trade_id=$1 AND tenant_id=$2", trade_id, tenant_id)
    if head is None:
        raise NotFound(trade_id)
    v = version or head["current_version"]
    row = await c.fetchrow("SELECT * FROM autodesk.trade_plan_versions WHERE trade_id=$1 AND version=$2", trade_id, v)
    if row is None:
        raise NotFound(f"{trade_id}@{v}")
    out = dict(head)
    out["version"] = v
    out["body"] = row["body"]
    out["body_sha256"] = row["body_sha256"]
    out["version_created_by"] = row["created_by"]
    out["change_reason"] = row["change_reason"]
    return out


async def list_plan_versions(c: asyncpg.Connection, tenant_id: str, trade_id: str) -> list[dict]:
    await get_plan(c, tenant_id, trade_id)   # tenant check
    return [dict(r) for r in await c.fetch(
        "SELECT * FROM autodesk.trade_plan_versions WHERE trade_id=$1 ORDER BY version", trade_id)]


async def list_plans(c: asyncpg.Connection, tenant_id: str, *, account_id: Optional[str] = None,
                     simulation_id: Optional[str] = None, status: Optional[str] = None, limit: int = 200) -> list[dict]:
    q, args = ["SELECT * FROM autodesk.trade_plans WHERE tenant_id=$1"], [tenant_id]
    if simulation_id is not None:
        args.append(simulation_id); q.append(f"AND simulation_id=${len(args)}")
    else:
        q.append("AND simulation_id IS NULL")
    for col, val in (("account_id", account_id), ("status", status)):
        if val is not None:
            args.append(val); q.append(f"AND {col}=${len(args)}")
    args.append(min(max(limit, 1), 1000)); q.append(f"ORDER BY created_at DESC LIMIT ${len(args)}")
    return [dict(r) for r in await c.fetch(" ".join(q), *args)]


# ── risk assessments ─────────────────────────────────────────────────────────────────────────────────────────────────

async def insert_risk_assessment(c: asyncpg.Connection, *, tenant_id: str, a: C.RiskAssessment, producer: str,
                                 workflow_id: Optional[str]) -> dict:
    await c.execute(
        """INSERT INTO autodesk.risk_assessments (assessment_id, tenant_id, trade_id, plan_version, account_id,
               simulation_id, verdict, body, policy_id, policy_version, engine_version)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)""",
        a.assessment_id, tenant_id, a.trade_id, a.plan_version, a.account_id, a.simulation_id, a.verdict.value,
        a.model_dump(mode="json"), a.policy_id, a.policy_version, a.engine_version)
    await emit(c, C.EventType.RISK_ASSESSMENT_COMPLETED, tenant_id=tenant_id, producer=producer,
               account_id=a.account_id, simulation_id=a.simulation_id, workflow_id=workflow_id,
               correlation_id=a.trade_id,
               payload={"assessment_id": a.assessment_id, "trade_id": a.trade_id, "plan_version": a.plan_version,
                        "verdict": a.verdict.value, "violations": a.violations})
    return dict(await c.fetchrow("SELECT * FROM autodesk.risk_assessments WHERE assessment_id=$1", a.assessment_id))


async def get_risk_assessment(c: asyncpg.Connection, tenant_id: str, assessment_id: str) -> dict:
    r = await c.fetchrow("SELECT * FROM autodesk.risk_assessments WHERE assessment_id=$1 AND tenant_id=$2",
                         assessment_id, tenant_id)
    if r is None:
        raise NotFound(assessment_id)
    return dict(r)


async def latest_risk_assessment(c: asyncpg.Connection, tenant_id: str, trade_id: str,
                                 plan_version: int) -> Optional[dict]:
    return _row(await c.fetchrow(
        """SELECT * FROM autodesk.risk_assessments WHERE tenant_id=$1 AND trade_id=$2 AND plan_version=$3
           ORDER BY created_at DESC LIMIT 1""", tenant_id, trade_id, plan_version))


# ── approvals ────────────────────────────────────────────────────────────────────────────────────────────────────────

_APPROVAL_EVENT = {
    C.ApprovalStatus.APPROVED: C.EventType.APPROVAL_GRANTED,
    C.ApprovalStatus.REJECTED: C.EventType.APPROVAL_REJECTED,
    C.ApprovalStatus.NEEDS_HUMAN_APPROVAL: C.EventType.APPROVAL_NEEDS_HUMAN,
    C.ApprovalStatus.NEEDS_REVISION: C.EventType.APPROVAL_REJECTED,
    C.ApprovalStatus.SUSPENDED: C.EventType.APPROVAL_REJECTED,
}


async def insert_approval(c: asyncpg.Connection, *, tenant_id: str, d: C.ApprovalDecision, producer: str,
                          workflow_id: Optional[str], supersedes_id: Optional[str] = None) -> dict:
    try:
        await c.execute(
            """INSERT INTO autodesk.approvals (approval_id, tenant_id, trade_id, plan_version, account_id, simulation_id,
                   status, decided_by, body, risk_assessment_id, supersedes_id, expires_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)""",
            d.approval_id, tenant_id, d.trade_id, d.plan_version, d.account_id, d.simulation_id, d.status.value,
            d.decided_by, d.model_dump(mode="json"), d.risk_assessment_id, supersedes_id, d.expires_at)
    except asyncpg.UniqueViolationError as e:
        raise Conflict("this approval request has already been answered") from e
    await emit(c, _APPROVAL_EVENT[d.status], tenant_id=tenant_id, producer=producer, account_id=d.account_id,
               simulation_id=d.simulation_id, workflow_id=workflow_id, correlation_id=d.trade_id,
               payload={"approval_id": d.approval_id, "trade_id": d.trade_id, "plan_version": d.plan_version,
                        "status": d.status.value, "decided_by": d.decided_by, "reasons": d.reasons,
                        "supersedes_id": supersedes_id})
    return dict(await c.fetchrow("SELECT * FROM autodesk.approvals WHERE approval_id=$1", d.approval_id))


async def get_approval(c: asyncpg.Connection, tenant_id: str, approval_id: str) -> dict:
    r = await c.fetchrow("SELECT * FROM autodesk.approvals WHERE approval_id=$1 AND tenant_id=$2", approval_id, tenant_id)
    if r is None:
        raise NotFound(approval_id)
    return dict(r)


async def is_answered(c: asyncpg.Connection, approval_id: str) -> bool:
    return bool(await c.fetchval("SELECT 1 FROM autodesk.approvals WHERE supersedes_id=$1", approval_id))


async def list_approvals(c: asyncpg.Connection, tenant_id: str, *, pending_only: bool = False,
                         trade_id: Optional[str] = None, simulation_id: Optional[str] = None,
                         limit: int = 200) -> list[dict]:
    q, args = ["SELECT a.* FROM autodesk.approvals a WHERE a.tenant_id=$1"], [tenant_id]
    if pending_only:
        q.append("AND a.status='NEEDS_HUMAN_APPROVAL' AND NOT EXISTS "
                 "(SELECT 1 FROM autodesk.approvals b WHERE b.supersedes_id=a.approval_id)")
    if trade_id is not None:
        args.append(trade_id); q.append(f"AND a.trade_id=${len(args)}")
    if simulation_id is not None:
        args.append(simulation_id); q.append(f"AND a.simulation_id=${len(args)}")
    args.append(min(max(limit, 1), 1000)); q.append(f"ORDER BY a.created_at DESC LIMIT ${len(args)}")
    return [dict(r) for r in await c.fetch(" ".join(q), *args)]


# ── simulations ──────────────────────────────────────────────────────────────────────────────────────────────────────

async def create_simulation(c: asyncpg.Connection, *, tenant_id: str, cfg: C.SimulationConfig, created_by: str,
                            versions: dict) -> dict:
    sid = C.new_id("SIM")
    await c.execute(
        """INSERT INTO autodesk.simulations (simulation_id, tenant_id, name, mode, status, config, versions, created_by)
           VALUES ($1,$2,$3,$4,'CREATED',$5,$6,$7)""",
        sid, tenant_id, cfg.name, cfg.mode.value, cfg.model_dump(mode="json"), versions, created_by)
    await emit(c, C.EventType.SIMULATION_CREATED, tenant_id=tenant_id, producer=created_by, simulation_id=sid,
               payload={"name": cfg.name, "mode": cfg.mode.value, "start_date": cfg.start_date.isoformat(),
                        "end_date": cfg.end_date.isoformat(), "versions": versions})
    return await get_simulation(c, tenant_id, sid)


async def get_simulation(c: asyncpg.Connection, tenant_id: str, simulation_id: str, *, for_update: bool = False) -> dict:
    r = await c.fetchrow("SELECT * FROM autodesk.simulations WHERE simulation_id=$1 AND tenant_id=$2"
                         + (" FOR UPDATE" if for_update else ""), simulation_id, tenant_id)
    if r is None:
        raise NotFound(simulation_id)
    return dict(r)


async def list_simulations(c: asyncpg.Connection, tenant_id: str, limit: int = 100) -> list[dict]:
    return [dict(r) for r in await c.fetch(
        "SELECT * FROM autodesk.simulations WHERE tenant_id=$1 ORDER BY created_at DESC LIMIT $2", tenant_id,
        min(max(limit, 1), 500))]


async def update_simulation(c: asyncpg.Connection, *, tenant_id: str, simulation_id: str, producer: str,
                            **cols: Any) -> dict:
    allowed = {"status", "account_id", "clock_sim_time", "clock_session", "clock_phase", "step_seq", "results",
               "error", "started_at", "ended_at"}
    bad = set(cols) - allowed
    if bad:
        raise ValueError(f"unknown simulation columns: {sorted(bad)}")
    cur = await get_simulation(c, tenant_id, simulation_id, for_update=True)
    sets, args = ["updated_at=now()"], [simulation_id]
    for k, v in cols.items():
        args.append(v.value if isinstance(v, C.SimulationStatus) else v)
        sets.append(f"{k}=${len(args)}")
    await c.execute(f"UPDATE autodesk.simulations SET {', '.join(sets)} WHERE simulation_id=$1", *args)
    if "status" in cols and cols["status"] != cur["status"]:
        new = cols["status"].value if isinstance(cols["status"], C.SimulationStatus) else cols["status"]
        await emit(c, C.EventType.SIMULATION_STATE_CHANGED, tenant_id=tenant_id, producer=producer,
                   simulation_id=simulation_id, sim_time=cols.get("clock_sim_time") or cur["clock_sim_time"],
                   payload={"from": cur["status"], "to": new, "error": cols.get("error")})
    return await get_simulation(c, tenant_id, simulation_id)


async def add_clock_event(c: asyncpg.Connection, *, tenant_id: str, simulation_id: str, seq: int,
                          session_date: date, phase: C.ClockPhase, sim_time: datetime, workflows: list[str]) -> None:
    await c.execute(
        """INSERT INTO autodesk.simulation_clock_events (simulation_id, seq, session_date, phase, sim_time, workflows)
           VALUES ($1,$2,$3,$4,$5,$6)""", simulation_id, seq, session_date, phase.value, sim_time, workflows)
    await emit(c, C.EventType.CLOCK_ADVANCED, tenant_id=tenant_id, producer="SIMULATION_CLOCK",
               simulation_id=simulation_id, sim_time=sim_time,
               payload={"seq": seq, "session_date": session_date.isoformat(), "phase": phase.value,
                        "workflows": workflows})


async def list_clock_events(c: asyncpg.Connection, tenant_id: str, simulation_id: str) -> list[dict]:
    await get_simulation(c, tenant_id, simulation_id)
    return [dict(r) for r in await c.fetch(
        "SELECT * FROM autodesk.simulation_clock_events WHERE simulation_id=$1 ORDER BY seq", simulation_id)]
