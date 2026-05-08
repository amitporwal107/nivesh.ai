"""Provisions OpenAlgo accounts on behalf of Nivesh users.

When a signed-in Nivesh user clicks "Connect Broker" and the hosted
OpenAlgo instance is configured, this service:

  1. Calls OpenAlgo's `POST /management/v1/users` with the user's email.
  2. OpenAlgo creates an OpenAlgo account (or rotates the API key for an
     existing one) and returns the plaintext API key.
  3. Nivesh stores the returned key encrypted in `broker_accounts` so the
     user never sees an OpenAlgo login or pastes a key by hand.

Auth: shared `OPENALGO_MANAGEMENT_TOKEN` secret matched on both sides.
This module is deliberately small; the broker_connect route is the only
caller.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)

_TIMEOUT = 10  # seconds


def _conf(key: str) -> str:
    """Read a Nivesh secret with env fallback. Empty string when unset."""
    try:
        from helpers import secrets as _s
        v = (_s.get(key) or "").strip()
        if v:
            return v
    except Exception:  # noqa: BLE001
        pass
    import os as _os
    return (_os.environ.get(key) or "").strip()


class OpenAlgoProvisioningError(Exception):
    """Raised for any failure of the management call."""


def is_configured() -> bool:
    return bool(_conf("OPENALGO_BASE_URL")) and bool(_conf("OPENALGO_MANAGEMENT_TOKEN"))


def provision_for_email(email: str, base_url: Optional[str] = None) -> Dict[str, Any]:
    """Create or rotate the OpenAlgo account for a Nivesh user.

    Returns `{"username": str, "api_key": str, "created": bool}`. Raises
    `OpenAlgoProvisioningError` when the management API isn't configured
    or the call fails. Idempotent at OpenAlgo's side: same email always
    yields the same username; the api_key is rotated each call.

    `base_url` overrides `OPENALGO_BASE_URL` so the caller can target a
    freshly-launched per-account instance instead of the shared one. The
    management token is the same on every instance (set in their .env).
    """
    base = (base_url or _conf("OPENALGO_BASE_URL")).rstrip("/")
    token = _conf("OPENALGO_MANAGEMENT_TOKEN")
    if not base or not token:
        raise OpenAlgoProvisioningError(
            "OpenAlgo management is not configured (OPENALGO_BASE_URL / OPENALGO_MANAGEMENT_TOKEN missing).",
        )
    if not email or "@" not in email:
        raise OpenAlgoProvisioningError("email must be a valid address")

    url = f"{base}/management/v1/users"
    try:
        resp = requests.post(
            url,
            json={"email": email.strip().lower()},
            headers={
                "X-Management-Token": token,
                "Content-Type": "application/json",
                "User-Agent": "Nivesh-SPC/1.0",
            },
            timeout=_TIMEOUT,
        )
    except requests.RequestException as e:
        raise OpenAlgoProvisioningError(f"network error calling OpenAlgo: {e}") from e

    if resp.status_code == 401:
        raise OpenAlgoProvisioningError(
            "OpenAlgo rejected the management token — check OPENALGO_MANAGEMENT_TOKEN matches on both sides.",
        )
    if resp.status_code >= 500:
        raise OpenAlgoProvisioningError(f"OpenAlgo server error {resp.status_code}")
    try:
        body = resp.json()
    except ValueError as e:
        raise OpenAlgoProvisioningError(f"non-JSON response: {e}") from e
    if resp.status_code >= 400:
        raise OpenAlgoProvisioningError(
            body.get("error") if isinstance(body, dict) else f"status {resp.status_code}",
        )

    if not isinstance(body, dict) or "api_key" not in body or "username" not in body:
        raise OpenAlgoProvisioningError(f"unexpected response shape: {body}")
    logger.info(
        "openalgo_provisioner: %s username=%s",
        "created" if body.get("created") else "rotated",
        body.get("username"),
    )
    return body


def mint_sso_token(username: str, base_url: Optional[str] = None) -> str:
    """Ask OpenAlgo to mint a single-use, time-bounded SSO token for a
    username. Returns the opaque token string. Raises on misconfig or
    network error. Used by `connect-hosted` so the user lands on
    OpenAlgo's broker-OAuth flow already signed in.

    Pass `base_url` to target a per-account instance.
    """
    base = (base_url or _conf("OPENALGO_BASE_URL")).rstrip("/")
    token = _conf("OPENALGO_MANAGEMENT_TOKEN")
    if not base or not token:
        raise OpenAlgoProvisioningError("OpenAlgo management is not configured.")
    if not username:
        raise OpenAlgoProvisioningError("username required")

    try:
        resp = requests.post(
            f"{base}/management/v1/sso-tokens",
            json={"username": username},
            headers={
                "X-Management-Token": token,
                "Content-Type": "application/json",
                "User-Agent": "Nivesh-SPC/1.0",
            },
            timeout=_TIMEOUT,
        )
    except requests.RequestException as e:
        raise OpenAlgoProvisioningError(f"network error minting SSO: {e}") from e

    if resp.status_code == 401:
        raise OpenAlgoProvisioningError("management token rejected")
    if resp.status_code >= 400:
        try:
            err = resp.json().get("error", "")
        except Exception:  # noqa: BLE001
            err = ""
        raise OpenAlgoProvisioningError(f"sso-token mint failed: {err or resp.status_code}")

    body = resp.json()
    if not isinstance(body, dict) or "token" not in body:
        raise OpenAlgoProvisioningError(f"unexpected sso-token response: {body}")
    return body["token"]
