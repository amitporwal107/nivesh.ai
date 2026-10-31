"""Suggestion cards for the Copilot home (services/suggestions). Signed in; each user sees only their own.

    GET  /api/suggestions?tab=for_you|market|my_trades|fno_lab&mode=investor|trader
         -> {schema, tab, mode, generated_at, window, tabs[{key,label,count}], suggestions[...], notices[...]}
    POST /api/suggestions/refresh            {tab, mode}      the same, with the market sources read again now
    POST /api/suggestions/{id}/feedback      {action}         dismissed | useful | not_relevant | completed
    GET  /api/suggestions/{id}/why                            the rule, its inputs with their as-of dates, the template

Every card is a question; clicking it asks the Copilot that question. Nothing here places an order.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict

from deps import db, get_current_user
from services.suggestions import engine, store

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

Tab = Literal["for_you", "market", "my_trades", "fno_lab"]
Mode = Literal["investor", "trader"]


class RefreshBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tab: Tab = "for_you"
    mode: Optional[Mode] = None


class FeedbackBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["dismissed", "useful", "not_relevant", "completed"]


async def _view(request: Request, tab: str, mode: Optional[str], fresh: bool) -> dict:
    user = await get_current_user(request)
    result = await engine.evaluate(db, user, request=request, mode=mode, fresh_read=fresh)
    return engine.tab_view(result, tab)


@router.get("/suggestions")
async def list_suggestions(request: Request, tab: Tab = Query("for_you"), mode: Optional[Mode] = Query(None)) -> dict:
    return await _view(request, tab, mode, fresh=False)


@router.post("/suggestions/refresh")
async def refresh_suggestions(request: Request, body: RefreshBody) -> dict:
    return await _view(request, body.tab, body.mode, fresh=True)


@router.post("/suggestions/{suggestion_id}/feedback")
async def suggestion_feedback(suggestion_id: str, request: Request, body: FeedbackBody) -> dict:
    user = await get_current_user(request)
    inst = await store.get_instance(db, user["user_id"], suggestion_id)
    if not inst:
        raise HTTPException(status_code=404, detail="suggestion_not_found")
    row = await store.add_feedback(db, inst, body.action, now=datetime.now(timezone.utc))
    engine.forget(user["user_id"])
    return {"id": suggestion_id, "action": body.action, "state": row["state"], "at": row["at"]}


@router.get("/suggestions/{suggestion_id}/why")
async def suggestion_why(suggestion_id: str, request: Request) -> dict:
    user = await get_current_user(request)
    inst = await store.get_instance(db, user["user_id"], suggestion_id)
    if not inst:
        raise HTTPException(status_code=404, detail="suggestion_not_found")
    rule = next((r for r in await store.rules(db) if r["_id"] == inst.get("rule_id")), None)
    return engine.why(inst, rule)

