"""HTTP API of the Autonomous Trading Desk (`/api/v1`, DESIGN §6.5). Every route needs a signed-in Nivesh user; the
tenant is the user's id, and every read is tenant-scoped (another tenant's id answers 404)."""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .. import APP_NAME, APP_VERSION
from .. import contracts as C
from .. import store
from ..accounts import ensure_default_policy, open_account
from ..scoring import registry as scoring_registry

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1")


# ── auth + plumbing ─────────────────────────────────────────────────────────────────────────────────────────────────

async def current_user(request: Request) -> dict:
    """The signed-in Nivesh user (same session cookie / bearer token as the main app)."""
    from deps import get_current_user
    return await get_current_user(request)


def _is_admin(user: dict) -> bool:
    try:
        from deps import _is_role
        return bool(_is_role(user, "admin"))
    except Exception:  # noqa: BLE001
        return bool(user.get("is_admin")) or user.get("role") == "admin"


def tenant_of(user: dict) -> str:
    uid = user.get("user_id")
    if not uid:
        raise HTTPException(401, "Not authenticated")
    return uid


def out(v: Any) -> Any:
    """JSON-safe: Decimals as strings (money keeps its precision), datetimes / dates ISO, enums by value."""
    if isinstance(v, dict):
        return {k: out(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [out(x) for x in v]
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, Enum):
        return v.value
    if hasattr(v, "model_dump"):
        return out(v.model_dump(mode="json"))
    return v


def _state(request: Request):
    return request.app.state.desk


async def _bg(request: Request, key: str, coro) -> None:
    tasks = _state(request).background
    if key in tasks and not tasks[key].done():
        coro.close()
        raise HTTPException(409, "already running")

    async def wrap():
        try:
            await coro
        except Exception:  # noqa: BLE001 — recorded on the workflow / simulation by the code that failed
            log.exception("background job %s failed", key)

    tasks[key] = asyncio.create_task(wrap())


def error_handlers(app) -> None:
    @app.exception_handler(store.NotFound)
    async def _nf(_r, e):
        return JSONResponse({"error": "NOT_FOUND", "message": f"not found: {e}"}, status_code=404)

    @app.exception_handler(store.Conflict)
    async def _cf(_r, e):
        return JSONResponse({"error": "CONFLICT", "message": str(e)}, status_code=409)

    @app.exception_handler(store.IllegalTransition)
    async def _it(_r, e):
        return JSONResponse({"error": "ILLEGAL_TRANSITION", "message": str(e)}, status_code=409)

    @app.exception_handler(ValueError)
    async def _ve(_r, e):
        return JSONResponse({"error": "INVALID", "message": str(e)}, status_code=422)


# ── health + desk ───────────────────────────────────────────────────────────────────────────────────────────────────

@router.get("/health")
async def health(request: Request):
    st = _state(request)
    try:
        async with st.pool.acquire() as c:
            db = await c.fetchval("SELECT 1") == 1
            migs = [r["name"] for r in await c.fetch("SELECT name FROM autodesk.schema_migrations ORDER BY name")]
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"status": "degraded", "db": False, "error": type(e).__name__}, status_code=503)
    return {"status": "ok", "app": APP_NAME, "version": APP_VERSION, "db": db, "migrations": migs,
            "agents": {k.value: a.descriptor.version for k, a in st.orchestrator.agents.items()},
            "calendar_years": _calendar_years(), "execution": "none (Phase 1: no orders)"}


def _calendar_years() -> list[int]:
    from ..market import calendar
    return calendar.loaded_years()


