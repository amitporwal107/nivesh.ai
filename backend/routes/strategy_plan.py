"""Strategy Builder routes (PRD §16, §17.4, §16.11).

POST /api/desk/strategy/payoff            pure payoff calculation (no DB write)
GET  /api/desk/strategy/templates         the strategy templates the payoff engine can price (read only; templates, not certified programs)
POST /api/desk/strategy/plan              build a StrategyPlan from live read-only sources
POST /api/desk/strategy/ideas             strategies for the top AI opportunities (scanner), cash / futures / options / combinations
POST /api/desk/strategy/top               the best N ideas per asset class (index options / stock F&O / cash) by regime fit
    The only write of these three: each candidate's / idea's canonical TradePlan is stored insert-once in Mongo
    `trade_plans` (services/strategy_plan/trade_plan.py), so a paper trade can cite it by id (`plan_ref`).
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
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request, Response

from deps import db, get_current_user
from services import strategy_levels
from services.strategy_plan import PLAN_SCHEMA, build_plan, compute_payoff, explain_plan_context, normalise_inputs
from services.strategy_plan import ideas as ideas_mod
from services.strategy_plan import regime_fit
from services.strategy_plan import templates as templates_mod
from services.strategy_plan.plan import digest
from services.strategy_plan import trade_plan as tpm
from services.strategy_plan.sources import attach_symbol_suggestions, collect_snapshots, finish_plan
from services import trade_lifecycle as lifecycle

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


@router.get("/templates")
async def strategy_templates(request: Request) -> Dict[str, Any]:
    """The strategy templates in services/strategy_plan/templates.py, for the F&O lab's program library: each one's legs,
    its own parameters and the payoff engine version that prices it. Read only: these are templates, not certified
    programs (there is no program compiler, executor or certification yet); nothing is compiled, written or sent."""
    await get_current_user(request)
    items = templates_mod.catalog()
    return {"templates": items, "count": len(items), "status": "template",
            "calculation_version": templates_mod.CALCULATION_VERSION, "read_only": True}


@router.post("/levels")
async def strategy_levels_route(request: Request) -> Dict[str, Any]:
    """Rule-based, hypothetical entry / stop / target levels for an options structure (services/strategy_levels), worked out from the payoff engine's own numbers. Pure calculation: no write, nothing
    sent to a broker. Body: {"payoff": <the payoff request>, "refs": {"put_wall", "call_wall", "expected_move"}}."""
    await get_current_user(request)
    body = await _body(request)
    if not isinstance(body, dict) or not isinstance(body.get("payoff"), dict):
        raise HTTPException(status_code=422, detail="payoff_required")
    refs = body.get("refs") if isinstance(body.get("refs"), dict) else {}
    return strategy_levels.compute(body["payoff"], refs, date.today())


@router.post("/plan")
async def strategy_plan(request: Request) -> Dict[str, Any]:
    """Build a plan. Reads sources, writes nothing. Request: see services/strategy_plan/plan.py normalise_inputs."""
    user = await get_current_user(request)
    inputs, problems = normalise_inputs(await _body(request))
    if problems:
        raise HTTPException(status_code=422, detail={"code": "invalid_input", "problems": problems})
    snaps = await collect_snapshots(request, user["user_id"], inputs, today())
    plan = await asyncio.to_thread(build_plan, inputs, snaps, utcnow(), today())
    plan = await attach_symbol_suggestions(plan)
    await store_trade_plans([c.get("trade_plan") for c in plan.get("candidates") or []], user["user_id"])
    return await finish_plan(plan, user["user_id"])


STORE_TIMEOUT_S = 10.0


async def store_trade_plans(plans: Any, owner: str) -> None:
    """Store the TradePlans a response carries (insert-once). A plan that could not be stored says so on itself
    (`stored: false`), so a paper trade that cites it is refused as unknown rather than guessed."""
    plans = [p for p in plans if p]
    if not plans:
        return
    try:
        await asyncio.wait_for(tpm.store_many(db, plans, owner), timeout=STORE_TIMEOUT_S)
    except asyncio.TimeoutError:
        logger.error("strategy: storing %d trade plans timed out after %ss", len(plans), STORE_TIMEOUT_S)
        for p in plans:
            p.setdefault("stored", False)
            p.setdefault("store_error", "timeout")


@router.post("/ideas")
async def strategy_ideas(request: Request) -> Dict[str, Any]:
    """Strategies for the top AI opportunities. Reads the scanner and the plan sources, writes nothing, sends nothing to a broker."""
    user = await get_current_user(request)
    body = await _body(request)
    limit, passed, problems, applied = ideas_mod.parse_body(body)
    chartink_limit, cprobs, capplied = ideas_mod.parse_chartink_limit(body)
    problems, applied = problems + cprobs, applied + capplied
    if problems:
        raise HTTPException(status_code=422, detail={"code": "invalid_input", "problems": problems})
    out = await ideas_mod.build_ideas(request, user["user_id"], limit, passed, applied, utcnow(), today(), chartink_limit)
    await store_trade_plans([i.get("trade_plan") for i in out.get("ideas") or []], user["user_id"])
    return out


_TOP_CLASSES = ("index_options", "stock_fno", "cash")
_TOP_LIMIT_MAX = 10


def _parse_top_body(body: Any) -> Dict[str, Any]:
    """limit / classes / expiry / distinct for POST /top. Anything unrecognised is refused rather than ignored, so a
    misspelled class cannot silently return the default three."""
    if body in (None, ""):
        body = {}
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail={"code": "invalid_input", "problems": [
            {"field": "body", "code": "not_an_object", "message": "The body must be a JSON object."}]})
    problems = []
    unknown = sorted(set(body) - {"limit", "classes", "expiry", "distinct"})
    if unknown:
        problems.append({"field": "body", "code": "unknown_field",
                         "message": f"Unknown field(s): {', '.join(unknown)}."})

    limit = body.get("limit", 5)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= _TOP_LIMIT_MAX:
        problems.append({"field": "limit", "code": "out_of_range",
                         "message": f"limit must be a whole number between 1 and {_TOP_LIMIT_MAX}."})

    classes = body.get("classes")
    if classes is not None:
        if not isinstance(classes, list) or not classes or any(c not in _TOP_CLASSES for c in classes):
            problems.append({"field": "classes", "code": "unknown_class",
                             "message": f"classes must be a non-empty list from {', '.join(_TOP_CLASSES)}."})

    expiry = body.get("expiry")
    if expiry is not None:
        try:
            date.fromisoformat(str(expiry))
        except ValueError:
            problems.append({"field": "expiry", "code": "bad_date",
                             "message": "expiry must be a date as YYYY-MM-DD."})

    # One row per underlying in the option classes (regime_fit.one_per_underlying); off unless asked for.
    distinct = body.get("distinct", False)
    if not isinstance(distinct, bool):
        problems.append({"field": "distinct", "code": "not_a_boolean",
                         "message": "distinct must be true or false."})

    if problems:
        raise HTTPException(status_code=422, detail={"code": "invalid_input", "problems": problems})
    return {"limit": limit, "classes": classes, "expiry": str(expiry) if expiry else None, "distinct": distinct}


@router.post("/top")
async def strategy_top(request: Request) -> Dict[str, Any]:
    """The best `limit` ideas in each asset class, ranked by fit to the measured market regime and priced
    from the live end-of-day option chain. Reads only: nothing is written and nothing is sent to a broker.

    "Best" is fit to today's conditions, NOT performance — see services/strategy_plan/regime_fit.py, which
    records why a performance ranking is not available in this system. The caveat travels on the response
    as `ranking_note`, and the things this cannot do are listed in `gaps`."""
    user = await get_current_user(request)
    args = _parse_top_body(await _body(request))
    out = await regime_fit.build_top(request, user["user_id"], limit=args["limit"],
                                     classes=args["classes"], expiry=args["expiry"], distinct=args["distinct"])
    await store_trade_plans(trade_plans_of_top(out), user["user_id"])
    return out


def trade_plans_of_top(top: Dict[str, Any]) -> list:
    """Every TradePlan a /top answer carries: each option idea and alternative, and the cash class's ideas."""
    out = [i.get("trade_plan") for _c, i in regime_fit._all_ideas(top)]
    out += [i.get("trade_plan") for i in ((top.get("classes") or {}).get("cash") or {}).get("ideas") or []]
    return out


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


