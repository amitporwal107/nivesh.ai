"""Two-layer dashboard cache.

L1 — Redis: key ``dashboard:{user_id}:{dtype}``, TTL 24 h.
L2 — MongoDB: collection ``dashboard_daily_snapshot``, one doc per
     (user_id, date, dtype).  Survives Redis eviction/restart; queried only
     on L1 miss.  The snapshot is re-warmed into Redis when served from L2.

Invalidation is *event-driven*, not TTL-only.  Call ``invalidate(user_id)``
from any mutation handler (portfolio upload, risk-profile save, goal CRUD,
NAV refresh) — this deletes all six dashboard type keys from Redis.  L2 docs
are kept for historical reference; only the current-date entry is ever served.

Usage::

    from services.dashboard_cache import dashboard_cache

    # read (L1 → L2 → None)
    cached = await dashboard_cache.get(user_id, "risk")

    # write (L1 + L2)
    await dashboard_cache.set(user_id, "risk", data)

    # invalidate on any mutation
    await dashboard_cache.invalidate(user_id)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from services.redis_client import cache_del, cache_get, cache_set

logger = logging.getLogger(__name__)

DASHBOARD_TYPES = ("concentration", "diversification", "risk", "performance", "goals", "tax")
_CACHE_TTL_S = 86_400  # 24 hours


def _redis_key(user_id: str, dtype: str) -> str:
    return f"dashboard:{user_id}:{dtype}"


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


async def get(user_id: str, dtype: str) -> Optional[dict]:
    """Return cached dashboard data or None.  Tries L1 (Redis) first, then
    L2 (MongoDB today-only).  On L2 hit, re-warms L1."""
    # L1
    hit = await cache_get(_redis_key(user_id, dtype))
    if hit is not None:
        return hit

    # L2 — today's snapshot only (stale dates are not served)
    try:
        from deps import db  # late import to avoid circular at module load
        doc = await db.dashboard_daily_snapshot.find_one(
            {"user_id": user_id, "date": _today_utc(), "dtype": dtype},
            {"_id": 0, "data": 1},
        )
        if doc and doc.get("data"):
            logger.debug("dashboard cache L2 hit user=%s type=%s", user_id, dtype)
            await cache_set(_redis_key(user_id, dtype), doc["data"], ttl_s=_CACHE_TTL_S)
            return doc["data"]
    except Exception as exc:
        logger.warning("dashboard cache L2 read failed: %s", exc)

    return None


async def set(user_id: str, dtype: str, data: dict) -> None:  # noqa: A001
    """Write to L1 (Redis, 24 h TTL) and L2 (MongoDB, upsert today's doc)."""
    await cache_set(_redis_key(user_id, dtype), data, ttl_s=_CACHE_TTL_S)

    today = _today_utc()
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        from deps import db  # late import to avoid circular at module load
        await db.dashboard_daily_snapshot.update_one(
            {"user_id": user_id, "date": today, "dtype": dtype},
            {"$set": {"data": data, "updated_at": now_iso}},
            upsert=True,
        )
    except Exception as exc:
        logger.warning("dashboard cache L2 write failed: %s", exc)


async def invalidate(user_id: str) -> None:
    """Delete all dashboard Redis L1 keys and today's MongoDB L2 docs for this user.

    Both layers are cleared so that a Redis restart after a portfolio mutation
    doesn't cause stale L2 data to be served.
    """
    for dtype in DASHBOARD_TYPES:
        await cache_del(_redis_key(user_id, dtype))
    today = _today_utc()
    try:
        from deps import db  # late import to avoid circular at module load
        await db.dashboard_daily_snapshot.delete_many({"user_id": user_id, "date": today})
    except Exception as exc:
        logger.warning("dashboard cache L2 invalidation failed for user %s: %s", user_id, exc)
    logger.info("dashboard cache invalidated user=%s", user_id)
