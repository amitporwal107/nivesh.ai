"""Goal-Based Investment Planning routes.

Endpoints
---------
    GET    /api/goals/snapshot                  Fetch current user's financial snapshot
    PUT    /api/goals/snapshot                  Create / update snapshot
    GET    /api/goals                           List all goals for current user
    POST   /api/goals                           Create a goal (auto-picks funds)
    GET    /api/goals/{goal_id}                 Full detail incl. last simulation
    PATCH  /api/goals/{goal_id}                 Edit goal fields
    DELETE /api/goals/{goal_id}                 Archive goal
    POST   /api/goals/{goal_id}/simulate        Run fresh MC + scenarios
    POST   /api/goals/{goal_id}/what-if         Evaluate hypothetical adjustments
    GET    /api/goals/fund-shortlist/{bucket}   Top-5 funds per bucket for override
"""
from __future__ import annotations
import json
import logging
import uuid
from datetime import datetime, timezone

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from deps import get_current_user
from services import dashboard_cache, pg_client, goal_engine, goal_fund_picker, goal_copilot

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/goals")


# ── Pydantic models ─────────────────────────────────────────────────────
class FinancialSnapshot(BaseModel):
    age: Optional[int] = None
    marital_status: Optional[str] = None
    dependents: int = 0
    monthly_income_rs: Optional[float] = None
    income_growth_pct: float = 8.0
    monthly_expenses_rs: Optional[float] = None
    inflation_pct: float = 6.0
    current_corpus_rs: float = 0.0
    total_liabilities_rs: float = 0.0
    risk_profile: str = "moderate"
    behavior_score: Optional[float] = None


class GoalCreate(BaseModel):
    goal_type: str = Field(..., description="retirement|education|home|wealth|custom")
    goal_name: str
    target_amount_rs: float = Field(..., gt=0)
    horizon_years: float = Field(..., gt=0)
    priority: str = "medium"
    inflation_pct: Optional[float] = 6.0
    current_corpus_rs: float = 0.0
    monthly_sip_rs: float = 0.0
    manual_allocation: Optional[Dict[str, float]] = None


class GoalUpdate(BaseModel):
    goal_name: Optional[str] = None
    target_amount_rs: Optional[float] = None
    horizon_years: Optional[float] = None
    priority: Optional[str] = None
    monthly_sip_rs: Optional[float] = None
    current_corpus_rs: Optional[float] = None
    allocation: Optional[Dict[str, float]] = None
    selected_funds: Optional[Dict[str, List[Dict[str, Any]]]] = None
    manual_fund_override: Optional[bool] = None
    status: Optional[str] = None


class WhatIfRequest(BaseModel):
    monthly_sip_rs: Optional[float] = None
    horizon_years: Optional[float] = None
    current_corpus_rs: Optional[float] = None
    allocation_override: Optional[Dict[str, float]] = None


class CopilotAskRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=500)


# ── Helpers ─────────────────────────────────────────────────────────────
async def _user_id(request: Request) -> str:
    user = await get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="unauthenticated")
    return str(user.get("user_id") or user.get("_id") or user.get("id"))


def _user_uuid(user_id: str) -> uuid.UUID:
    """Map the app's string user_id (e.g. 'user_abc123') → deterministic UUID.

    Postgres columns are UUID; Mongo IDs are strings — uuid5() gives us a
    stable 1:1 mapping without schema changes.
    """
    try:
        return uuid.UUID(user_id)
    except (ValueError, AttributeError):
        return uuid.uuid5(uuid.NAMESPACE_DNS, f"nivesh:user:{user_id}")


def _row_to_goal_dict(row) -> Dict[str, Any]:
    d = dict(row)
    for k in ("goal_id", "user_id"):
        if k in d and d[k] is not None:
            d[k] = str(d[k])
    for k in ("created_at", "updated_at", "last_simulated_at"):
        if k in d and isinstance(d[k], datetime):
            d[k] = d[k].isoformat()
    # JSONB comes back as dict already via asyncpg+jsonb codec; json.loads for safety
    for k in ("allocation", "selected_funds", "last_simulation"):
        v = d.get(k)
        if isinstance(v, str):
            try:
                d[k] = json.loads(v)
            except Exception:
                pass
    for k in ("target_amount_rs", "horizon_years", "inflation_pct",
              "expected_return_pct", "current_corpus_rs", "monthly_sip_rs",
              "on_track_pct"):
        if k in d and d[k] is not None:
            d[k] = float(d[k])
    return d


