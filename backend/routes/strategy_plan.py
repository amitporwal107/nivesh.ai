"""Strategy Builder routes (PRD §16, §17.4, §16.11).

POST /api/desk/strategy/payoff            pure payoff calculation (no DB write)
POST /api/desk/strategy/plan              build a StrategyPlan from live read-only sources; nothing is written
POST /api/desk/strategy/plans             save a built plan (Mongo `desk_strategy_plans`), immutable after save: there is no update route
GET  /api/desk/strategy/plans             the signed-in user's saved plans, newest first (capped)
GET  /api/desk/strategy/plans/{id}        one saved plan
GET  /api/desk/strategy/plans/{id}/context   compact text of a saved plan for the Copilot to quote
DELETE /api/desk/strategy/plans/{id}      deletes only the user's saved copy

Every route needs a signed-in user and every plan is scoped to its owner: another user's plan answers 404, the same as a missing
one. Writes pass through the app's CSRF middleware like the other desk writes. Nothing is ever sent to a broker
(`sent_to_broker: false`). Malformed JSON is 422 `invalid_body`; invalid plan inputs are 422 with `detail.problems`.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import date, datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request, Response

from deps import db, get_current_user
from services.strategy_plan import PLAN_SCHEMA, build_plan, compute_payoff, explain_plan_context, normalise_inputs
from services.strategy_plan.plan import digest
from services.strategy_plan.sources import collect_snapshots

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/desk/strategy", tags=["desk"])

PLANS = "desk_strategy_plans"
MAX_SAVED_PLANS = 200
MAX_LISTED = 100
MAX_PLAN_BYTES = 2_000_000
_ID_MAX = 64
_STATUSES = ("plan", "wait", "no_trade", "insufficient_data")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def today() -> date:
    return date.today()


async def _body(request: Request) -> Any:
    try:
        return json.loads(await request.body())
    except ValueError:
        raise HTTPException(status_code=422, detail="invalid_body")


@router.post("/payoff")
async def strategy_payoff(request: Request) -> Dict[str, Any]:
    await get_current_user(request)
    return compute_payoff(await _body(request), date.today())


@router.post("/plan")
async def strategy_plan(request: Request) -> Dict[str, Any]:
    """Build a plan. Reads sources, writes nothing. Request: see services/strategy_plan/plan.py normalise_inputs."""
    user = await get_current_user(request)
    inputs, problems = normalise_inputs(await _body(request))
    if problems:
        raise HTTPException(status_code=422, detail={"code": "invalid_input", "problems": problems})
    snaps = await collect_snapshots(request, user["user_id"], inputs, today())
    return await asyncio.to_thread(build_plan, inputs, snaps, utcnow(), today())


def _check_plan(plan: Any) -> Dict[str, Any]:
    """A plan the builder returned, unchanged: right schema, never sent to a broker, and an id that matches its inputs and snapshots."""
    def bad(code: str, message: str) -> HTTPException:
        return HTTPException(status_code=422, detail={"code": code, "message": message})
    if not isinstance(plan, dict) or plan.get("schema") != PLAN_SCHEMA:
        raise bad("not_a_plan", f"Send the plan object returned by POST /api/desk/strategy/plan (schema {PLAN_SCHEMA}).")
    if len(json.dumps(plan, default=str)) > MAX_PLAN_BYTES:
        raise bad("plan_too_large", "The plan is larger than the 2 MB limit.")
    if plan.get("sent_to_broker") is not False:
        raise bad("sent_to_broker", "A plan must have sent_to_broker false.")
    if plan.get("status") not in _STATUSES or not isinstance(plan.get("inputs"), dict) or not isinstance(plan.get("source_snapshots"), list):
        raise bad("not_a_plan", "The plan is missing its status, inputs or source snapshots.")
    expect = "plan_" + digest({"inputs": plan["inputs"], "snapshots": plan["source_snapshots"], "rules": plan.get("rules_version")})
    if plan.get("plan_id") != expect or plan.get("inputs_hash") != digest(plan["inputs"], 32):
        raise bad("plan_id_mismatch", "The plan id does not match its inputs and source snapshots: the plan was changed after it was built.")
    return plan


def _summary(doc: Dict[str, Any]) -> Dict[str, Any]:
    p = doc["plan"]
    s = p.get("summary") or {}
    return {"id": doc["_id"], "plan_id": doc["plan_id"], "saved_at": doc["saved_at"], "underlying": s.get("underlying"),
            "direction": s.get("direction"), "horizon": s.get("horizon"), "segment": s.get("segment"), "family": s.get("family"),
            "status": p.get("status"), "data_as_of": s.get("data_as_of"), "rules_version": p.get("rules_version"),
            "lifecycle": (p.get("lifecycle") or {}).get("status"), "sent_to_broker": False}


async def _own(user_id: str, plan_id: str) -> Dict[str, Any]:
    doc = await db[PLANS].find_one({"_id": plan_id, "user_id": user_id}) if 0 < len(plan_id) <= _ID_MAX else None
    if doc is None:
        raise HTTPException(status_code=404, detail="plan_not_found")
    return doc


@router.post("/plans", status_code=201)
async def save_plan(request: Request) -> Dict[str, Any]:
    user = await get_current_user(request)
    uid = user["user_id"]
    body = await _body(request)
    plan = _check_plan(body.get("plan") if isinstance(body, dict) else None)
    if await db[PLANS].find_one({"user_id": uid, "plan_id": plan["plan_id"]}):
        raise HTTPException(status_code=409, detail={"code": "already_saved", "message": "This exact plan is already saved."})
    if await db[PLANS].count_documents({"user_id": uid}) >= MAX_SAVED_PLANS:
        raise HTTPException(status_code=409, detail={"code": "plan_limit", "message": f"At most {MAX_SAVED_PLANS} saved plans; delete one first."})
    doc = {"_id": uuid.uuid4().hex, "user_id": uid, "plan_id": plan["plan_id"], "inputs_hash": plan["inputs_hash"], "saved_at": utcnow().isoformat(),
           "source_snapshots": plan["source_snapshots"], "rules_version": plan.get("rules_version"), "plan": plan}
    await db[PLANS].insert_one(doc)
    if await db[PLANS].count_documents({"user_id": uid}) > MAX_SAVED_PLANS:
        # two saves that both counted 199 can both insert; the later count catches it and takes ours back
        await db[PLANS].delete_one({"_id": doc["_id"], "user_id": uid})
        raise HTTPException(status_code=409, detail={"code": "plan_limit", "message": f"At most {MAX_SAVED_PLANS} saved plans; delete one first."})
    logger.info("desk: user %s saved strategy plan %s (%s)", uid, doc["_id"], plan["plan_id"])
    return {"id": doc["_id"], "saved_at": doc["saved_at"], "plan": plan, "sent_to_broker": False}


@router.get("/plans")
async def list_plans(request: Request) -> Dict[str, Any]:
    user = await get_current_user(request)
    docs = await db[PLANS].find({"user_id": user["user_id"]}).sort("saved_at", -1).to_list(MAX_LISTED)
    return {"plans": [_summary(d) for d in docs], "count": len(docs), "limit": MAX_LISTED, "max_saved": MAX_SAVED_PLANS}


@router.get("/plans/{plan_id}")
async def get_plan(request: Request, plan_id: str) -> Dict[str, Any]:
    user = await get_current_user(request)
    doc = await _own(user["user_id"], plan_id)
    return {"id": doc["_id"], "saved_at": doc["saved_at"], "plan": doc["plan"], "sent_to_broker": False}


@router.get("/plans/{plan_id}/context")
async def plan_context(request: Request, plan_id: str) -> Dict[str, Any]:
    user = await get_current_user(request)
    doc = await _own(user["user_id"], plan_id)
    return {"id": doc["_id"], "plan_id": doc["plan_id"], "context": explain_plan_context(doc["plan"], doc["_id"], doc["saved_at"])}


@router.delete("/plans/{plan_id}")
async def delete_plan(request: Request, plan_id: str) -> Dict[str, Any]:
    user = await get_current_user(request)
    res = await db[PLANS].delete_one({"_id": plan_id, "user_id": user["user_id"]}) if 0 < len(plan_id) <= _ID_MAX else None
    if res is None or res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="plan_not_found")
    logger.info("desk: user %s deleted saved strategy plan %s", user["user_id"], plan_id)
    return {"deleted": True, "id": plan_id, "note": "This deleted only your saved copy of the plan. Nothing else changed and nothing was sent to a broker."}
