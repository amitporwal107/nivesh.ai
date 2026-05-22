"""Minimal HTTP client for the CASParser ``/v1/token`` endpoint.

The existing nivesh.ai backend has a richer client (rotating key pool,
admin-toggleable sandbox mode) at ``backend/services/cas_api_client.py``.
This file is a deliberately small, self-contained wrapper so the
portfolio_ingestion package doesn't drag the entire host backend into its
container image. Multi-key rotation lands here in a later iteration once
the integration with GSM is wired (Iter 4 ops).

Behaviour:
  * Posts ``{key: <api_key>}`` to ``{base}/v1/token``.
  * Returns ``(access_token, expires_at_isoformat)``.
  * If ``PI_CASPARSER_API_KEY`` is unset, mints a deterministic ``stub-at-…``
    token so staging dry-runs work without real CASParser credentials.
  * On upstream non-2xx, raises :class:`CasparserUpstreamError`.
"""
from __future__ import annotations

import datetime as dt
import logging
import os
import uuid
from dataclasses import dataclass

import httpx

log = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.casparser.in"
DEFAULT_TTL_SECONDS = 30 * 60                 # PRD §4.2 — TTL ≤ 30 min


class CasparserUpstreamError(RuntimeError):
    """The CASParser API returned a non-2xx or unparseable response."""


@dataclass(frozen=True)
class AccessToken:
    access_token: str
    expires_at: dt.datetime
    stub: bool = False


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


async def mint(
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    http_client: httpx.AsyncClient | None = None,
) -> AccessToken:
    """Mint a short-lived access token.

    Args precedence (each optional, falls back to env vars):
      base_url       PI_CASPARSER_BASE_URL  → DEFAULT_BASE_URL
      api_key        PI_CASPARSER_API_KEY   → stub mode
      ttl_seconds    PI_CASPARSER_TTL_SEC   → DEFAULT_TTL_SECONDS
    """
    base_url = base_url or os.environ.get("PI_CASPARSER_BASE_URL", DEFAULT_BASE_URL)
    api_key = api_key or os.environ.get("PI_CASPARSER_API_KEY")
    try:
        ttl_seconds = int(os.environ.get("PI_CASPARSER_TTL_SEC", ttl_seconds))
    except ValueError:
        pass
    ttl_seconds = min(ttl_seconds, DEFAULT_TTL_SECONDS)   # cap at 30 min

    # ── Stub mode: no real key → deterministic fake token ─────────────────
    if not api_key:
        token = "stub-at-" + uuid.uuid4().hex[:24]
        log.info(
            "casparser token mint (stub)",
            extra={"eventType": "CASPARSER_TOKEN_STUB"},
        )
        return AccessToken(
            access_token=token,
            expires_at=_now() + dt.timedelta(seconds=ttl_seconds),
            stub=True,
        )

    # ── Real call ─────────────────────────────────────────────────────────
    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(timeout=10.0)
    try:
        resp = await client.post(
            f"{base_url.rstrip('/')}/v1/token",
            json={"ttl_seconds": ttl_seconds},
            headers={"x-api-key": api_key, "accept": "application/json"},
        )
    except httpx.HTTPError as e:
        log.warning(
            "casparser token mint failed (transport)",
            extra={"eventType": "CASPARSER_TOKEN_FAIL", "reason": str(e)},
        )
        raise CasparserUpstreamError(f"transport error: {e}") from e
    finally:
        if owns_client:
            await client.aclose()

    if resp.status_code >= 400:
        log.warning(
            "casparser token mint non-2xx",
            extra={
                "eventType": "CASPARSER_TOKEN_FAIL",
                "status_code": resp.status_code,
            },
        )
        raise CasparserUpstreamError(
            f"upstream returned {resp.status_code}"
        )

    body = resp.json()
    token = body.get("access_token") or body.get("token")
    expires_in = body.get("expires_in", ttl_seconds)
    if not token:
        raise CasparserUpstreamError("upstream response missing access_token")

    return AccessToken(
        access_token=token,
        expires_at=_now() + dt.timedelta(seconds=int(expires_in)),
        stub=False,
    )