async def _get_goal(goal_id: str, user_id: str):
    pool = await pg_client.get_pool()
    if pool is None:
        raise HTTPException(500, "postgres_unavailable")
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM user_goals WHERE goal_id = $1 AND user_id = $2",
            uuid.UUID(goal_id), _user_uuid(user_id),
        )
    if not row:
        raise HTTPException(404, "goal_not_found")
    return _row_to_goal_dict(row)


# ── Financial Snapshot ──────────────────────────────────────────────────
@router.get("/snapshot")
async def get_snapshot(request: Request):
    user_id = await _user_id(request)
    pool = await pg_client.get_pool()
    if pool is None:
        raise HTTPException(500, "postgres_unavailable")
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM user_financial_snapshots WHERE user_id = $1",
            _user_uuid(user_id),
        )
    if not row:
        return {"snapshot": None}
    d = dict(row)
    for k in ("monthly_income_rs", "monthly_expenses_rs", "current_corpus_rs",
              "total_liabilities_rs", "income_growth_pct", "inflation_pct",
              "behavior_score"):
        if k in d and d[k] is not None:
            d[k] = float(d[k])
    if d.get("user_id"):
        d["user_id"] = str(d["user_id"])
    if isinstance(d.get("updated_at"), datetime):
        d["updated_at"] = d["updated_at"].isoformat()
    return {"snapshot": d}


