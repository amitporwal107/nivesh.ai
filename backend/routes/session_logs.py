"""Session log viewer API — powers Settings → Logs & Diagnostics.

A signed-in user can turn on verbose logging for their own session to
troubleshoot a problem. On enable we mint a random debug-session id owned by
that user; the frontend then sends it on every request via the
X-Nivesh-Debug-Session header. RequestLoggingMiddleware buffers each request's
server-side log records into Redis (services.session_log_store), and this router
lets the *same* user read them back.

Access is strictly self-scoped: a session's logs are only ever returned to the
user who owns it (checked against the Redis owner mapping). Server log messages
are already email/PAN-masked by core.logging_config. Logging is OFF by default;
the user opts in per session and it auto-expires.
"""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from deps import get_current_user
from services import session_log_store as store

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


class _DisableBody(BaseModel):
    sid: str | None = None


@router.post("/session-logs/enable")
async def enable_session_logs(request: Request):
    """Start capturing server logs for the caller's session. Returns a debug
    session id the client must echo via the X-Nivesh-Debug-Session header."""
    user = await get_current_user(request)
    if not await store.available():
        raise HTTPException(
            status_code=503,
            detail="Session logging is unavailable (log store not configured).",
        )
    sid = uuid.uuid4().hex
    if not await store.register_owner(sid, user["user_id"]):
        raise HTTPException(status_code=503, detail="Could not start session logging.")
    logger.info("session logging enabled", extra={"eventType": "BUSINESS_EVENT"})
    return {"enabled": True, "sid": sid, "ttl_seconds": store.TTL_SECONDS}


@router.post("/session-logs/disable")
async def disable_session_logs(request: Request, body: _DisableBody):
    """Stop capturing and purge the caller's buffered server logs."""
    user = await get_current_user(request)
    sid = body.sid
    if sid:
        owner = await store.get_owner(sid)
        if owner == user["user_id"]:
            await store.clear(sid)
    return {"enabled": False}


@router.get("/session-logs")
async def get_session_logs(
    request: Request,
    sid: str = Query(..., min_length=8, max_length=64),
    limit: int = Query(default=1000, ge=1, le=store.MAX_ENTRIES),
):
    """Return the caller's buffered server logs for a debug session."""
    user = await get_current_user(request)
    owner = await store.get_owner(sid)
    if owner is None:
        raise HTTPException(status_code=404, detail="Session not found or expired.")
    if owner != user["user_id"]:
        raise HTTPException(status_code=403, detail="Not your session.")
    logs = await store.read(sid, limit=limit)
    return {"sid": sid, "count": len(logs), "logs": logs}


@router.delete("/session-logs")
async def clear_session_logs(
    request: Request,
    sid: str = Query(..., min_length=8, max_length=64),
):
    """Clear the buffered server logs for a debug session (keeps it enabled)."""
    user = await get_current_user(request)
    owner = await store.get_owner(sid)
    if owner is None:
        raise HTTPException(status_code=404, detail="Session not found or expired.")
    if owner != user["user_id"]:
        raise HTTPException(status_code=403, detail="Not your session.")
    await store.clear(sid, keep_owner=True)
    return {"cleared": True}
