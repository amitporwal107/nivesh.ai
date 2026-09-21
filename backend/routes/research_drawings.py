"""Manual chart drawings — the one writable state in the charting feature (everything else is a
read-only snapshot, backend/routes/research_chart.py). Per-user CRUD over MongoDB, following the
same shape as backend/routes/screeners.py (saved_screeners).

Endpoints (SNAPSHOT_SCHEMA.md "Drawings"), all under /api/research/drawings:
    POST   ""              create a drawing
    GET    "?symbol="      list the caller's drawings for one symbol
    GET    "/{id}"         fetch one (not in the literal contract table, but TC-13 requires GET
                            to be one of the ownership-checked verbs alongside PATCH/DELETE, and a
                            resource with PATCH+DELETE by id with no matching GET by id would be an
                            odd asymmetry -- added for that reason, flagged to the orchestrator)
    PATCH  "/{id}"         update fields
    DELETE "/{id}"         delete

Mongo collection `research_drawings`. Every query is scoped to the caller's own user_id; a
drawing_id that exists but belongs to someone else is 404, never 403 -- 403 would confirm the id
exists, which is exactly the leak PRD wants avoided. Shape validation (PRD §7.3 / SNAPSHOT_SCHEMA.md):
TRENDLINE needs exactly 2 anchor_points, HORIZONTAL_LINE needs exactly 1. Same feature gate as the
read-only chart API (require_feature("charting"), NI-1: Kite-derived prices, never public).
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from deps import db
from feature_gate import require_feature

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/research/drawings", tags=["research_drawings"])
FLAG = "charting"

SYMBOL_PATTERN = r"^[A-Z0-9&\-]{1,32}$"
DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"

DRAWING_TYPES = ("TRENDLINE", "HORIZONTAL_LINE")
_REQUIRED_ANCHORS = {"TRENDLINE": 2, "HORIZONTAL_LINE": 1}


class Anchor(BaseModel):
    date: str = Field(pattern=DATE_PATTERN)
    price: float


class DrawingCreate(BaseModel):
    symbol: str = Field(pattern=SYMBOL_PATTERN)
    timeframe: str = Field(default="1D", min_length=1, max_length=8)
    drawing_type: str
    anchor_points: List[Anchor]
    style: Dict[str, Any] = Field(default_factory=dict)


class DrawingUpdate(BaseModel):
    symbol: Optional[str] = Field(default=None, pattern=SYMBOL_PATTERN)
    timeframe: Optional[str] = Field(default=None, min_length=1, max_length=8)
    drawing_type: Optional[str] = None
    anchor_points: Optional[List[Anchor]] = None
    style: Optional[Dict[str, Any]] = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in doc.items() if k != "_id"}


def _validate_shape(drawing_type: str, anchor_points: list) -> None:
    if drawing_type not in DRAWING_TYPES:
        raise HTTPException(status_code=422, detail=f"drawing_type: must be one of {list(DRAWING_TYPES)}")
    need = _REQUIRED_ANCHORS[drawing_type]
    if len(anchor_points) != need:
        raise HTTPException(status_code=422,
                            detail=f"anchor_points: {drawing_type} needs exactly {need} anchor point(s), got {len(anchor_points)}")


@router.post("", status_code=201)
async def create_drawing(payload: DrawingCreate, user: dict = Depends(require_feature(FLAG))) -> Dict[str, Any]:
    _validate_shape(payload.drawing_type, payload.anchor_points)
    now = _now()
    doc = {
        "drawing_id": str(uuid.uuid4()),
        "user_id": user["user_id"],
        "symbol": payload.symbol,
        "timeframe": payload.timeframe,
        "drawing_type": payload.drawing_type,
        "anchor_points": [a.model_dump() for a in payload.anchor_points],
        "style": payload.style,
        "created_at": now,
        "updated_at": now,
    }
    await db.research_drawings.insert_one(doc)
    return _clean(doc)


@router.get("")
async def list_drawings(symbol: str = Query(..., pattern=SYMBOL_PATTERN),
                        user: dict = Depends(require_feature(FLAG))) -> List[Dict[str, Any]]:
    return await db.research_drawings.find(
        {"user_id": user["user_id"], "symbol": symbol}, {"_id": 0}
    ).sort("created_at", 1).to_list(500)


@router.get("/{drawing_id}")
async def get_drawing(drawing_id: str, user: dict = Depends(require_feature(FLAG))) -> Dict[str, Any]:
    doc = await db.research_drawings.find_one(
        {"drawing_id": drawing_id, "user_id": user["user_id"]}, {"_id": 0}
    )
    if not doc:
        raise HTTPException(status_code=404, detail="not_found")
    return doc


@router.patch("/{drawing_id}")
async def update_drawing(drawing_id: str, payload: DrawingUpdate,
                         user: dict = Depends(require_feature(FLAG))) -> Dict[str, Any]:
    current = await db.research_drawings.find_one({"drawing_id": drawing_id, "user_id": user["user_id"]})
    if not current:
        raise HTTPException(status_code=404, detail="not_found")

    changes: Dict[str, Any] = {}
    if payload.symbol is not None:
        changes["symbol"] = payload.symbol
    if payload.timeframe is not None:
        changes["timeframe"] = payload.timeframe
    if payload.drawing_type is not None:
        changes["drawing_type"] = payload.drawing_type
    if payload.anchor_points is not None:
        changes["anchor_points"] = [a.model_dump() for a in payload.anchor_points]
    if payload.style is not None:
        changes["style"] = payload.style
    if not changes:
        raise HTTPException(status_code=400, detail="no_fields_to_update")

    # Validate the shape that would RESULT from this patch, not just the fields being changed --
    # e.g. PATCHing anchor_points alone must still respect the (possibly unchanged) drawing_type.
    resulting_type = changes.get("drawing_type", current["drawing_type"])
    resulting_anchors = changes.get("anchor_points", current["anchor_points"])
    _validate_shape(resulting_type, resulting_anchors)

    changes["updated_at"] = _now()
    res = await db.research_drawings.update_one(
        {"drawing_id": drawing_id, "user_id": user["user_id"]}, {"$set": changes},
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="not_found")
    return _clean(await db.research_drawings.find_one(
        {"drawing_id": drawing_id, "user_id": user["user_id"]}, {"_id": 0}
    ))


@router.delete("/{drawing_id}")
async def delete_drawing(drawing_id: str, user: dict = Depends(require_feature(FLAG))) -> Dict[str, str]:
    res = await db.research_drawings.delete_one({"drawing_id": drawing_id, "user_id": user["user_id"]})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="not_found")
    return {"status": "deleted", "drawing_id": drawing_id}
