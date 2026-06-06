"""Redis client — lazy connection from admin-managed secret REDIS_URL.

Used as the primary cache for Groww-scraped MF holdings. If REDIS_URL is not
configured (or connection fails), callers should fall back to MongoDB cache.

Keys:
    nivesh:mf:holdings:{instrument_key}   -> JSON-serialised fund data
    nivesh:mf:slug:{instrument_key}        -> resolved Groww slug (text)
"""
from __future__ import annotations
import json
import logging
from typing import Any, Dict, Optional

from redis import asyncio as aioredis

from helpers import secrets as _secrets

logger = logging.getLogger(__name__)

_client: Optional[aioredis.Redis] = None
_last_url: Optional[str] = None

DEFAULT_TTL_S = 15 * 24 * 3600  # 15 days


async def get_client() -> Optional[aioredis.Redis]:
    """Return connected Redis client, or None if not configured."""
    global _client, _last_url
    url = _secrets.get("REDIS_URL")
    if not url:
        return None
    if _client is not None and _last_url == url:
        return _client
    if _client is not None:
        try:
            await _client.close()
        except Exception:  # noqa: BLE001
            pass
        _client = None
    try:
        _client = aioredis.from_url(
            url, encoding="utf-8", decode_responses=True,
            socket_connect_timeout=3, socket_timeout=3,
        )
        # Force connection check
        await _client.ping()
        _last_url = url
        logger.info("Redis connected")
        return _client
    except Exception as e:  # noqa: BLE001
        logger.warning("Redis init failed: %s", e)
        _client = None
        _last_url = None
        return None


async def close_client() -> None:
    global _client
    if _client is not None:
        try:
            await _client.close()
        finally:
            _client = None


async def ping() -> Dict[str, Any]:
    c = await get_client()
    if c is None:
        return {"ok": False, "reason": "REDIS_URL not configured"}
    try:
        pong = await c.ping()
        info = await c.info("server")
        return {
            "ok": bool(pong),
            "version": info.get("redis_version"),
        }
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": str(e)}


def _key(prefix: str, instrument_key: str) -> str:
    return f"nivesh:mf:{prefix}:{instrument_key}"


async def get_holdings(instrument_key: str) -> Optional[Dict[str, Any]]:
    c = await get_client()
    if c is None:
        return None
    try:
        raw = await c.get(_key("holdings", instrument_key))
        return json.loads(raw) if raw else None
    except Exception as e:  # noqa: BLE001
        logger.warning("redis get_holdings failed: %s", e)
        return None


async def set_holdings(
    instrument_key: str, data: Dict[str, Any], ttl_s: int = DEFAULT_TTL_S
) -> bool:
    c = await get_client()
    if c is None:
        return False
    try:
        await c.set(_key("holdings", instrument_key), json.dumps(data), ex=ttl_s)
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("redis set_holdings failed: %s", e)
        return False


async def get_slug(instrument_key: str) -> Optional[str]:
    c = await get_client()
    if c is None:
        return None
    try:
        return await c.get(_key("slug", instrument_key))
    except Exception as e:  # noqa: BLE001
        logger.warning("redis get_slug failed: %s", e)
        return None


async def set_slug(instrument_key: str, slug: str) -> bool:
    c = await get_client()
    if c is None:
        return False
    try:
        await c.set(_key("slug", instrument_key), slug)
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("redis set_slug failed: %s", e)
        return False


# ── Generic JSON cache (namespaced under nivesh:cache:) ──────────────────
async def cache_get(key: str) -> Optional[Any]:
    c = await get_client()
    if c is None:
        return None
    try:
        raw = await c.get(f"nivesh:cache:{key}")
        return json.loads(raw) if raw else None
    except Exception as e:  # noqa: BLE001
        logger.warning("redis cache_get failed: %s", e)
        return None


async def cache_set(key: str, value: Any, ttl_s: int = 300) -> bool:
    c = await get_client()
    if c is None:
        return False
    try:
        await c.set(f"nivesh:cache:{key}", json.dumps(value, default=str), ex=ttl_s)
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("redis cache_set failed: %s", e)
        return False


async def cache_del(key: str) -> bool:
    c = await get_client()
    if c is None:
        return False
    try:
        await c.delete(f"nivesh:cache:{key}")
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("redis cache_del failed: %s", e)
        return False


async def cache_del_pattern(pattern: str) -> int:
    """Delete all keys matching a glob pattern (relative to nivesh:cache:). Returns count deleted."""
    c = await get_client()
    if c is None:
        return 0
    try:
        keys = await c.keys(f"nivesh:cache:{pattern}")
        if keys:
            await c.delete(*keys)
        return len(keys)
    except Exception as e:  # noqa: BLE001
        logger.warning("redis cache_del_pattern failed: %s", e)
        return 0
