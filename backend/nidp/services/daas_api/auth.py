"""DaaS auth dependency.

Resolves the API key from one of:

  * ``X-API-Key: <token>``  — preferred, public-API convention
  * ``Authorization: Bearer <token>`` — accepted for SDK-style clients

then verifies + applies rate-limit / quota. On success, attaches the
key record to ``request.state.daas_key`` so handlers can read identity
without re-querying the DB.

The lookup is hashed (SHA-256) and constant-time-compared via the
unique key_hash index — so an attacker timing-probing this endpoint
gets no signal about which prefix is real.

Lookups are cached for ~30s in-process. That window keeps a noisy
caller from hammering the DB on every request and is short enough
that a freshly-revoked key is rejected within half a minute.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Optional, Tuple

from fastapi import Header, HTTPException, Request

from nidp.services.daas_api import keys as keymod
from nidp.services.daas_api import ratelimit


logger = logging.getLogger(__name__)


_LOOKUP_CACHE: dict[str, Tuple[float, Optional[keymod.KeyRecord]]] = {}
_CACHE_TTL_SECS = 30.0
_INTERNAL_TOKEN = os.environ.get("NIDP_DAAS_INTERNAL_TOKEN", "").strip()


def _extract_token(api_key_header: Optional[str], authorization: Optional[str]) -> Optional[str]:
    if api_key_header:
        return api_key_header.strip()
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


async def _resolve(token: str) -> Optional[keymod.KeyRecord]:
    h = keymod.hash_token(token)
    now = time.monotonic()
    cached = _LOOKUP_CACHE.get(h)
    if cached and (now - cached[0]) < _CACHE_TTL_SECS:
        return cached[1]
    rec = await keymod.lookup_by_hash(h)
    _LOOKUP_CACHE[h] = (now, rec)
    return rec


async def require_api_key(
    request: Request,
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    authorization: Optional[str] = Header(default=None),
) -> keymod.KeyRecord:
    token = _extract_token(x_api_key, authorization)
    if not token:
        raise HTTPException(
            status_code=401,
            detail="missing api key — pass it as 'X-API-Key: <token>' or 'Authorization: Bearer <token>'",
        )

    # Optional escape hatch for internal callers (Cloud Run service-to-
    # service). Skipped if the env isn't set.
    if _INTERNAL_TOKEN and token == _INTERNAL_TOKEN:
        rec = keymod.KeyRecord(
            key_id="00000000-0000-0000-0000-000000000000",
            key_prefix="nvd_internal",
            name="internal",
            owner_email="internal@nidp",
            plan="internal",
            rate_limit_rpm=6000,
            daily_quota=None,
            status="active",
            expires_at=None,
        )
    else:
        rec = await _resolve(token)
        if rec is None:
            raise HTTPException(status_code=401, detail="invalid api key")
        if rec.status != "active":
            raise HTTPException(status_code=403, detail=f"api key is {rec.status}")
        if rec.expires_at is not None and rec.expires_at < keymod.now_utc():
            raise HTTPException(status_code=403, detail="api key has expired")

    decision = await ratelimit.consume(
        rec.key_id,
        limit_rpm=rec.rate_limit_rpm,
        daily_quota=rec.daily_quota,
    )
    request.state.daas_key = rec
    request.state.daas_decision = decision
    if not decision.allowed:
        retry_after = decision.reset_seconds if decision.reason == "rate_limit" else 86400
        detail = (
            "rate limit exceeded"
            if decision.reason == "rate_limit"
            else "daily quota exhausted"
        )
        raise HTTPException(
            status_code=429,
            detail=detail,
            headers={
                "Retry-After":         str(retry_after),
                "X-RateLimit-Limit":   str(rec.rate_limit_rpm),
                "X-RateLimit-Remaining": str(decision.remaining_rpm),
                "X-RateLimit-Reset":   str(decision.reset_seconds),
                "X-Daily-Limit":       str(rec.daily_quota) if rec.daily_quota else "unlimited",
                "X-Daily-Remaining":   str(decision.daily_remaining) if decision.daily_remaining is not None else "unlimited",
            },
        )
    return rec
