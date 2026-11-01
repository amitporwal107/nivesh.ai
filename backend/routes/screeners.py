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
    POST   /screeners/run        — run a rule list on the day's stock data (read-only)
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from deps import db, get_current_user
from services import screener_run
from services.copilot_tools import daas_client, stock_intelligence  # noqa: F401  (patched by tests/test_screeners_run.py)

logger = logging.getLogger(__name__)

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


# ── run a screen ─────────────────────────────────────────────────────────────
# A run reads the whole day of nidp.stock_features_daily once, through the same
# data-platform call the chat screener uses (nidp_stock_screener), and shapes the
# matches with the same builder (build_stock_screener_widget), so the screen and
# the chat render one widget contract.
#
# Nothing is filtered on the data platform. The response has to say how many
# stocks carry a value for each rule's metric, and that can only be counted on
# rows no rule has cut yet: a platform-side "ROE >= 20" on a day with no ROE
# returns no rows, which reads the same as "ROE is there, nothing is that high".

# The screen itself lives in services/screener_run.py (moved there 2026-11-01 so the Copilot chat runs the same code as this page).
# The names below are kept importable from here: tests/test_screeners_run.py and other callers use them.
ScreenRunCondition = screener_run.ScreenRunCondition
ScreenRunRequest = screener_run.ScreenRunRequest
_MF_METRICS = screener_run.MF_METRICS
_DAY_READ_LIMIT = screener_run.DAY_READ_LIMIT
_CAP_BUCKETS = screener_run.CAP_BUCKETS


@router.post("/screeners/run")
async def run_screener(request: Request, payload: ScreenRunRequest) -> Dict[str, Any]:
    await get_current_user(request)
    try:
        return await screener_run.run_screen(payload)
    except screener_run.UnknownMetric as exc:
        raise HTTPException(status_code=422, detail=str(exc))


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
