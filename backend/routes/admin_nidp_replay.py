"""Admin → NIDP → Replay endpoints (pod-side proxy).

Forwards `/api/admin/nidp/replay/*` to the DaaS API on the NIDP VM at
`${NIDP_DAAS_BASE_URL}/v1/replay/*`. The replay engine itself runs on
the VM (where it has direct PG access); the pod just gates the
admin session and injects the X-API-Key.

Same pattern as `admin_nidp.py:dq_proxy` — generic verb-agnostic proxy.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from deps import require_admin
from nidp.quality.replay.policy import list_policies

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin/nidp/replay", tags=["admin-nidp-replay"])


def _vm_creds() -> tuple[str, str]:
    base = os.environ.get("NIDP_DAAS_BASE_URL")
    key  = os.environ.get("NIDP_DAAS_API_KEY")
    if not base or not key:
        raise HTTPException(
            status_code=503,
            detail=(
                "NIDP_DAAS_BASE_URL / NIDP_DAAS_API_KEY not configured. "
                "Set both in the pod backend .env to enable replay endpoints."
            ),
        )
    return base.rstrip("/"), key


# ─────────────────────────────────────────────────────────────────
# Special-case: /policies — graceful fallback to built-ins so the UI's
# Start-Run dropdown is never empty even if the VM is unreachable.
# ─────────────────────────────────────────────────────────────────
@router.get("/policies")
async def get_policies(request: Request) -> Dict[str, Any]:
    await require_admin(request)
    try:
        base, key = _vm_creds()
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(
                f"{base}/v1/replay/policies",
                headers={"X-API-Key": key, "Accept": "application/json"},
            )
        if r.status_code == 200:
            data = r.json()
            data.setdefault("source", "db")
            return data
        # VM responded with non-200 → fall through to builtin
        logger.warning("replay /policies: VM returned HTTP %s — using builtin", r.status_code)
    except (HTTPException, httpx.HTTPError) as e:
        logger.warning("replay /policies: VM unreachable (%s) — using builtin", e)

    policies = await list_policies(None)
    return {
        "policies": [p.as_dict() for p in policies],
        "source":   "builtin",
        "warning":  "NIDP DaaS unreachable; showing built-in defaults",
    }


# ─────────────────────────────────────────────────────────────────
# Generic proxy for everything else
# ─────────────────────────────────────────────────────────────────
@router.api_route(
    "/{tail:path}",
    methods=["GET", "POST", "PATCH", "DELETE"],
    summary="Authenticated proxy to NIDP DaaS /v1/replay/*",
)
async def replay_proxy(tail: str, request: Request) -> StreamingResponse:
    await require_admin(request)
    base, key = _vm_creds()

    upstream = f"{base}/v1/replay/{tail}"
    if request.url.query:
        upstream += f"?{request.url.query}"

    body = await request.body() if request.method in ("POST", "PUT", "PATCH") else None
    headers = {"X-API-Key": key, "Accept": "application/json"}
    if body:
        headers["Content-Type"] = "application/json"

    try:
        # Replay /start kicks off a background task on the VM but
        # returns within a few seconds with the replay_id; allow 30s.
        # Status / list calls are fast.
        timeout = 30.0
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.request(request.method, upstream, headers=headers, content=body)
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"replay proxy: {e}") from e

    return StreamingResponse(
        iter([r.content]),
        status_code=r.status_code,
        media_type=r.headers.get("content-type", "application/json"),
    )