@router.put("/snapshot")
async def put_snapshot(payload: FinancialSnapshot, request: Request):
    user_id = await _user_id(request)
    pool = await pg_client.get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO user_financial_snapshots (
                user_id, age, marital_status, dependents,
                monthly_income_rs, income_growth_pct,
                monthly_expenses_rs, inflation_pct,
                current_corpus_rs, total_liabilities_rs,
                risk_profile, behavior_score, updated_at
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,NOW())
            ON CONFLICT (user_id) DO UPDATE SET
                age = EXCLUDED.age,
                marital_status = EXCLUDED.marital_status,
                dependents = EXCLUDED.dependents,
                monthly_income_rs = EXCLUDED.monthly_income_rs,
                income_growth_pct = EXCLUDED.income_growth_pct,
                monthly_expenses_rs = EXCLUDED.monthly_expenses_rs,
                inflation_pct = EXCLUDED.inflation_pct,
                current_corpus_rs = EXCLUDED.current_corpus_rs,
                total_liabilities_rs = EXCLUDED.total_liabilities_rs,
                risk_profile = EXCLUDED.risk_profile,
                behavior_score = EXCLUDED.behavior_score,
                updated_at = NOW()
            """,
            _user_uuid(user_id), payload.age, payload.marital_status, payload.dependents,
            payload.monthly_income_rs, payload.income_growth_pct,
            payload.monthly_expenses_rs, payload.inflation_pct,
            payload.current_corpus_rs, payload.total_liabilities_rs,
            payload.risk_profile, payload.behavior_score,
        )
    await _dc.invalidate(user_id)
    return await get_snapshot(request)


# ── Goal CRUD ───────────────────────────────────────────────────────────
@router.get("")
async def list_goals(request: Request):
    user_id = await _user_id(request)
    pool = await pg_client.get_pool()
    if pool is None:
        return {"goals": []}
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM user_goals WHERE user_id = $1 AND status != 'abandoned' ORDER BY "
            "CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, "
            "created_at DESC",
            _user_uuid(user_id),
        )
    goals = [_row_to_goal_dict(r) for r in rows]

    # Reconcile each goal's on-track % against the ACTUAL recent SIP from
    # CAS, not just the planned mandate. Without this, a client whose
    # plan says ₹50k/mo but who's only contributing ₹5k/mo still shows a
    # rosy 45% on track. Stored `on_track_pct` becomes "plan-on-track";
    # we attach `actual_monthly_sip_rs` and `on_track_pct_actual` so the
    # UI can flag the gap.
    if goals:
        try:
            from services import cas_snapshot_engine as _eng
            from services import goal_engine as _ge
            sip_stats = await _eng.actual_monthly_sip_rate(user_id, lookback_months=6)
            actual_sip = float(sip_stats.get("avg_monthly_rs") or 0)
            for g in goals:
                g["actual_monthly_sip_rs"] = actual_sip
                g["actual_sip_window_months"] = sip_stats.get("months_observed", 0)
                g["actual_sip_gap_months"] = sip_stats.get("gap_months", 0)
                planned_sip = float(g.get("monthly_sip_rs") or 0)
                target_today = float(g.get("target_amount_rs") or 0)
                horizon = float(g.get("horizon_years") or 0)
                start_corpus = float(g.get("current_corpus_rs") or 0)
                exp_ret = float(g.get("expected_return_pct") or 12.0)
                inflation = float(g.get("inflation_pct") or 6.0)
                if target_today > 0 and horizon > 0:
                    fv = _ge.inflate_target(target_today, horizon, inflation)
                    projected_actual = _ge.project_corpus_fixed(
                        start_corpus, actual_sip, horizon, exp_ret,
                    )
                    g["on_track_pct_actual"] = round(
                        min(100.0, (projected_actual / fv * 100) if fv > 0 else 0), 1
                    )
                    # Difference flag the UI can use without recomputing.
                    plan_pct = float(g.get("on_track_pct") or 0)
                    g["on_track_pct_plan"] = plan_pct
                    g["on_track_drop_pp"] = round(plan_pct - g["on_track_pct_actual"], 1)
                    g["sip_shortfall_rs"] = round(max(0.0, planned_sip - actual_sip), 2)
        except Exception:
            # Best-effort enrichment — original goals payload is still served.
            pass

    return {"goals": goals}


@router.post("")
async def create_goal(payload: GoalCreate, request: Request):
    user_id = await _user_id(request)

    # Hard cap: a user can track at most 4 active goals at a time. This
    # keeps the consolidated dashboard view legible and forces the user
    # to prioritise before adding another life goal.
    MAX_GOALS = 4

    # Fetch the user's risk profile from snapshot
    pool = await pg_client.get_pool()
    if pool is None:
        raise HTTPException(500, "postgres_unavailable")
    async with pool.acquire() as conn:
        # Count existing goals for this user.
        existing = await conn.fetchval(
            "SELECT COUNT(*) FROM user_goals WHERE user_id = $1 AND status != 'abandoned'",
            _user_uuid(user_id),
        )
        if existing is not None and existing >= MAX_GOALS:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Goal limit reached — you can track up to {MAX_GOALS} "
                    "goals at a time. Delete or merge one before adding a new one."
                ),
            )
        # Prevent duplicate goal_type — PRD §4.1 requires clear goal state.
        # If a goal of the same type already exists, return 409 with the existing goal_id
        # so the frontend can offer to edit rather than create a duplicate.
        dup = await conn.fetchrow(
            "SELECT goal_id FROM user_goals WHERE user_id = $1 AND goal_type = $2 AND status != 'abandoned'",
            _user_uuid(user_id), payload.goal_type,
        )
        if dup:
            raise HTTPException(
                status_code=409,
                detail=f"A {payload.goal_type} goal already exists. Edit the existing one instead.",
                headers={"X-Existing-Goal-Id": str(dup["goal_id"])},
            )
        snap = await conn.fetchrow(
            "SELECT risk_profile FROM user_financial_snapshots WHERE user_id = $1",
            _user_uuid(user_id),
        )
    risk_profile = (snap["risk_profile"] if snap else None) or "moderate"

    # Determine allocation
    alloc = payload.manual_allocation or goal_engine.allocation_for_profile(
        risk_profile, payload.horizon_years,
    )

    # Auto-pick funds
    selected = await goal_fund_picker.auto_allocate_funds(alloc, per_bucket=1)

    # Evaluate (expected return + on-track + scenarios + MC)
    ev = goal_engine.evaluate_goal(
        target_today_rs=payload.target_amount_rs,
        horizon_years=payload.horizon_years,
        starting_corpus_rs=payload.current_corpus_rs,
        monthly_sip_rs=payload.monthly_sip_rs,
        risk_profile=risk_profile,
        inflation_pct=payload.inflation_pct or 6.0,
        allocation_override=alloc,
    )

    goal_id = uuid.uuid4()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO user_goals (
                goal_id, user_id, goal_type, goal_name,
                target_amount_rs, horizon_years, priority,
                inflation_pct, expected_return_pct,
                current_corpus_rs, monthly_sip_rs,
                allocation, selected_funds, manual_fund_override,
                on_track_pct, last_simulated_at, last_simulation
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,NOW(),$16)
            """,
            goal_id, _user_uuid(user_id), payload.goal_type, payload.goal_name,
            payload.target_amount_rs, payload.horizon_years, payload.priority,
            payload.inflation_pct or 6.0, ev.expected_return_pct,
            payload.current_corpus_rs, payload.monthly_sip_rs,
            json.dumps(alloc), json.dumps(selected), False,
            ev.on_track_pct, json.dumps(ev.to_dict()),
        )
    await dashboard_cache.invalidate(user_id)
    return await _get_goal(str(goal_id), user_id)