@router.get("/desk/status")
async def desk_status(request: Request, user: dict = Depends(current_user)):
    t = tenant_of(user)
    st = _state(request)
    now = datetime.now(timezone.utc)
    async with st.pool.acquire() as c:
        accounts = await store.list_accounts(c, t)
        agents = await store.list_agents(c)
        pending = len(await store.list_approvals(c, t, pending_only=True))
        open_wf = await c.fetchval("""SELECT count(*) FROM autodesk.workflows WHERE tenant_id=$1
                                      AND state IN ('CREATED','RUNNING','WAITING_HUMAN') AND simulation_id IS NULL""", t)
        controls = await store.list_desk_controls(c, t)
        pm = await c.fetchrow("""SELECT session_date, outcome FROM autodesk.workflows WHERE tenant_id=$1
                                 AND kind='PREMARKET_CHECK' AND simulation_id IS NULL
                                 ORDER BY created_at DESC LIMIT 1""", t)
    data: dict[str, Any] = {}
    try:
        view = st.market_factory(now)
        data = {"latest_cash_session": view.latest_session("cash").isoformat(),
                "latest_fno_session": view.latest_session("fno").isoformat()}
    except Exception as e:  # noqa: BLE001
        data = {"error": f"{type(e).__name__}: {e}"}
    return out({"as_of": now, "accounts": [{k: a[k] for k in ("account_id", "name", "kind", "operating_mode", "status",
                                                              "starting_capital_rs")} for a in accounts],
                "agents": [{k: a[k] for k in ("agent_key", "version", "kind", "status", "last_heartbeat")}
                           for a in agents],
                "pending_approvals": pending, "open_workflows": open_wf, "controls": controls,
                "last_premarket": dict(pm) if pm else None, "market_data": data,
                "execution": "none (Phase 1: no orders, fills or positions)"})


class ControlIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    active: bool
    reason: str = Field(min_length=1, max_length=300)


@router.get("/desk/controls")
async def list_controls(request: Request, user: dict = Depends(current_user)):
    async with _state(request).pool.acquire() as c:
        return out(await store.list_desk_controls(c, tenant_of(user)))


@router.post("/desk/controls/{control}")
async def set_control(control: C.DeskControl, body: ControlIn, request: Request, user: dict = Depends(current_user)):
    """Emergency control (PRD §10.4). STOP_NEW_ENTRIES: no new proposal starts and nothing is approved on the desk's
    real-time accounts until it is lifted. It never cancels a protective exit (there are no orders in Phase 1)."""
    t = tenant_of(user)
    async with _state(request).pool.acquire() as c:
        return out(await store.set_desk_control(c, tenant_id=t, control=control, active=body.active,
                                                reason=body.reason, actor=f"user:{t}"))


# ── accounts + policies ─────────────────────────────────────────────────────────────────────────────────────────────

class AccountIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    operating_mode: C.OperatingMode = C.OperatingMode.RESEARCH
    starting_capital_rs: Decimal = Field(default=Decimal("1000000"), gt=0, le=Decimal("1000000000"))


class ModeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: C.OperatingMode
    reason: str = Field(min_length=1, max_length=300)


@router.post("/accounts", status_code=201)
async def create_account(body: AccountIn, request: Request, user: dict = Depends(current_user)):
    t = tenant_of(user)
    async with _state(request).pool.acquire() as c:
        async with c.transaction():
            acc = await open_account(c, tenant_id=t, name=body.name, kind=C.AccountKind.PAPER, mode=body.operating_mode,
                                     capital=body.starting_capital_rs, created_by=f"user:{t}")
    return out(acc)


@router.get("/accounts")
async def list_accounts(request: Request, include_simulation: bool = False, user: dict = Depends(current_user)):
    async with _state(request).pool.acquire() as c:
        return out(await store.list_accounts(c, tenant_of(user), include_simulation=include_simulation))


@router.get("/accounts/{account_id}")
async def get_account(account_id: str, request: Request, user: dict = Depends(current_user)):
    async with _state(request).pool.acquire() as c:
        return out(await store.get_account(c, tenant_of(user), account_id))


@router.post("/accounts/{account_id}/mode")
async def set_mode(account_id: str, body: ModeIn, request: Request, user: dict = Depends(current_user)):
    t = tenant_of(user)
    async with _state(request).pool.acquire() as c:
        async with c.transaction():
            return out(await store.set_account_mode(c, tenant_id=t, account_id=account_id, mode=body.mode,
                                                    actor=f"user:{t}", reason=body.reason))


class PolicyChangeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    changes: dict[str, Any]
    reason: str = Field(min_length=1, max_length=300)


@router.get("/policies")
async def list_policies(request: Request, user: dict = Depends(current_user)):
    t = tenant_of(user)
    async with _state(request).pool.acquire() as c:
        async with c.transaction():
            await ensure_default_policy(c, t, f"user:{t}")
        return out(await store.list_policies(c, t))


@router.get("/policies/{policy_id}")
async def get_policy(policy_id: str, request: Request, version: Optional[int] = None,
                     user: dict = Depends(current_user)):
    async with _state(request).pool.acquire() as c:
        return out(await store.get_policy(c, tenant_of(user), policy_id, version))


