"""Idempotency-Key guard for write-once endpoints.

Usage in a route::

    from core.idempotency import IdempotencyState, check_idempotency, store_idempotency_result

    @router.post("/portfolio/import-connect")
    async def my_route(
        idem: IdempotencyState = Depends(check_idempotency),
    ):
        if idem.cached is not None:
            return idem.cached          # replay cached response
        result = ...                    # actual work
        await store_idempotency_result(idem, result)
        return result

Keys are stored in MongoDB (``idempotency_keys`` collection) with a 24 h TTL.
A missing or empty ``Idempotency-Key`` header means no idempotency protection —
the request proceeds normally and is NOT cached.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import Header

logger = logging.getLogger(__name__)

_TTL_HOURS = 24


@dataclass
class IdempotencyState:
    """Carries the parsed key and any already-cached result into the route."""
    key: Optional[str]          # None = header absent → no protection
    cached: Optional[Any]       # non-None = replay this; skip real work
    _db: Any = field(default=None, repr=False)


async def check_idempotency(
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
) -> IdempotencyState:
    """FastAPI dependency: look up ``Idempotency-Key`` in MongoDB.

    - Key absent → returns ``IdempotencyState(key=None, cached=None)``; no-op.
    - Key present, not seen before → ``cached=None``; route must call
      ``store_idempotency_result`` after building its response.
    - Key present, already stored → ``cached=<dict>``; route should return it.
    """
    if not idempotency_key:
        return IdempotencyState(key=None, cached=None)

    try:
        from deps import db  # import inside fn to avoid circular at module load
        doc = await db.idempotency_keys.find_one(
            {"key": idempotency_key}, {"_id": 0, "result": 1}
        )
        if doc:
            logger.info(
                "Idempotency replay",
                extra={"eventType": "IDEMPOTENCY_REPLAY", "key": idempotency_key},
            )
            return IdempotencyState(key=idempotency_key, cached=doc["result"], _db=db)
        return IdempotencyState(key=idempotency_key, cached=None, _db=db)
    except Exception:
        # If the DB lookup fails, let the request through without caching
        # (fail-open: idempotency is best-effort, not a hard gate).
        logger.warning(
            "Idempotency key lookup failed — proceeding without protection",
            extra={"key": idempotency_key},
            exc_info=True,
        )
        return IdempotencyState(key=idempotency_key, cached=None, _db=None)


async def store_idempotency_result(state: IdempotencyState, result: Any) -> None:
    """Persist the route's response so future requests with the same key replay it.

    Safe to call even when ``state.key`` is None (no-op) or when the DB is
    unavailable (logs a warning, never raises).
    """
    if not state.key or state._db is None:
        return
    expires_at = datetime.now(timezone.utc) + timedelta(hours=_TTL_HOURS)
    try:
        await state._db.idempotency_keys.update_one(
            {"key": state.key},
            {
                "$setOnInsert": {
                    "key": state.key,
                    "result": result,
                    "expires_at": expires_at,
                    "created_at": datetime.now(timezone.utc),
                }
            },
            upsert=True,
        )
        logger.debug(
            "Idempotency key stored",
            extra={"eventType": "IDEMPOTENCY_STORE", "key": state.key},
        )
    except Exception:
        logger.warning(
            "Failed to store idempotency key — replay will not work for this request",
            extra={"key": state.key},
            exc_info=True,
        )