@router.get("/fund-shortlist/{bucket}")
async def fund_shortlist(
    bucket: str,
    request: Request,
    n: int = 15,
    min_quality: float = 55.0,
):
    """Ranked fund shortlist for the Portfolio Maker UI.

    Default n=15 (vs n=5 used by auto-pick) gives users enough options to
    browse and swap. `min_quality` default 55 matches the auto-picker so
    users only see investable funds.
    """
    await _user_id(request)
    funds = await goal_fund_picker.shortlist_for_bucket(bucket, n=n, min_quality=min_quality)
    return {"bucket": bucket, "count": len(funds), "funds": funds}


@router.get("/{goal_id}")
async def get_goal(goal_id: str, request: Request):
    user_id = await _user_id(request)
    return await _get_goal(goal_id, user_id)


@router.patch("/{goal_id}")
async def patch_goal(goal_id: str, payload: GoalUpdate, request: Request):
    user_id = await _user_id(request)
    pool = await pg_client.get_pool()

    # Build dynamic UPDATE
    fields = payload.model_dump(exclude_none=True)
    if not fields:
        return await _get_goal(goal_id, user_id)

    # JSON-encode dict fields
    for k in ("allocation", "selected_funds"):
        if k in fields and fields[k] is not None:
            fields[k] = json.dumps(fields[k])

    sets = ", ".join(f"{k} = ${i + 3}" for i, k in enumerate(fields.keys()))
    vals = list(fields.values())
    async with pool.acquire() as conn:
        await conn.execute(
            f"UPDATE user_goals SET {sets}, updated_at = NOW() "
            f"WHERE goal_id = $1 AND user_id = $2",
            uuid.UUID(goal_id), _user_uuid(user_id), *vals,
        )
    await dashboard_cache.invalidate(user_id)
    return await _get_goal(goal_id, user_id)


@router.delete("/{goal_id}")
async def delete_goal(goal_id: str, request: Request):
    user_id = await _user_id(request)
    pool = await pg_client.get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE user_goals SET status = 'abandoned', updated_at = NOW() "
            "WHERE goal_id = $1 AND user_id = $2",
            uuid.UUID(goal_id), _user_uuid(user_id),
        )
    await dashboard_cache.invalidate(user_id)
    return {"ok": True, "goal_id": goal_id, "status": "abandoned"}


