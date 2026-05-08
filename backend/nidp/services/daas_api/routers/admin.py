"""Admin endpoints — key lifecycle management.

Protected by NIDP_DAAS_INTERNAL_TOKEN (Bearer auth). Never exposed to
external callers; intended for ops tooling / the Nivesh admin console.

    POST   /admin/keys          — issue a new key (returns token once)
    GET    /admin/keys          — list all keys (no cleartext tokens)
    DELETE /admin/keys/{key_id} — revoke a key
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr, Field

from nidp.services.daas_api import keys as daas_keys

router = APIRouter(prefix="/admin", tags=["admin"])

_bearer = HTTPBearer(auto_error=False)


def _require_internal(
    request: Request,
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> None:
    internal_token = os.environ.get("NIDP_DAAS_INTERNAL_TOKEN", "")
    if not internal_token:
        raise HTTPException(503, "Admin endpoint not configured (no internal token).")
    provided = None
    if creds and creds.scheme.lower() == "bearer":
        provided = creds.credentials
    if not provided or provided != internal_token:
        raise HTTPException(401, "Invalid or missing admin token.")


class KeyRequest(BaseModel):
    name:            str = Field(..., description="Human label, e.g. 'AcmeCorp prod'")
    owner_email:     str = Field(..., description="Owner contact email")
    plan:            str = Field("free", description="free | standard | pro | internal")
    rate_limit_rpm:  Optional[int] = Field(None, description="Override rpm (default: plan)")
    daily_quota:     Optional[int] = Field(None, description="Override quota (0 = unlimited)")
    expires_in_days: Optional[int] = Field(None, description="Auto-expire after N days; omit = never")
    notes:           Optional[str] = None


@router.post("/keys", dependencies=[Depends(_require_internal)], status_code=201)
async def create_key(body: KeyRequest):
    """Issue a new DaaS API key. The cleartext token is returned once
    in this response and never stored — save it immediately."""
    expires_at: Optional[datetime] = None
    if body.expires_in_days:
        expires_at = datetime.now(tz=timezone.utc) + timedelta(days=body.expires_in_days)
    try:
        result = await daas_keys.issue_key(
            name=body.name,
            owner_email=body.owner_email,
            plan=body.plan,
            rate_limit_rpm=body.rate_limit_rpm,
            daily_quota=body.daily_quota if body.daily_quota != 0 else None,
            expires_at=expires_at,
            notes=body.notes,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return result


@router.get("/keys", dependencies=[Depends(_require_internal)])
async def list_keys():
    """List all API keys (active and revoked). Does not return cleartext tokens."""
    return {"keys": await daas_keys.list_keys()}


@router.delete("/keys/{key_id}", dependencies=[Depends(_require_internal)])
async def revoke_key(key_id: str):
    """Revoke a key by key_id. Idempotent."""
    ok = await daas_keys.revoke_key(key_id=key_id)
    if not ok:
        raise HTTPException(404, f"Key {key_id!r} not found or already revoked.")
    return {"revoked": True, "key_id": key_id}