def _summary(doc: Dict[str, Any], lifecycle_status: Optional[str] = None) -> Dict[str, Any]:
    p = doc["plan"]
    s = p.get("summary") or {}
    return {"id": doc["_id"], "plan_id": doc["plan_id"], "saved_at": doc["saved_at"], "underlying": s.get("underlying"),
            "direction": s.get("direction"), "horizon": s.get("horizon"), "segment": s.get("segment"), "family": s.get("family"),
            "status": p.get("status"), "data_as_of": s.get("data_as_of"), "rules_version": p.get("rules_version"),
            "lifecycle": lifecycle_status or (p.get("lifecycle") or {}).get("status"), "sent_to_broker": False}


TRADES = "desk_paper_trades"


async def _derived_status(user_id: str, docs: list) -> Dict[str, str]:
    """{saved plan id: lifecycle status} DERIVED from the user's paper trades that cite one of its candidates'
    TradePlans or the saved plan itself (Phase 2.2: the plan's lifecycle used to be the constant "draft"). A saved plan
    no trade cites keeps "draft"."""
    by_tp = {tp_id: d["_id"] for d in docs for tp_id in ((d.get("plan") or {}).get("trade_plans") or {}).values()}
    ids = [d["_id"] for d in docs]
    if not ids:
        return {}
    trades = await db[TRADES].find({"user_id": user_id, "$or": [{"trade_plan_id": {"$in": list(by_tp)}},
                                                                 {"strategy_plan_id": {"$in": ids}}]}).to_list(1000)
    states: Dict[str, list] = {}
    for t in trades:
        owner = by_tp.get(t.get("trade_plan_id")) or t.get("strategy_plan_id")
        if owner:
            states.setdefault(owner, []).append(lifecycle.current_state(t))
    return {k: lifecycle.plan_status(v) for k, v in states.items()}


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
    derived = await _safe_derived(user["user_id"], docs)
    return {"plans": [_summary(d, derived.get(d["_id"])) for d in docs], "count": len(docs), "limit": MAX_LISTED, "max_saved": MAX_SAVED_PLANS}


async def _safe_derived(user_id: str, docs: list) -> Dict[str, str]:
    try:
        return await _derived_status(user_id, docs)
    except Exception as e:  # noqa: BLE001 — the saved plans still answer; the status falls back to the stored one, logged
        logger.warning("strategy: derived plan status unavailable: %r", e)
        return {}


@router.get("/plans/{plan_id}")
async def get_plan(request: Request, plan_id: str) -> Dict[str, Any]:
    user = await get_current_user(request)
    doc = await _own(user["user_id"], plan_id)
    derived = (await _safe_derived(user["user_id"], [doc])).get(doc["_id"])
    plan = doc["plan"]
    if derived:
        plan = {**plan, "lifecycle": {**(plan.get("lifecycle") or {}), "status": derived, "derived": True}}
    return {"id": doc["_id"], "saved_at": doc["saved_at"], "plan": plan, "sent_to_broker": False}


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
