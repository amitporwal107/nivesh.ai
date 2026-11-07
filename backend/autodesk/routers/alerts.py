"""Admin-only test of the Slack notifier (AD-AL-26). It sends one message marked TEST and changes nothing else."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException

from ..notify.runtime import get_notifier
from .api import _is_admin, current_user

router = APIRouter(prefix="/api/v1/alerts")


@router.post("/test")
async def send_test(user: dict = Depends(current_user)):
    if not _is_admin(user):
        raise HTTPException(403, "admin only")
    n = get_notifier()
    if not n.enabled:
        raise HTTPException(503, "Slack notifications are not configured on this environment")
    res = await asyncio.to_thread(n.transport.send, "[TEST] Autonomous Trading Desk: notification check. No action needed.")
    if not res.ok:
        raise HTTPException(502, res.reason or "send failed")
    return {"sent": True, "reason": None}