@router.post("/policies/{policy_id}/versions", status_code=201)
async def new_policy_version(policy_id: str, body: PolicyChangeIn, request: Request,
                             user: dict = Depends(current_user)):
    """A user may tighten; loosening beyond the defaults needs an admin (risk-profile rule)."""
    t = tenant_of(user)
    from ..control.policy import validate_change
    async with _state(request).pool.acquire() as c:
        async with c.transaction():
            cur = await store.get_policy(c, t, policy_id)
            old = C.PolicyBody.model_validate(cur["body"])
            try:
                new = C.PolicyBody.model_validate({**cur["body"], **body.changes})
            except Exception as e:  # noqa: BLE001
                raise HTTPException(422, f"invalid policy: {e}") from e
            try:
                validate_change(old, new, is_admin=_is_admin(user))
            except PermissionError as e:
                raise HTTPException(403, str(e)) from e
            return out(await store.add_policy_version(c, tenant_id=t, policy_id=policy_id,
                                                      body=new.model_dump(mode="json"), created_by=f"user:{t}",
                                                      reason=body.reason))


# ── agents + workflows + events ─────────────────────────────────────────────────────────────────────────────────────

@router.get("/scoring/versions")
async def scoring_versions(user: dict = Depends(current_user)):
    """Scoring versions: which one selects signals (v1), which run in shadow, which are off (scoring/registry.py)."""
    tenant_of(user)
    return {"active": scoring_registry.active_version(), "versions": scoring_registry.describe()}


@router.get("/agents")
async def list_agents(request: Request, user: dict = Depends(current_user)):
    tenant_of(user)
    async with _state(request).pool.acquire() as c:
        return out(await store.list_agents(c))


@router.get("/agents/{agent_key}/activity")
async def agent_activity(agent_key: C.AgentKey, request: Request, simulation_id: Optional[str] = None,
                         limit: int = Query(100, ge=1, le=500), user: dict = Depends(current_user)):
    async with _state(request).pool.acquire() as c:
        rows = await store.list_tasks(c, tenant_of(user), agent=agent_key.value, simulation_id=simulation_id,
                                      limit=limit)
    keep = ("task_id", "workflow_id", "simulation_id", "task_type", "step", "entity_id", "state", "attempt",
            "result_summary", "result_ref", "error", "agent_version", "created_at", "completed_at", "latency_ms")
    return out([{k: r[k] for k in keep} for r in rows])


class WorkflowIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["SESSION_CYCLE", "TRADE_PROPOSAL"]
    account_id: Optional[str] = None
    session_date: Optional[date] = None
    universe: str = "FNO"
    symbols: Optional[list[str]] = Field(default=None, max_length=50)
    max_proposals: Optional[int] = Field(default=None, ge=0, le=20)
    signal_id: Optional[str] = None
    wait: bool = False


@router.post("/desk/workflows", status_code=202)
async def start_workflow(body: WorkflowIn, request: Request, user: dict = Depends(current_user)):
    t = tenant_of(user)
    st = _state(request)
    now = datetime.now(timezone.utc)
    orch = st.orchestrator
    if body.kind == "SESSION_CYCLE":
        if not body.account_id:
            raise HTTPException(422, "account_id is required")
        sd = body.session_date or await st.next_session(now)
        cycle = await orch.open_session_cycle(tenant_id=t, account_id=body.account_id, session_date=sd, as_of=now,
                                              universe=body.universe, symbols=body.symbols,
                                              max_proposals=body.max_proposals, producer=f"user:{t}")
        if cycle["state"] == "RUNNING":
            job = orch.run_session_cycle(tenant_id=t, account_id=body.account_id, session_date=sd, as_of=now,
                                         idempotency_key=cycle["idempotency_key"])
            if body.wait:
                cycle = await job
            else:
                await _bg(request, cycle["workflow_id"], job)
        return out(cycle)
    # TRADE_PROPOSAL for one stored desk signal (not for simulations: their clock runs proposals)
    if not body.signal_id:
        raise HTTPException(422, "signal_id is required")
    async with st.pool.acquire() as c:
        sig = await store.get_signal(c, t, body.signal_id)
        if sig["simulation_id"]:
            raise HTTPException(409, "simulated signals are proposed by their simulation's clock")
        if sig["status"] != "DETECTED":
            raise HTTPException(409, f"signal is {sig['status']}")
        scan_wf = await store.get_workflow(c, t, sig["workflow_id"])
        cycle = await store.get_workflow(c, t, scan_wf["parent_workflow_id"])
        scan_task = await store.get_task(c, t, sig["task_id"])
    job = orch.run_trade_proposal(tenant_id=t, cycle=cycle, signal=sig, as_of=now, scan_task=scan_task)
    if body.wait:
        return out(await job)
    await _bg(request, f"proposal:{body.signal_id}", job)
    return {"status": "started", "signal_id": body.signal_id}


