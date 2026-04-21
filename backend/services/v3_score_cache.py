"""V3 Engine Phase 2b — Redis-backed composite score cache.

    Key format     : v3:score:{instrument_id}
    TTL            : 24 hours (configurable via V3_SCORE_TTL_S env)
    Eviction       : TTL + explicit invalidate_*() on primitive update.
    Fallback       : mutual_fund_metadata.quality_score/health_score cols
                     (so a Redis outage never blocks the API).
"""
from __future__ import annotations
import json
import logging
import os
from typing import Any, Dict, Optional, Iterable

from services import redis_client

logger = logging.getLogger(__name__)

_KEY_PREFIX = "v3:score"
_TTL_S = int(os.environ.get("V3_SCORE_TTL_S", 24 * 3600))


def _key(instrument_id: str) -> str:
    return f"{_KEY_PREFIX}:{instrument_id}"


async def get(instrument_id: str) -> Optional[Dict[str, Any]]:
    """Return cached V3 bundle or None."""
    client = await redis_client.get_client()
    if client is None or not instrument_id:
        return None
    try:
        raw = await client.get(_key(instrument_id))
    except Exception as e:  # noqa: BLE001
        logger.debug(f"redis get v3:score miss: {e}")
        return None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


async def set(instrument_id: str, bundle: Dict[str, Any], ttl_s: int = _TTL_S) -> bool:
    """Cache a V3 bundle with TTL."""
    client = await redis_client.get_client()
    if client is None or not instrument_id:
        return False
    try:
        await client.setex(_key(instrument_id), ttl_s, json.dumps(bundle, default=str))
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning(f"redis set v3:score failed: {e}")
        return False


async def invalidate(instrument_id: str) -> None:
    """Drop the cached bundle for one fund — call this whenever any
    underlying primitive (NAV, AUM, expense, manager) changes."""
    client = await redis_client.get_client()
    if client is None or not instrument_id:
        return
    try:
        await client.delete(_key(instrument_id))
    except Exception:  # noqa: BLE001
        pass


async def invalidate_many(instrument_ids: Iterable[str]) -> int:
    """Bulk invalidation. Returns count of keys deleted (best-effort)."""
    client = await redis_client.get_client()
    if client is None:
        return 0
    keys = [_key(i) for i in instrument_ids if i]
    if not keys:
        return 0
    try:
        return int(await client.delete(*keys))
    except Exception:  # noqa: BLE001
        return 0


async def invalidate_all() -> int:
    """Nuke the whole V3 cache (admin button). Uses SCAN so it's non-blocking."""
    client = await redis_client.get_client()
    if client is None:
        return 0
    deleted = 0
    try:
        async for key in client.scan_iter(match=f"{_KEY_PREFIX}:*", count=500):
            await client.delete(key)
            deleted += 1
    except Exception as e:  # noqa: BLE001
        logger.warning(f"redis invalidate_all failed: {e}")
    return deleted


async def get_stats() -> Dict[str, Any]:
    """For the admin Data Pipeline panel."""
    client = await redis_client.get_client()
    if client is None:
        return {"available": False, "keys": 0, "ttl_s": _TTL_S}
    keys = 0
    try:
        async for _ in client.scan_iter(match=f"{_KEY_PREFIX}:*", count=500):
            keys += 1
    except Exception:  # noqa: BLE001
        pass
    return {"available": True, "keys": keys, "ttl_s": _TTL_S}
