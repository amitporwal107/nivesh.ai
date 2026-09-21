"""Fail-closed feature gate for API routes: `Depends(require_feature("move_odds"))`.

feature_flags keeps flags in each worker's memory, loaded at startup; an admin change reaches only the worker that
served it. This gate re-reads the persisted flags when this worker's copy is older than REFRESH_SECONDS, so turning a
flag off takes effect everywhere within that window. It gates on the logged-in person, not on a client profile an
advisor is acting for, and any failure to read the flag state denies access.
"""
from __future__ import annotations

import logging
import time
from typing import Awaitable, Callable, Optional

from fastapi import HTTPException, Request

import feature_flags as ff

logger = logging.getLogger(__name__)
REFRESH_SECONDS = 30.0
_state = {"at": float("-inf")}


async def refresh_if_stale(db, now: Optional[float] = None) -> bool:
    t = time.monotonic() if now is None else now
    if t - _state["at"] < REFRESH_SECONDS:
        return False
    await ff.hydrate_from_db(db)
    _state["at"] = t
    return True


async def fresh_user_feature_map(db, email: Optional[str], now: Optional[float] = None) -> dict:
    """The per-user feature map for /auth/me and /user/profile, refreshed on the same rule as the gate. Without this,
    each worker answered from its startup copy, so an admin allowlist change made a flag flip between true and false
    depending on which worker served the request. A failed refresh keeps this worker's copy: the map only decides what
    the UI shows, and every gated API route still refuses on its own."""
    try:
        await refresh_if_stale(db, now)
    except Exception as e:  # noqa: BLE001 — UI visibility only; routes stay fail-closed
        logger.warning("feature flags refresh failed for the profile map: %s", e)
    return ff.user_feature_map(email)


def require_feature(flag: str, *, resolve_user: Optional[Callable[[Request], Awaitable[dict]]] = None,
                    get_db: Optional[Callable[[], object]] = None, clock: Optional[Callable[[], float]] = None):
    async def dependency(request: Request) -> dict:
        if resolve_user is None:
            from deps import get_current_user as _resolve
        else:
            _resolve = resolve_user
        if get_db is None:
            from deps import db as _db
        else:
            _db = get_db()
        user = await _resolve(request)
        try:
            await refresh_if_stale(_db, clock() if clock else None)
        except Exception as e:  # noqa: BLE001 — fail closed
            logger.warning("feature flags unreadable, denying %s: %s", flag, e)
            raise HTTPException(status_code=503, detail="feature_state_unavailable")
        email = user.get("email")
        owner = user.get("_session_user_id")
        if owner and owner != user.get("user_id"):
            doc = await _db.users.find_one({"user_id": owner}, {"_id": 0, "email": 1})
            email = (doc or {}).get("email")
        if not ff.is_enabled(flag, email):
            raise HTTPException(status_code=403, detail="feature_not_enabled")
        return user
    return dependency