@router.get("/desk/workflows")
async def list_workflows(request: Request, account_id: Optional[str] = None, simulation_id: Optional[str] = None,
                         kind: Optional[str] = None, limit: int = Query(100, ge=1, le=500),
                         user: dict = Depends(current_user)):
    async with _state(request).pool.acquire() as c:
        return out(await store.list_workflows(c, tenant_of(user), account_id=account_id, simulation_id=simulation_id,
                                              kind=kind, limit=limit))


@router.get("/desk/workflows/{workflow_id}")
async def get_workflow(workflow_id: str, request: Request, user: dict = Depends(current_user)):
    t = tenant_of(user)
    async with _state(request).pool.acquire() as c:
        wf = await store.get_workflow(c, t, workflow_id)
        tasks = sorted(await store.list_tasks(c, t, workflow_id=workflow_id), key=lambda r: r["created_at"])
        hand = await store.list_handoffs(c, t, workflow_id=workflow_id)
        children = await store.list_workflows(c, t, parent_workflow_id=workflow_id)
    return out({"workflow": wf, "tasks": tasks, "handoffs": hand,
                "children": [{k: w[k] for k in ("workflow_id", "kind", "state", "outcome", "created_at")}
                             for w in children]})


@router.get("/events")
async def events(request: Request, simulation_id: Optional[str] = None, workflow_id: Optional[str] = None,
                 after_seq: int = Query(0, ge=0), limit: int = Query(500, ge=1, le=5000),
                 user: dict = Depends(current_user)):
    async with _state(request).pool.acquire() as c:
        return out(await store.list_events(c, tenant_of(user), simulation_id=simulation_id, workflow_id=workflow_id,
                                           after_seq=after_seq, limit=limit))


# ── signals, plans, risk, approvals ─────────────────────────────────────────────────────────────────────────────────

@router.get("/signals")
async def list_signals(request: Request, simulation_id: Optional[str] = None, account_id: Optional[str] = None,
                       session_date: Optional[date] = None, status: Optional[str] = None,
                       segment: Optional[str] = None, min_score: Optional[Decimal] = None,
                       limit: int = Query(200, ge=1, le=2000), user: dict = Depends(current_user)):
    async with _state(request).pool.acquire() as c:
        return out(await store.list_signals(c, tenant_of(user), simulation_id=simulation_id, account_id=account_id,
                                            session_date=session_date, status=status, segment=segment,
                                            min_score=min_score, limit=limit))


@router.get("/signals/{signal_id}")
async def get_signal(signal_id: str, request: Request, user: dict = Depends(current_user)):
    async with _state(request).pool.acquire() as c:
        return out(await store.get_signal(c, tenant_of(user), signal_id))


@router.get("/trade-plans")
async def list_plans(request: Request, account_id: Optional[str] = None, simulation_id: Optional[str] = None,
                     status: Optional[str] = None, limit: int = Query(200, ge=1, le=1000),
                     user: dict = Depends(current_user)):
    async with _state(request).pool.acquire() as c:
        return out(await store.list_plans(c, tenant_of(user), account_id=account_id, simulation_id=simulation_id,
                                          status=status, limit=limit))


@router.get("/trade-plans/{trade_id}")
async def get_plan(trade_id: str, request: Request, version: Optional[int] = None,
                   user: dict = Depends(current_user)):
    t = tenant_of(user)
    async with _state(request).pool.acquire() as c:
        plan = await store.get_plan(c, t, trade_id, version)
        risk = await store.latest_risk_assessment(c, t, trade_id, plan["version"])
        apr = await store.list_approvals(c, t, trade_id=trade_id)
    return out({**plan, "plan_hash": C.plan_hash(plan["body"]), "latest_risk_assessment": risk, "approvals": apr})


