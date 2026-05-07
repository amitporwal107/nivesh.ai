"""Bearer-token auth for the NIDP Query API.

Single shared secret read from NIDP_QUERY_API_TOKEN (mounted from
Secret Manager). Fail-closed: if the env var is unset, every request
returns 503 — a misconfigured deploy can never silently leak data."""
from __future__ import annotations

import os
import secrets as _stdlib_secrets

from fastapi import Header, HTTPException


_TOKEN: str = os.environ.get("NIDP_QUERY_API_TOKEN", "").strip()
_BEARER_PREFIX = "Bearer "


async def require_bearer(authorization: str | None = Header(default=None)) -> None:
    if not _TOKEN:
        raise HTTPException(status_code=503,
                            detail="NIDP_QUERY_API_TOKEN not configured on server")
    if not authorization or not authorization.startswith(_BEARER_PREFIX):
        raise HTTPException(status_code=401, detail="missing bearer token")
    presented = authorization[len(_BEARER_PREFIX):].strip()
    if not _stdlib_secrets.compare_digest(presented, _TOKEN):
        raise HTTPException(status_code=401, detail="invalid bearer token")
