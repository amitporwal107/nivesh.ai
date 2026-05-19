"""Thin bridge from LangGraph agent nodes to the app-level DAAS client.

The app-level `services.copilot_tools.daas_client` already handles auth,
retries and error formatting. This module adds a generic `call_daas()`
helper that returns a normalised dict so nodes don't need to import
the app daas_client directly (avoiding circular imports when nidp services
are used standalone).
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)
_TIMEOUT = 8.0


def _headers() -> dict:
    key = os.environ.get("NIDP_DAAS_API_KEY", "")
    return {"X-API-Key": key, "Accept": "application/json"} if key else {"Accept": "application/json"}


def _base() -> str:
    return os.environ.get("NIDP_DAAS_BASE_URL", "https://data.niveshcopilot.com/daas").rstrip("/")


async def call_daas(
    method: str,
    path: str,
    params: Optional[Dict[str, Any]] = None,
    json: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Call the NIDP DAAS API and return a normalised dict.

    Returns:
        {"ok": bool, "summary": str, "data": dict, "rows": list}

    Never raises — errors are surfaced via ok=False + summary.
    """
    url = f"{_base()}{path}"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.request(
                method.upper(),
                url,
                params=params,
                json=json,
                headers=_headers(),
            )
        if resp.status_code == 404:
            return {"ok": False, "summary": f"DAAS: {path} not found", "data": {}, "rows": []}
        if resp.status_code != 200:
            return {
                "ok": False,
                "summary": f"DAAS {path} HTTP {resp.status_code}",
                "data": {},
                "rows": [],
            }
        body = resp.json()
        # normalise: body may be a list or dict
        if isinstance(body, list):
            return {"ok": True, "summary": f"{len(body)} records from {path}", "data": {}, "rows": body}
        return {
            "ok": True,
            "summary": body.get("summary", f"data from {path}"),
            "data": {k: v for k, v in body.items() if k not in ("rows", "items", "data")},
            "rows": body.get("rows") or body.get("items") or body.get("data") or [],
        }
    except httpx.TimeoutException:
        logger.warning("DAAS timeout: %s", path)
        return {"ok": False, "summary": f"DAAS timeout: {path}", "data": {}, "rows": []}
    except Exception as exc:
        logger.warning("DAAS error %s: %s", path, exc)
        return {"ok": False, "summary": f"DAAS error: {exc}", "data": {}, "rows": []}
