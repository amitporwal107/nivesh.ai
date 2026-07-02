"""Per-session server log buffer (Redis-backed, TTL'd).

Powers Settings → Logs & Diagnostics: when a signed-in user turns logging on,
the backend registers a random debug-session id (owned by that user) and, for
every request carrying the X-Nivesh-Debug-Session header, buffers that request's
log records into a capped Redis list so the user can review their own session's
server logs. Everything auto-expires so nothing accumulates.

Redis keys (namespaced under nivesh:sesslog:):
    nivesh:sesslog:owner:{sid}  -> user_id that owns this debug session (string)
    nivesh:sesslog:data:{sid}   -> capped list of JSON-encoded log entries

If Redis is not configured, get_client() returns None and every function here
degrades gracefully to a no-op (the feature simply reports "unavailable").
"""
from __future__ import annotations

import json
import logging
from typing import List, Optional

from services.redis_client import get_client
from deps import db

logger = logging.getLogger(__name__)

TTL_SECONDS = 24 * 3600  # debug sessions live 24h of inactivity (survive to be archived next login)
MAX_ENTRIES = 2000       # ring-buffer cap per session (oldest lines trimmed)
HISTORY_COLLECTION = "session_log_history"
HISTORY_MAX = 10         # keep the last N archived sessions per user


def _owner_key(sid: str) -> str:
    return f"nivesh:sesslog:owner:{sid}"


def _data_key(sid: str) -> str:
    return f"nivesh:sesslog:data:{sid}"


async def register_owner(sid: str, user_id: str) -> bool:
    """Record that `user_id` owns debug session `sid`. Returns False if Redis
    is unavailable (feature can't be enabled)."""
    c = await get_client()
    if c is None:
        return False
    try:
        await c.set(_owner_key(sid), user_id, ex=TTL_SECONDS)
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("session_log register_owner failed: %s", e)
        return False


async def get_owner(sid: str) -> Optional[str]:
    """Return the owning user_id for a debug session, or None if unknown/expired."""
    c = await get_client()
    if c is None:
        return None
    try:
        return await c.get(_owner_key(sid))
    except Exception as e:  # noqa: BLE001
        logger.warning("session_log get_owner failed: %s", e)
        return None


async def append(sid: str, entries: List[dict]) -> None:
    """Append captured log entries for a debug session.

    Only writes when the session is registered (owner key exists) so a forged
    header can't fill Redis. Refreshes the TTL on both keys so an active session
    stays alive. Best-effort — never raises to the caller (the request path)."""
    if not entries:
        return
    c = await get_client()
    if c is None:
        return
    try:
        if not await c.exists(_owner_key(sid)):
            return
        key = _data_key(sid)
        pipe = c.pipeline()
        for e in entries:
            pipe.rpush(key, json.dumps(e, default=str))
        pipe.ltrim(key, -MAX_ENTRIES, -1)
        pipe.expire(key, TTL_SECONDS)
        pipe.expire(_owner_key(sid), TTL_SECONDS)
        await pipe.execute()
    except Exception as e:  # noqa: BLE001
        logger.warning("session_log append failed: %s", e)


async def read(sid: str, limit: int = MAX_ENTRIES) -> List[dict]:
    """Return up to the most recent `limit` log entries for a debug session."""
    c = await get_client()
    if c is None:
        return []
    limit = max(1, min(limit, MAX_ENTRIES))
    try:
        raw = await c.lrange(_data_key(sid), -limit, -1)
        out: List[dict] = []
        for line in raw or []:
            try:
                out.append(json.loads(line))
            except Exception:  # noqa: BLE001 — skip a corrupt line, keep the rest
                continue
        return out
    except Exception as e:  # noqa: BLE001
        logger.warning("session_log read failed: %s", e)
        return []


async def clear(sid: str, *, keep_owner: bool = False) -> None:
    """Delete a session's buffered logs (and its owner mapping unless kept)."""
    c = await get_client()
    if c is None:
        return
    try:
        keys: list[str] = [_data_key(sid)]
        if not keep_owner:
            keys.append(_owner_key(sid))
        await c.delete(*keys)
    except Exception as e:  # noqa: BLE001
        logger.warning("session_log clear failed: %s", e)


async def available() -> bool:
    """True if the store is usable (Redis configured & reachable)."""
    return (await get_client()) is not None


# ── History: archive a finished session to Mongo, keep the last N per user ────

async def archive(sid: str, user_id: str) -> bool:
    """Move a session's buffered logs from Redis into the Mongo history
    collection (kept to the last HISTORY_MAX per user), then clear Redis.
    Called when a session rolls over (new login) or logging is turned off.
    Best-effort — returns True if a history doc was written."""
    from datetime import datetime, timezone
    try:
        logs = await read(sid, limit=MAX_ENTRIES)
        wrote = False
        if logs:
            await db[HISTORY_COLLECTION].insert_one({
                "user_id": user_id,
                "sid": sid,
                "archived_at": datetime.now(timezone.utc),
                "count": len(logs),
                "logs": logs,
            })
            wrote = True
            # Trim to the last HISTORY_MAX for this user.
            stale = await db[HISTORY_COLLECTION].find(
                {"user_id": user_id}, {"_id": 1},
            ).sort("archived_at", -1).skip(HISTORY_MAX).to_list(1000)
            if stale:
                await db[HISTORY_COLLECTION].delete_many(
                    {"_id": {"$in": [d["_id"] for d in stale]}}
                )
        await clear(sid)  # remove the live Redis buffer + owner mapping
        return wrote
    except Exception as e:  # noqa: BLE001
        logger.warning("session_log archive failed: %s", e)
        return False


async def list_history(user_id: str) -> List[dict]:
    """Return metadata for the user's last HISTORY_MAX archived sessions
    (newest first): sid, archived_at (ISO), count."""
    try:
        docs = await db[HISTORY_COLLECTION].find(
            {"user_id": user_id}, {"_id": 0, "logs": 0},
        ).sort("archived_at", -1).limit(HISTORY_MAX).to_list(HISTORY_MAX)
        out = []
        for d in docs:
            at = d.get("archived_at")
            out.append({
                "sid": d.get("sid"),
                "archived_at": at.isoformat() if hasattr(at, "isoformat") else at,
                "count": d.get("count", 0),
            })
        return out
    except Exception as e:  # noqa: BLE001
        logger.warning("session_log list_history failed: %s", e)
        return []


async def get_history(user_id: str, sid: str) -> Optional[List[dict]]:
    """Return the archived log lines for one of the user's past sessions,
    or None if not found / not theirs."""
    try:
        doc = await db[HISTORY_COLLECTION].find_one(
            {"user_id": user_id, "sid": sid}, {"_id": 0, "logs": 1},
        )
        return None if doc is None else (doc.get("logs") or [])
    except Exception as e:  # noqa: BLE001
        logger.warning("session_log get_history failed: %s", e)
        return None