@router.get("/trade-plans/{trade_id}/versions")
async def plan_versions(trade_id: str, request: Request, user: dict = Depends(current_user)):
    async with _state(request).pool.acquire() as c:
        return out(await store.list_plan_versions(c, tenant_of(user), trade_id))


class AssessIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    trade_id: str
    version: Optional[int] = None


@router.post("/trade-plans/{trade_id}/validate", status_code=201)
async def validate_plan(trade_id: str, request: Request, user: dict = Depends(current_user)):
    t = tenant_of(user)
    return out(await _state(request).orchestrator.reassess(tenant_id=t, trade_id=trade_id, version=None))


@router.post("/risk/assessments", status_code=201)
async def run_assessment(body: AssessIn, request: Request, user: dict = Depends(current_user)):
    t = tenant_of(user)
    return out(await _state(request).orchestrator.reassess(tenant_id=t, trade_id=body.trade_id, version=body.version))


@router.get("/risk/assessments/{assessment_id}")
async def get_assessment(assessment_id: str, request: Request, user: dict = Depends(current_user)):
    async with _state(request).pool.acquire() as c:
        return out(await store.get_risk_assessment(c, tenant_of(user), assessment_id))


@router.get("/risk/portfolio/{account_id}")
async def portfolio_risk(account_id: str, request: Request, user: dict = Depends(current_user)):
    t = tenant_of(user)
    st = _state(request)
    now = datetime.now(timezone.utc)
    async with st.pool.acquire() as c:
        acc = await store.get_account(c, t, account_id)
        book = await st.orchestrator.load_book(c, t, account_id, now)
    return out({"account": acc, "book": book.to_json() if hasattr(book, "to_json") else book,
                "note": "Phase 1: commitments are approved, unexpired plans; there are no fills or positions yet"})


class DecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["APPROVE", "REJECT", "REQUEST_REVISION"]
    reason: str = Field(default="", max_length=500)
    plan_hash: Optional[str] = Field(default=None, pattern=r"^[0-9a-f]{64}$")  # the plan version the person reviewed


@router.get("/approvals")
async def list_approvals(request: Request, pending: bool = False, trade_id: Optional[str] = None,
                         simulation_id: Optional[str] = None, limit: int = Query(200, ge=1, le=1000),
                         user: dict = Depends(current_user)):
    async with _state(request).pool.acquire() as c:
        return out(await store.list_approvals(c, tenant_of(user), pending_only=pending, trade_id=trade_id,
                                              simulation_id=simulation_id, limit=limit))


@router.get("/approvals/{approval_id}")
async def get_approval(approval_id: str, request: Request, user: dict = Depends(current_user)):
    async with _state(request).pool.acquire() as c:
        return out(await store.get_approval(c, tenant_of(user), approval_id))


@router.post("/approvals/{approval_id}/decision", status_code=201)
async def decide(approval_id: str, body: DecisionIn, request: Request, user: dict = Depends(current_user)):
    t = tenant_of(user)
    return out(await _state(request).orchestrator.decide(tenant_id=t, approval_id=approval_id, decision=body.decision,
                                                         reason=body.reason, user_id=t, plan_hash=body.plan_hash))


# ── simulations ─────────────────────────────────────────────────────────────────────────────────────────────────────

class StepIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    unit: Literal["PHASE", "SESSION"] = "PHASE"


@router.post("/simulations", status_code=201)
async def create_simulation(body: C.SimulationConfig, request: Request, user: dict = Depends(current_user)):
    t = tenant_of(user)
    return out(await _state(request).simulator.create(tenant_id=t, cfg=body, user_id=t))


@router.get("/simulations")
async def list_simulations(request: Request, limit: int = Query(50, ge=1, le=500), user: dict = Depends(current_user)):
    async with _state(request).pool.acquire() as c:
        return out(await store.list_simulations(c, tenant_of(user), limit))


@router.get("/simulations/{sid}")
async def get_simulation(sid: str, request: Request, user: dict = Depends(current_user)):
    st = _state(request)
    async with st.pool.acquire() as c:
        sim = await store.get_simulation(c, tenant_of(user), sid)
    running = sid in st.background and not st.background[sid].done()
    return out({**sim, "background_run": running})


