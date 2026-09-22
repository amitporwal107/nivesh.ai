"""Saved chart layouts — docs/charting.md §38.8 ("Saved layouts, watchlist, compare") and §38.11
(API additions). The layouts API is the sibling of backend/routes/research_drawings.py (the other
writable state in the charting feature) and copies its patterns: per-user CRUD over MongoDB, the
same require_feature("charting") allowlist gate, the same "another user's row is 404, never 403"
ownership rule (a 403 would confirm the id exists -- exactly the leak the PRD wants avoided), and
the same error-shape convention (`detail` = "<field>: <reason>" for a validation failure, a single
lowercase token for a state failure such as "not_found" or "no_fields_to_update"). CSRF on the
mutating verbs (POST/PATCH/DELETE) is the existing origin-check middleware
(middleware.CsrfProtectMiddleware, registered globally in server.py) -- nothing route-specific
needed here, since it keys off the session cookie + method + /api prefix.

A saved layout holds (§38.8): symbol, timeframe, chart type, indicator instances with their
presets and styles, pane order and heights, visible range, drawing visibility and sidebar state.
It does NOT store a theme -- the chart follows the app theme (D-6, §38.9). "A new chart is
'Unnamed' until saved": name defaults to "Unnamed" when omitted.

Mongo collection `research_chart_layouts`, scoped by user exactly as `research_drawings` is.
Every field is size- and type-bounded (Pydantic `max_length` on every string/list/dict, `extra`
forbidden on every model) so a malformed or oversized payload is rejected with a reason code
rather than stored shapeless (§27 "every error must include a structured reason code").
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from deps import db
from feature_gate import require_feature

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/research/chart-layouts", tags=["research_chart_layouts"])
FLAG = "charting"

SYMBOL_PATTERN = r"^[A-Z0-9&\-]{1,32}$"
DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"

# P0 chart types (§38.7); heikin_ashi is named there as the P1 addition, already a fixed id.
CHART_TYPES = ("candles", "hollow_candles", "bars", "line", "area", "heikin_ashi")

# Size caps -- generous enough for any real workspace (a chart realistically carries a handful of
# indicator instances and panes), small enough that a shapeless/abusive payload is rejected rather
# than stored.
MAX_INDICATORS = 40
MAX_PANES = 20
MAX_DRAWING_VISIBILITY = 500
MAX_STYLE_KEYS = 20
LIST_CAP = 500  # matches research_drawings.list_drawings' to_list(500)


class IndicatorInstance(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instance_id: str = Field(min_length=1, max_length=64)
    indicator_id: str = Field(min_length=1, max_length=64)
    preset_id: str = Field(min_length=1, max_length=64)
    pane_index: int = Field(ge=0, le=50)
    visible: bool = True
    style: Dict[str, Any] = Field(default_factory=dict, max_length=MAX_STYLE_KEYS)


class Pane(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pane_id: str = Field(min_length=1, max_length=64)
    order: int = Field(ge=0, le=100)
    height: float = Field(gt=0, le=5000)
    collapsed: bool = False


class VisibleRange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    from_date: str = Field(pattern=DATE_PATTERN)
    to_date: str = Field(pattern=DATE_PATTERN)


class SidebarState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    collapsed: bool = False
    active_tab: Optional[str] = Field(default=None, max_length=32)


class LayoutCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(default="Unnamed", max_length=120)
    symbol: str = Field(pattern=SYMBOL_PATTERN)
    timeframe: str = Field(default="1D", min_length=1, max_length=8)
    chart_type: str = Field(default="candles", max_length=32)
    indicators: List[IndicatorInstance] = Field(default_factory=list, max_length=MAX_INDICATORS)
    panes: List[Pane] = Field(default_factory=list, max_length=MAX_PANES)
    visible_range: Optional[VisibleRange] = None
    drawing_visibility: Dict[str, bool] = Field(default_factory=dict, max_length=MAX_DRAWING_VISIBILITY)
    sidebar_state: Optional[SidebarState] = None


class LayoutUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Optional[str] = Field(default=None, max_length=120)
    symbol: Optional[str] = Field(default=None, pattern=SYMBOL_PATTERN)
    timeframe: Optional[str] = Field(default=None, min_length=1, max_length=8)
    chart_type: Optional[str] = Field(default=None, max_length=32)
    indicators: Optional[List[IndicatorInstance]] = Field(default=None, max_length=MAX_INDICATORS)
    panes: Optional[List[Pane]] = Field(default=None, max_length=MAX_PANES)
    visible_range: Optional[VisibleRange] = None
    drawing_visibility: Optional[Dict[str, bool]] = Field(default=None, max_length=MAX_DRAWING_VISIBILITY)
    sidebar_state: Optional[SidebarState] = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in doc.items() if k != "_id"}


def _validate_chart_type(chart_type: str) -> None:
    if chart_type not in CHART_TYPES:
        raise HTTPException(status_code=422, detail=f"chart_type: must be one of {list(CHART_TYPES)}")


@router.post("", status_code=201)
async def create_layout(payload: LayoutCreate, user: dict = Depends(require_feature(FLAG))) -> Dict[str, Any]:
    _validate_chart_type(payload.chart_type)
    now = _now()
    doc = {
        "layout_id": str(uuid.uuid4()),
        "user_id": user["user_id"],
        "name": payload.name,
        "symbol": payload.symbol,
        "timeframe": payload.timeframe,
        "chart_type": payload.chart_type,
        "indicators": [i.model_dump() for i in payload.indicators],
        "panes": [p.model_dump() for p in payload.panes],
        "visible_range": payload.visible_range.model_dump() if payload.visible_range else None,
        "drawing_visibility": dict(payload.drawing_visibility),
        "sidebar_state": payload.sidebar_state.model_dump() if payload.sidebar_state else None,
        "created_at": now,
        "updated_at": now,
    }
    await db.research_chart_layouts.insert_one(doc)
    return _clean(doc)


@router.get("")
async def list_layouts(user: dict = Depends(require_feature(FLAG))) -> List[Dict[str, Any]]:
    return await db.research_chart_layouts.find(
        {"user_id": user["user_id"]}, {"_id": 0}
    ).sort("created_at", -1).to_list(LIST_CAP)


@router.patch("/{layout_id}")
async def update_layout(layout_id: str, payload: LayoutUpdate,
                        user: dict = Depends(require_feature(FLAG))) -> Dict[str, Any]:
    current = await db.research_chart_layouts.find_one({"layout_id": layout_id, "user_id": user["user_id"]})
    if not current:
        raise HTTPException(status_code=404, detail="not_found")

    if payload.chart_type is not None:
        _validate_chart_type(payload.chart_type)

    changes: Dict[str, Any] = {}
    if payload.name is not None:
        changes["name"] = payload.name
    if payload.symbol is not None:
        changes["symbol"] = payload.symbol
    if payload.timeframe is not None:
        changes["timeframe"] = payload.timeframe
    if payload.chart_type is not None:
        changes["chart_type"] = payload.chart_type
    if payload.indicators is not None:
        changes["indicators"] = [i.model_dump() for i in payload.indicators]
    if payload.panes is not None:
        changes["panes"] = [p.model_dump() for p in payload.panes]
    if payload.visible_range is not None:
        changes["visible_range"] = payload.visible_range.model_dump()
    if payload.drawing_visibility is not None:
        changes["drawing_visibility"] = dict(payload.drawing_visibility)
    if payload.sidebar_state is not None:
        changes["sidebar_state"] = payload.sidebar_state.model_dump()
    if not changes:
        raise HTTPException(status_code=400, detail="no_fields_to_update")

    changes["updated_at"] = _now()
    res = await db.research_chart_layouts.update_one(
        {"layout_id": layout_id, "user_id": user["user_id"]}, {"$set": changes},
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="not_found")
    return _clean(await db.research_chart_layouts.find_one(
        {"layout_id": layout_id, "user_id": user["user_id"]}, {"_id": 0}
    ))


@router.delete("/{layout_id}")
async def delete_layout(layout_id: str, user: dict = Depends(require_feature(FLAG))) -> Dict[str, str]:
    res = await db.research_chart_layouts.delete_one({"layout_id": layout_id, "user_id": user["user_id"]})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="not_found")
    return {"status": "deleted", "layout_id": layout_id}
