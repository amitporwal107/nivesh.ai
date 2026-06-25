"""Saved stock screeners — per-user CRUD over MongoDB.

A saved screener stores the natural-language query (the same string the copilot
parser consumes) plus the structured builder conditions so it can be reloaded
into the visual Query Builder for editing. Scoped to the authenticated user.

Endpoints (all under /api):
    GET    /screeners            — list the user's saved screeners (newest first)
    POST   /screeners            — create one
    GET    /screeners/{id}       — fetch one
    PUT    /screeners/{id}       — update name / query / conditions / bucket
    DELETE /screeners/{id}       — delete one
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from deps import db, get_current_user

router = APIRouter(prefix="/api")


class ScreenerCondition(BaseModel):
    key: str
    op: str = "over"                 # "over" | "under"
    value: str = ""


class ScreenerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    query: str = Field(min_length=1, max_length=600)
    conditions: List[ScreenerCondition] = Field(default_factory=list)
    bucket: Optional[str] = None     # "" | "large" | "mid" | "small" | "micro"


class ScreenerUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=80)
    query: Optional[str] = Field(default=None, min_length=1, max_length=600)
    conditions: Optional[List[ScreenerCondition]] = None
    bucket: Optional[str] = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in doc.items() if k != "_id"}


@router.get("/screeners")
async def list_screeners(request: Request) -> List[Dict[str, Any]]:
    user = await get_current_user(request)
    return await db.saved_screeners.find(
        {"user_id": user["user_id"]}, {"_id": 0}
    ).sort("updated_at", -1).to_list(200)


@router.post("/screeners")
async def create_screener(request: Request, payload: ScreenerCreate) -> Dict[str, Any]:
    user = await get_current_user(request)
    now = _now()
    doc = {
        "screener_id": f"scr_{uuid.uuid4().hex[:12]}",
        "user_id": user["user_id"],
        "name": payload.name.strip(),
        "query": payload.query.strip(),
        "conditions": [c.model_dump() for c in payload.conditions],
        "bucket": payload.bucket or "",
        "created_at": now,
        "updated_at": now,
    }
    await db.saved_screeners.insert_one(doc)
    return _clean(doc)


@router.get("/screeners/{screener_id}")
async def get_screener(request: Request, screener_id: str) -> Dict[str, Any]:
    user = await get_current_user(request)
    doc = await db.saved_screeners.find_one(
        {"screener_id": screener_id, "user_id": user["user_id"]}, {"_id": 0}
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Screener not found")
    return doc


@router.put("/screeners/{screener_id}")
async def update_screener(request: Request, screener_id: str, payload: ScreenerUpdate) -> Dict[str, Any]:
    user = await get_current_user(request)
    changes: Dict[str, Any] = {}
    if payload.name is not None:       changes["name"] = payload.name.strip()
    if payload.query is not None:      changes["query"] = payload.query.strip()
    if payload.conditions is not None: changes["conditions"] = [c.model_dump() for c in payload.conditions]
    if payload.bucket is not None:     changes["bucket"] = payload.bucket
    if not changes:
        raise HTTPException(status_code=400, detail="No fields to update")
    changes["updated_at"] = _now()
    res = await db.saved_screeners.update_one(
        {"screener_id": screener_id, "user_id": user["user_id"]},
        {"$set": changes},
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Screener not found")
    return await db.saved_screeners.find_one(
        {"screener_id": screener_id, "user_id": user["user_id"]}, {"_id": 0}
    )


@router.delete("/screeners/{screener_id}")
async def delete_screener(request: Request, screener_id: str) -> Dict[str, str]:
    user = await get_current_user(request)
    res = await db.saved_screeners.delete_one(
        {"screener_id": screener_id, "user_id": user["user_id"]}
    )
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Screener not found")
    return {"status": "deleted", "screener_id": screener_id}
