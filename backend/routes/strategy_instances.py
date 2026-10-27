"""Strategy instances (Trade Desk › Strategy Lab › Build a trade, step 4: Save version · Clone · Adjust legs).

POST /api/desk/strategy/instances                  save a structure as a new instance, version 1  → 201 {instance}
POST /api/desk/strategy/instances/{id}/versions    append version N+1 (versions are never edited)  → 201 {instance}
POST /api/desk/strategy/instances/{id}/clone       a new instance whose version 1 copies the latest → 201 {instance}
GET  /api/desk/strategy/instances                  your instances, most recently updated first, each with its latest version
GET  /api/desk/strategy/instances/{id}             one instance with every version

Mongo `desk_strategy_instances`, scoped to the signed-in user: another user's instance answers 404 instance_not_found, the
same as a missing one. Bodies are validated by services/strategy_plan/instances.py (422 {code, message}). Writes pass
through the app's CSRF middleware like the other desk writes. An instance is a saved layout of legs, not a trade: it is
not priced, sized or risk-checked here (the payoff route and the risk service do that) and nothing is sent to a broker.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request

from deps import db, get_current_user
from services.strategy_plan import instances as inst

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/desk/strategy/instances", tags=["desk"])

_ID_MAX = 64


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _stamp() -> str:
    return utcnow().isoformat()


async def _body(request: Request) -> Any:
    try:
        return json.loads(await request.body())
    except ValueError:
        raise HTTPException(status_code=422, detail={"code": "invalid_body", "message": "The body is not JSON."})


async def _own(user_id: str, instance_id: str) -> Dict[str, Any]:
    doc = await db[inst.COLLECTION].find_one({"_id": instance_id, "user_id": user_id}) \
        if 0 < len(instance_id) <= _ID_MAX else None
    if doc is None:
        raise HTTPException(status_code=404, detail="instance_not_found")
    return doc


async def _insert(uid: str, doc: Dict[str, Any]) -> None:
    if await db[inst.COLLECTION].count_documents({"user_id": uid}) >= inst.MAX_INSTANCES:
        raise HTTPException(status_code=409, detail={"code": "instance_limit",
                                                     "message": f"At most {inst.MAX_INSTANCES} saved instances."})
    await db[inst.COLLECTION].insert_one(doc)
    if await db[inst.COLLECTION].count_documents({"user_id": uid}) > inst.MAX_INSTANCES:
        # two saves that both counted 199 can both insert; the later count catches it and takes ours back
        await db[inst.COLLECTION].delete_one({"_id": doc["_id"], "user_id": uid})
        raise HTTPException(status_code=409, detail={"code": "instance_limit",
                                                     "message": f"At most {inst.MAX_INSTANCES} saved instances."})


@router.post("", status_code=201)
async def create_instance(request: Request) -> Dict[str, Any]:
    user = await get_current_user(request)
    uid = user["user_id"]
    try:
        doc = inst.new_instance(uid, await _body(request), instance_id=uuid.uuid4().hex, at=_stamp())
    except inst.InstanceInputError as exc:
        raise HTTPException(status_code=422, detail=exc.detail())
    await _insert(uid, doc)
    logger.info("desk: user %s saved strategy instance %s (%s)", uid, doc["_id"], doc["underlying"])
    return {"instance": inst.public(doc)}


@router.get("")
async def list_instances(request: Request) -> Dict[str, Any]:
    user = await get_current_user(request)
    docs = await db[inst.COLLECTION].find({"user_id": user["user_id"]}).sort("updated_at", -1).to_list(inst.MAX_LISTED)
    return {"instances": [inst.public(d, latest_only=True) for d in docs], "count": len(docs), "limit": inst.MAX_LISTED,
            "max_saved": inst.MAX_INSTANCES, "sent_to_broker": False}


@router.get("/{instance_id}")
async def get_instance(request: Request, instance_id: str) -> Dict[str, Any]:
    user = await get_current_user(request)
    return {"instance": inst.public(await _own(user["user_id"], instance_id))}


@router.post("/{instance_id}/versions", status_code=201)
async def add_version(request: Request, instance_id: str) -> Dict[str, Any]:
    user = await get_current_user(request)
    uid = user["user_id"]
    doc = await _own(uid, instance_id)
    at = _stamp()
    try:
        version = inst.next_version(doc, await _body(request), at=at)
    except inst.InstanceInputError as exc:
        raise HTTPException(status_code=409 if exc.code == "version_limit" else 422, detail=exc.detail())
    # Only on top of the version this request read: two saves at once cannot both become version N+1.
    res = await db[inst.COLLECTION].update_one(
        {"_id": instance_id, "user_id": uid, "latest_version": doc["latest_version"]},
        {"$push": {"versions": version}, "$set": {"latest_version": version["version"], "updated_at": at}})
    if res.matched_count == 0:
        raise HTTPException(status_code=409, detail={"code": "version_conflict",
                                                     "message": "Another version was saved at the same time; reload and save again."})
    logger.info("desk: user %s saved version %s of strategy instance %s", uid, version["version"], instance_id)
    return {"instance": inst.public(await _own(uid, instance_id))}


@router.post("/{instance_id}/clone", status_code=201)
async def clone_instance(request: Request, instance_id: str) -> Dict[str, Any]:
    user = await get_current_user(request)
    uid = user["user_id"]
    src = await _own(uid, instance_id)
    doc = inst.clone_of(src, uid, instance_id=uuid.uuid4().hex, at=_stamp())
    await _insert(uid, doc)
    logger.info("desk: user %s cloned strategy instance %s into %s", uid, instance_id, doc["_id"])
    return {"instance": inst.public(doc)}