@router.post("/{goal_id}/simulate")
async def simulate_goal(goal_id: str, request: Request):
    user_id = await _user_id(request)
    g = await _get_goal(goal_id, user_id)

    # Fetch risk profile
    pool = await pg_client.get_pool()
    async with pool.acquire() as conn:
        snap = await conn.fetchrow(
            "SELECT risk_profile FROM user_financial_snapshots WHERE user_id = $1",
            _user_uuid(user_id),
        )
    risk_profile = (snap["risk_profile"] if snap else None) or "moderate"

    ev = goal_engine.evaluate_goal(
        target_today_rs=g["target_amount_rs"],
        horizon_years=g["horizon_years"],
        starting_corpus_rs=g.get("current_corpus_rs") or 0,
        monthly_sip_rs=g.get("monthly_sip_rs") or 0,
        risk_profile=risk_profile,
        inflation_pct=g.get("inflation_pct") or 6.0,
        allocation_override=g.get("allocation"),
    )
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE user_goals SET on_track_pct = $3, expected_return_pct = $4, "
            "last_simulated_at = NOW(), last_simulation = $5, updated_at = NOW() "
            "WHERE goal_id = $1 AND user_id = $2",
            uuid.UUID(goal_id), _user_uuid(user_id),
            ev.on_track_pct, ev.expected_return_pct,
            json.dumps(ev.to_dict()),
        )
    return {"goal_id": goal_id, **ev.to_dict()}


@router.post("/{goal_id}/what-if")
async def what_if(goal_id: str, payload: WhatIfRequest, request: Request):
    """Preview-only evaluation — doesn't persist."""
    user_id = await _user_id(request)
    g = await _get_goal(goal_id, user_id)

    pool = await pg_client.get_pool()
    async with pool.acquire() as conn:
        snap = await conn.fetchrow(
            "SELECT risk_profile FROM user_financial_snapshots WHERE user_id = $1",
            _user_uuid(user_id),
        )
    risk_profile = (snap["risk_profile"] if snap else None) or "moderate"

    ev = goal_engine.evaluate_goal(
        target_today_rs=g["target_amount_rs"],
        horizon_years=payload.horizon_years if payload.horizon_years is not None else g["horizon_years"],
        starting_corpus_rs=payload.current_corpus_rs if payload.current_corpus_rs is not None else (g.get("current_corpus_rs") or 0),
        monthly_sip_rs=payload.monthly_sip_rs if payload.monthly_sip_rs is not None else (g.get("monthly_sip_rs") or 0),
        risk_profile=risk_profile,
        inflation_pct=g.get("inflation_pct") or 6.0,
        allocation_override=payload.allocation_override or g.get("allocation"),
    )
    return {"goal_id": goal_id, "preview": True, **ev.to_dict()}


# ── LLM Copilot ─────────────────────────────────────────────────────────
@router.post("/{goal_id}/copilot")
async def copilot_ask(goal_id: str, payload: CopilotAskRequest, request: Request):
    """Natural-language what-if — user asks a question like
    'Can I retire 5 years earlier?' or 'What if I bump SIP by ₹5k?'.
    Returns structured engine output + a plain-English narrative."""
    user_id = await _user_id(request)
    goal = await _get_goal(goal_id, user_id)

    pool = await pg_client.get_pool()
    async with pool.acquire() as conn:
        snap = await conn.fetchrow(
            "SELECT risk_profile FROM user_financial_snapshots WHERE user_id = $1",
            _user_uuid(user_id),
        )
    risk_profile = (snap["risk_profile"] if snap else None) or "moderate"

    return await goal_copilot.ask(
        goal=goal, user_id=str(_user_uuid(user_id)),
        user_query=payload.query, risk_profile=risk_profile,
    )


@router.get("/{goal_id}/copilot/history")
async def copilot_history(goal_id: str, request: Request):
    user_id = await _user_id(request)
    await _get_goal(goal_id, user_id)     # authz
    msgs = await goal_copilot.load_history(goal_id, str(_user_uuid(user_id)), limit=30)
    return {"goal_id": goal_id, "messages": msgs}


@router.delete("/{goal_id}/copilot/history")
async def copilot_clear(goal_id: str, request: Request):
    user_id = await _user_id(request)
    await _get_goal(goal_id, user_id)     # authz
    n = await goal_copilot.clear_history(goal_id, str(_user_uuid(user_id)))
    return {"goal_id": goal_id, "deleted": n}
