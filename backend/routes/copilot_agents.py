"""Public agent + model picker endpoints used by the Chat UI.

Doc 02 §2.2 — the agent picker lists these.
Doc 06       — model picker reads /models.
"""
from __future__ import annotations

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel, Field
from typing import Optional

from datetime import datetime, timezone

from deps import db, get_current_user
from services import copilot_agents

router = APIRouter(prefix="/api/copilot", tags=["copilot-agents"])


@router.get("/agents")
async def list_agents(request: Request):
    """Return all 7 agents (including `auto`) so the picker UI can render."""
    await get_current_user(request)
    return {"agents": copilot_agents.agent_metadata()}


@router.get("/models/picker")
async def list_models(request: Request):
    """Return the 3 supported LLM backends. Default = gpt-4o.

    Note: lives at /models/picker (not /models) to avoid collision with
    the legacy /api/copilot/models endpoint in routes/copilot.py which
    exposes a different shape (key/tier/price_hint) for the
    NiveshCopilotDrawer.
    """
    await get_current_user(request)
    return {"models": copilot_agents.model_metadata()}


class RouteIntentRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)


@router.post("/agents/route")
async def route_intent(request: Request, payload: RouteIntentRequest):
    """Deterministic intent router. Frontend calls this BEFORE sending a
    chat message so it can render the matching agent ribbon immediately
    (and show a "Handed off" divider if the routed agent differs from the
    previous turn's agent)."""
    await get_current_user(request)
    agent_id = copilot_agents.route_intent(payload.message)
    spec = copilot_agents.get_agent(agent_id)
    return {
        "agent_id": agent_id,
        "agent": {
            "id": spec.id, "label": spec.label, "icon": spec.icon,
            "one_liner": spec.one_liner,
        } if spec else None,
    }


class AgentOneShotRequest(BaseModel):
    agent_id: str
    model_id: Optional[str] = None
    message: str = Field(..., min_length=1, max_length=4000)
    session_id: Optional[str] = None
    system_prompt: Optional[str] = None


@router.post("/agents/oneshot")
async def agent_oneshot(request: Request, payload: AgentOneShotRequest):
    """Single-turn agent call, used by widget-producing endpoints
    (e.g. compose a rationale for a Fund card without going through the
    full streaming chat loop). NOT used for the primary chat stream —
    that path stays on /api/chat/stream.

    Returns: {"text": "<assistant prose>"}.
    """
    user = await get_current_user(request)
    user_id = user["user_id"]
    spec = copilot_agents.get_agent(payload.agent_id)
    if not spec:
        raise HTTPException(status_code=400, detail=f"Unknown agent_id: {payload.agent_id}")

    system_prompt = payload.system_prompt or (
        f"You are the {spec.label} for Nivesh AI, an Indian-market financial "
        f"copilot. {spec.one_liner} Speak in second person, present tense. "
        "Lead with the action. One number per sentence. Never invent data."
    )
    text = await copilot_agents.run_agent_oneshot(
        agent_id=payload.agent_id,
        model_id=payload.model_id or "gpt-4o",
        system_prompt=system_prompt,
        user_message=payload.message,
        session_id=payload.session_id or f"oneshot:{user_id}",
    )
    return {"text": text, "agent_id": payload.agent_id, "model_id": payload.model_id or "gpt-4o"}


class MessageFeedbackRequest(BaseModel):
    message_id: str = Field(..., min_length=1, max_length=64)
    session_id: Optional[str] = None
    rating: str = Field(..., pattern="^(up|down)$")
    agent_id: Optional[str] = None
    comment: Optional[str] = Field(None, max_length=2000)


@router.post("/feedback")
async def message_feedback(request: Request, payload: MessageFeedbackRequest):
    """Record a thumbs-up / thumbs-down on an assistant message. The chat UI
    fires this fire-and-forget when the user clicks the toolbar under a
    bubble. We persist to `copilot_feedback` for offline review — no
    business logic depends on the response shape beyond {ok: true}."""
    user = await get_current_user(request)
    doc = {
        "user_id": user["user_id"],
        "message_id": payload.message_id,
        "session_id": payload.session_id,
        "rating": payload.rating,
        "agent_id": payload.agent_id,
        "comment": payload.comment,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        await db.copilot_feedback.insert_one(doc)
    except Exception:
        # Persistence failure is non-blocking for the user; surface a soft
        # ok so the toolbar still reflects the click.
        return {"ok": False}
    return {"ok": True}