@router.post("/simulations/{sid}/start")
async def start_simulation(sid: str, request: Request, user: dict = Depends(current_user)):
    t = tenant_of(user)
    return out(await _state(request).simulator.start(tenant_id=t, sid=sid, user_id=t))


@router.post("/simulations/{sid}/step")
async def step_simulation(sid: str, request: Request, body: StepIn = StepIn(), user: dict = Depends(current_user)):
    t = tenant_of(user)
    st = _state(request)
    if sid in st.background and not st.background[sid].done():
        raise HTTPException(409, "the simulation is running to the end in the background")
    return out(await st.simulator.step(tenant_id=t, sid=sid, unit=body.unit, user_id=t))


@router.post("/simulations/{sid}/run", status_code=202)
async def run_simulation(sid: str, request: Request, user: dict = Depends(current_user)):
    """Accelerated replay to the end, in the background. Poll GET /simulations/{id}; pause / stop interrupt it."""
    t = tenant_of(user)
    st = _state(request)
    async with st.pool.acquire() as c:
        sim = await store.get_simulation(c, t, sid)
    if sim["status"] != "RUNNING":
        raise HTTPException(409, f"simulation is {sim['status']}; start or resume it first")
    await _bg(request, sid, st.simulator.run_to_end(tenant_id=t, sid=sid, user_id=t))
    return {"simulation_id": sid, "status": "RUNNING", "background_run": True}


@router.post("/simulations/{sid}/pause")
async def pause_simulation(sid: str, request: Request, user: dict = Depends(current_user)):
    t = tenant_of(user)
    return out(await _state(request).simulator.pause(tenant_id=t, sid=sid, user_id=t))


@router.post("/simulations/{sid}/resume")
async def resume_simulation(sid: str, request: Request, user: dict = Depends(current_user)):
    t = tenant_of(user)
    return out(await _state(request).simulator.resume(tenant_id=t, sid=sid, user_id=t))


@router.post("/simulations/{sid}/stop")
async def stop_simulation(sid: str, request: Request, user: dict = Depends(current_user)):
    t = tenant_of(user)
    return out(await _state(request).simulator.stop(tenant_id=t, sid=sid, user_id=t))


@router.get("/simulations/{sid}/timeline")
async def simulation_timeline(sid: str, request: Request, after_seq: int = Query(0, ge=0),
                              limit: int = Query(1000, ge=1, le=5000), user: dict = Depends(current_user)):
    t = tenant_of(user)
    async with _state(request).pool.acquire() as c:
        await store.get_simulation(c, t, sid)
        return out({"clock": await store.list_clock_events(c, t, sid),
                    "events": await store.list_events(c, t, simulation_id=sid, after_seq=after_seq, limit=limit)})


@router.get("/simulations/{sid}/workflows")
async def simulation_workflows(sid: str, request: Request, user: dict = Depends(current_user)):
    t = tenant_of(user)
    async with _state(request).pool.acquire() as c:
        await store.get_simulation(c, t, sid)
        return out(await store.list_workflows(c, t, simulation_id=sid, limit=1000))


@router.get("/simulations/{sid}/agents")
async def simulation_agents(sid: str, request: Request, user: dict = Depends(current_user)):
    t = tenant_of(user)
    async with _state(request).pool.acquire() as c:
        sim = await store.get_simulation(c, t, sid)
        rows = await c.fetch("""SELECT to_agent, state, count(*) n, avg(latency_ms)::int avg_ms
                                FROM autodesk.agent_tasks WHERE simulation_id=$1 GROUP BY 1, 2 ORDER BY 1, 2""", sid)
    agents: dict[str, dict] = {}
    for r in rows:
        a = agents.setdefault(r["to_agent"], {"tasks": 0, "by_state": {}})
        a["tasks"] += r["n"]
        a["by_state"][r["state"]] = r["n"]
    return out({"simulation_id": sid, "versions": sim["versions"], "agents": agents})


@router.get("/simulations/{sid}/results")
async def simulation_results(sid: str, request: Request, user: dict = Depends(current_user)):
    t = tenant_of(user)
    st = _state(request)
    async with st.pool.acquire() as c:
        sim = await store.get_simulation(c, t, sid)
    return out(sim["results"] or await st.simulator.results(tenant_id=t, sid=sid))
