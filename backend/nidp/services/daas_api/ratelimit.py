"""Per-key sliding-window limiter.

Two layers, both enforced inside the auth dependency:

  * Per-minute rate limit — in-process token bucket. Each instance gets
    its own bucket, so the effective limit on a horizontally-scaled
    deploy is `rpm × instances`. Documented as best-effort; if we ever
    need cross-instance accuracy we'll move to Redis.

  * Daily quota — DB-backed UPSERT into nidp.daas_daily_usage. Hard cap
    that survives instance restarts and scales horizontally.

Both layers fail-open on infrastructure errors: a bug in the limiter
must not take the API offline. Quota exhaustion is the only condition
that returns 429 from this module.
"""
from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import date
from typing import Deque, Dict, Optional, Tuple

from nidp.shared.storage.pg import get_pool


@dataclass(frozen=True)
class LimitDecision:
    allowed:        bool
    limit_rpm:      int
    remaining_rpm:  int
    reset_seconds:  int               # seconds until the oldest in-window request ages out
    daily_quota:    Optional[int]
    daily_used:     int
    daily_remaining: Optional[int]
    reason:         Optional[str]     # 'rate_limit' | 'daily_quota' | None


# key_id → deque of monotonic timestamps for the last 60s
_buckets: Dict[str, Deque[float]] = defaultdict(deque)
_buckets_lock = asyncio.Lock()


def _evict_old(bucket: Deque[float], now: float) -> None:
    cutoff = now - 60.0
    while bucket and bucket[0] < cutoff:
        bucket.popleft()


async def _check_minute(key_id: str, limit_rpm: int) -> Tuple[bool, int, int]:
    now = time.monotonic()
    async with _buckets_lock:
        bucket = _buckets[key_id]
        _evict_old(bucket, now)
        if len(bucket) >= limit_rpm:
            oldest = bucket[0] if bucket else now
            reset = max(1, int(60 - (now - oldest)))
            return False, 0, reset
        bucket.append(now)
        remaining = limit_rpm - len(bucket)
        oldest = bucket[0]
        reset = max(1, int(60 - (now - oldest)))
        return True, remaining, reset


async def _check_quota(key_id: str, daily_quota: Optional[int]) -> Tuple[bool, int, Optional[int]]:
    """UPSERT today's row and return (allowed, used_after, remaining).
    `daily_quota=None` means unlimited — we still increment so usage
    analytics work, but never deny."""
    pool = await get_pool()
    today = date.today()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO nidp.daas_daily_usage (key_id, day, request_count, last_request_at)
            VALUES ($1, $2, 1, NOW())
            ON CONFLICT (key_id, day)
              DO UPDATE SET request_count = nidp.daas_daily_usage.request_count + 1,
                            last_request_at = NOW()
            RETURNING request_count
            """,
            key_id, today,
        )
    used = int(row["request_count"])
    if daily_quota is None:
        return True, used, None
    remaining = max(0, daily_quota - used)
    return used <= daily_quota, used, remaining


async def consume(key_id: str, *, limit_rpm: int, daily_quota: Optional[int]) -> LimitDecision:
    """Atomic-ish: check minute window first (in-memory, fast), only
    burn quota if the minute check passes — that way, throttled
    callers don't chew through their daily allowance."""
    ok_min, remaining_rpm, reset = await _check_minute(key_id, limit_rpm)
    if not ok_min:
        return LimitDecision(
            allowed=False, limit_rpm=limit_rpm, remaining_rpm=0,
            reset_seconds=reset, daily_quota=daily_quota,
            daily_used=-1, daily_remaining=None, reason="rate_limit",
        )

    ok_q, used, remaining_q = await _check_quota(key_id, daily_quota)
    return LimitDecision(
        allowed=ok_q, limit_rpm=limit_rpm, remaining_rpm=remaining_rpm,
        reset_seconds=reset, daily_quota=daily_quota,
        daily_used=used, daily_remaining=remaining_q,
        reason=None if ok_q else "daily_quota",
    )


def reset_buckets_for_tests() -> None:
    """Test helper — wipe in-process state between cases."""
    _buckets.clear()
