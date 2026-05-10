"""HTTP client for the NIDP Query API (Cloud Run service in GCP).

The wealth-advisor API service can't reach the private NIDP Postgres
on the GCP VM directly — it lives on a private IP behind a VPC
connector that only Cloud Run jobs/services have access to. So all
admin/nidp data reads are proxied through the NIDP Query API
(backend/nidp/services/query_api), which runs inside that VPC.

Configuration (read from secrets registry, env-var fallback):
  NIDP_QUERY_API_URL    — base URL printed by build_on_gcp.sh
  NIDP_QUERY_API_TOKEN  — bearer token created in Secret Manager

Failures raise NidpQueryClientError with a short human message so the
admin route can surface it cleanly to the dashboard.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional, Tuple

import httpx

from helpers import secrets as _secrets


logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


class NidpQueryClientError(Exception):
    """Raised when the NIDP Query API call fails. .detail carries a
    human-readable message; .status carries the HTTP code (or None
    for connection-level failures)."""

    def __init__(self, detail: str, status: Optional[int] = None):
        super().__init__(detail)
        self.detail = detail
        self.status = status


def _config() -> Tuple[Optional[str], Optional[str]]:
    url   = _secrets.get("NIDP_QUERY_API_URL")   or os.environ.get("NIDP_QUERY_API_URL")
    token = _secrets.get("NIDP_QUERY_API_TOKEN") or os.environ.get("NIDP_QUERY_API_TOKEN")
    return (url.rstrip("/") if url else None), token


def is_configured() -> bool:
    url, token = _config()
    return bool(url and token)


def config_summary() -> Dict[str, Any]:
    """Non-secret view of the current config — for /diag."""
    url, token = _config()
    return {
        "url_set":   bool(url),
        "token_set": bool(token),
        "url":       url,
    }


async def _request(method: str, path: str, *, auth: bool = True, **kwargs) -> Dict[str, Any]:
    url, token = _config()
    if not url:
        raise NidpQueryClientError("NIDP_QUERY_API_URL not configured")
    if auth and not token:
        raise NidpQueryClientError("NIDP_QUERY_API_TOKEN not configured")

    headers = kwargs.pop("headers", {})
    if auth:
        headers["Authorization"] = f"Bearer {token}"

    full_url = f"{url}{path}"
    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            r = await client.request(method, full_url, headers=headers, **kwargs)
    except httpx.TimeoutException as e:
        raise NidpQueryClientError(f"timeout contacting NIDP Query API ({full_url})") from e
    except httpx.RequestError as e:
        raise NidpQueryClientError(f"network error contacting NIDP Query API: {e}") from e

    if r.status_code >= 400:
        raise NidpQueryClientError(
            f"NIDP Query API returned {r.status_code}: {r.text[:300]}",
            status=r.status_code,
        )
    try:
        return r.json()
    except Exception as e:                                              # noqa: BLE001
        raise NidpQueryClientError(
            f"non-JSON response from {full_url}: {r.text[:200]}"
        ) from e


async def get_health() -> Dict[str, Any]:
    return await _request("GET", "/health", auth=False)


async def get_catalog() -> Dict[str, Any]:
    return await _request("GET", "/catalog")


async def get_feeds() -> Dict[str, Any]:
    return await _request("GET", "/feeds")


async def get_feed_runs(ingester: str, limit: int = 20) -> Dict[str, Any]:
    return await _request("GET", f"/feeds/{ingester}/runs",
                          params={"limit": limit})


async def get_feed_calendar(ingester: str, days: int = 7) -> Dict[str, Any]:
    return await _request("GET", f"/feeds/{ingester}/calendar",
                          params={"days": days})


async def get_validation(limit: int = 50) -> Dict[str, Any]:
    return await _request("GET", "/validation", params={"limit": limit})


# ── Quality / Certification ────────────────────────────────────────────────

async def get_quality(domain: Optional[str] = None, limit: int = 90) -> Dict[str, Any]:
    params: Dict[str, Any] = {"limit": limit}
    if domain:
        params["domain"] = domain
    return await _request("GET", "/quality", params=params)


async def get_certification(domain: Optional[str] = None, limit: int = 90) -> Dict[str, Any]:
    params: Dict[str, Any] = {"limit": limit}
    if domain:
        params["domain"] = domain
    return await _request("GET", "/certification", params=params)


async def get_consistency(domain: Optional[str] = None, limit: int = 90) -> Dict[str, Any]:
    params: Dict[str, Any] = {"limit": limit}
    if domain:
        params["domain"] = domain
    return await _request("GET", "/consistency", params=params)


async def get_consistency_findings(
    domain: Optional[str] = None,
    dimension: Optional[str] = None,
    severity: Optional[str] = None,
    limit: int = 200,
) -> Dict[str, Any]:
    params: Dict[str, Any] = {"limit": limit}
    if domain:
        params["domain"] = domain
    if dimension:
        params["dimension"] = dimension
    if severity:
        params["severity"] = severity
    return await _request("GET", "/consistency/findings", params=params)


async def get_publish_gate(domain: Optional[str] = None, limit: int = 90) -> Dict[str, Any]:
    params: Dict[str, Any] = {"limit": limit}
    if domain:
        params["domain"] = domain
    return await _request("GET", "/publish-gate", params=params)


async def get_exception_queue(resolved: bool = False, limit: int = 100) -> Dict[str, Any]:
    return await _request("GET", "/exception-queue",
                          params={"resolved": str(resolved).lower(), "limit": limit})


async def resolve_exception(
    queue_id: str,
    action: str,
    resolution_note: str = "",
    resolved_by: str = "ops",
) -> Dict[str, Any]:
    return await _request(
        "PATCH", f"/exception-queue/{queue_id}",
        json={"action": action, "resolution_note": resolution_note, "resolved_by": resolved_by},
    )


async def get_quarantine(domain: Optional[str] = None, limit: int = 50) -> Dict[str, Any]:
    params: Dict[str, Any] = {"limit": limit}
    if domain:
        params["domain"] = domain
    return await _request("GET", "/quarantine", params=params)


# ── VM ops (logs + execute, replaces gcloud Cloud Run path) ──────────

async def get_feed_logs(ingester: str, lines: int = 200) -> Dict[str, Any]:
    return await _request(
        "GET", f"/feeds/{ingester}/logs",
        params={"lines": lines},
    )


async def execute_feed(ingester: str) -> Dict[str, Any]:
    return await _request("POST", f"/feeds/{ingester}/execute")
