"""Broker Connect routes — Nivesh Secure Portfolio Connect.

Read-only broker integration via OpenAlgo. Per-user OpenAlgo API keys are
encrypted with AES-256-GCM (`services.pii_security`) before storage; we
never persist raw broker passwords, TOTP seeds, or trading PINs.

Routes (all under /api/broker, all authenticated):

    GET    /api/broker/supported              — list of brokers we accept
    GET    /api/broker/accounts               — current user's connections
    POST   /api/broker/connect                — store + verify a new conn
    POST   /api/broker/accounts/{id}/sync     — fetch holdings (OpenAlgo, or
                                                the broker session for a
                                                native account)
    GET    /api/broker/accounts/{id}/holdings — live holdings, one native
                                                account (never stored)
    GET    /api/broker/holdings               — live holdings, every account
                                                of the user (an OpenAlgo one
                                                is listed as not readable)
    GET    /api/broker/accounts/{id}/positions — live positions, one native
                                                account (never stored)
    GET    /api/broker/positions              — live positions, every account
                                                of the user (as /holdings)
    GET    /api/broker/accounts/{id}/snapshots — history of an account's
                                                holdings syncs
    GET    /api/broker/snapshots/{id}         — one sync snapshot, with the
                                                holdings as they were stored
    DELETE /api/broker/accounts/{id}          — disconnect (delete + audit)

The sync endpoint imports holdings into the same `db.holdings` collection
as CAS / Excel imports. Source-tracking distinguishes broker rows from
CAS rows: `source = "openalgo"`, `source_id = "{exchange}:{symbol}"`,
`broker_account_id = "<account>"`. Re-syncing the same account replaces
*only that account's* prior rows so concurrent CAS imports stay intact.

Accounts connected on the broker's own page (`native: True`, written by
`routes.broker_native`) are read through `services.brokers.hub_reads`;
their holdings rows carry `source = "broker_native"`. Syncing such an
account and the live holdings and positions routes need the `broker_hub`
feature flag; nothing else here does.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from core.exceptions import (
    BusinessException,
    IntegrationException,
    NiveshException,
    ValidationException,
)
from deps import db, get_current_user
from feature_gate import require_feature
from services import audit as _audit
from services import pii_security as _pii
from services.brokers import hub_reads as _hub
from services.brokers import sessions as _sessions
from services.brokers import sync_snapshots as _snapshots
from services.openalgo_client import (
    SUPPORTED_BROKERS,
    OpenAlgoClient,
    OpenAlgoError,
    mask_api_key,
)
from services.openalgo_provisioner import (
    OpenAlgoProvisioningError,
    is_configured as _provisioner_configured,
    mint_sso_token,
    provision_for_email,
)
from services import openalgo_instance_manager as _instance_mgr

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/broker")


# ── Request / response models ────────────────────────────────────────────
class ConnectRequest(BaseModel):
    broker: str = Field(..., min_length=2, max_length=40)
    # Optional — when omitted, falls back to the admin-configured hosted
    # OpenAlgo base URL (`OPENALGO_BASE_URL` secret). Self-hosted advanced
    # users can still pass their own URL.
    openalgo_url: Optional[str] = Field(default=None, max_length=300)
    api_key: str = Field(..., min_length=8, max_length=300)
    label: Optional[str] = Field(default=None, max_length=80)


# ── Hosted-config helpers ────────────────────────────────────────────────
def _hosted_base_url() -> str:
    """Return the Nivesh-hosted OpenAlgo base URL, or '' if not configured.

    Looks up the `OPENALGO_BASE_URL` secret via `helpers.secrets` and
    falls back to the env var of the same name. Both empty → hosted not
    configured, callers must request user-supplied URL.
    """
    try:
        from helpers import secrets as _s
        return (_s.get("OPENALGO_BASE_URL") or "").strip().rstrip("/")
    except Exception:  # noqa: BLE001
        import os as _os
        return (_os.environ.get("OPENALGO_BASE_URL") or "").strip().rstrip("/")


def _hosted_dashboard_url() -> str:
    """Return the public dashboard URL users open to mint their API key.

    Falls back to the base URL when the dedicated dashboard secret is
    empty — internal/external URLs are often the same single-tenant
    deployments.
    """
    try:
        from helpers import secrets as _s
        dash = (_s.get("OPENALGO_DASHBOARD_URL") or "").strip().rstrip("/")
        return dash or _hosted_base_url()
    except Exception:  # noqa: BLE001
        return _hosted_base_url()


# ── Helpers ──────────────────────────────────────────────────────────────
def _public_account(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Strip encrypted secrets before returning to the client."""
    hosted = bool(doc.get("openalgo_hosted"))
    broker = doc.get("broker")
    broker_display = _broker_display(doc)
    return {
        # Session state (native, needs_reconnect, expiry, …). Spread first
        # so it can never displace one of the keys below.
        **_sessions.public_fields(doc),
        "account_id": doc["account_id"],
        "broker": broker,
        "broker_display": broker_display,
        "label": doc.get("label"),
        # Don't leak the internal URL when it's the Nivesh-managed
        # instance — users only need to know it's hosted by Nivesh.
        "openalgo_url": "" if hosted else doc.get("openalgo_url"),
        "openalgo_hosted": hosted,
        "api_key_masked": doc.get("api_key_masked"),
        "status": doc.get("status"),
        "last_sync_at": doc.get("last_sync_at"),
        "last_sync_count": doc.get("last_sync_count"),
        "last_error": doc.get("last_error"),
        "created_at": doc.get("created_at"),
    }


def _broker_display(doc: Dict[str, Any]) -> Optional[str]:
    broker = doc.get("broker")
    if doc.get("native"):
        # Native rows use adapter slugs — the registry names them, the
        # OpenAlgo map does not cover them all.
        return _hub.display_name(broker or "") or broker
    return SUPPORTED_BROKERS.get(broker or "", broker)


async def _get_owned_account(user_id: str, account_id: str) -> Dict[str, Any]:
    doc = await db.broker_accounts.find_one(
        {"account_id": account_id, "user_id": user_id}, {"_id": 0},
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Broker account not found")
    return doc


async def _client_from(doc: Dict[str, Any]) -> OpenAlgoClient:
    raw_key = _pii.decrypt(doc.get("api_key_encrypted") or "")
    if not raw_key:
        raise HTTPException(status_code=500, detail="Failed to decrypt stored API key")
    if doc.get("openalgo_per_account_instance"):
        # Per-account instance: re-launch lazily if its process died
        # (e.g. backend restart cleaned subprocess; we left it; it crashed).
        existing = await _instance_mgr.get_base_url(db, doc["account_id"])
        if not existing:
            inst = await _instance_mgr.launch(
                db, doc["account_id"], doc["user_id"], doc.get("broker", ""),
            )
            existing = inst["base_url"]
        url = existing
    elif doc.get("openalgo_hosted"):
        # Shared singleton: tolerate URL rotation via admin secret.
        url = _hosted_base_url() or doc.get("openalgo_url")
        if not url:
            raise HTTPException(
                status_code=500,
                detail="Hosted OpenAlgo URL no longer configured — ask admin to set OPENALGO_BASE_URL.",
            )
    else:
        url = doc.get("openalgo_url")
        if not url:
            raise HTTPException(status_code=500, detail="Stored OpenAlgo URL is missing")
    return OpenAlgoClient(base_url=url, api_key=raw_key)


# ── Routes ───────────────────────────────────────────────────────────────
@router.get("/supported")
async def list_supported_brokers(request: Request):
    """Public-ish — still requires auth so we can attribute usage."""
    await get_current_user(request)
    return {
        "brokers": [{"slug": k, "name": v} for k, v in SUPPORTED_BROKERS.items()],
    }


@router.get("/openalgo-config")
async def get_openalgo_config(request: Request):
    """Tell the frontend whether a Nivesh-hosted OpenAlgo is configured.

    Never returns the master/admin API key — only the user-facing
    dashboard URL (so the modal can render an "Open OpenAlgo dashboard"
    link) and a bool flag. The internal base URL is NOT leaked.

    `auto_provision` is `True` when the management token is set, meaning
    Nivesh can mint OpenAlgo accounts server-to-server and the user
    never sees OpenAlgo's signup/login screens.
    """
    await get_current_user(request)
    base = _hosted_base_url()
    return {
        "hosted": bool(base),
        "auto_provision": _provisioner_configured(),
        "dashboard_url": _hosted_dashboard_url() if base else "",
    }


# ── Auto-provisioning request model ──────────────────────────────────────
class HostedConnectRequest(BaseModel):
    broker: str = Field(..., min_length=2, max_length=40)
    label: Optional[str] = Field(default=None, max_length=80)


@router.post("/connect-hosted")
async def connect_broker_hosted(request: Request, body: HostedConnectRequest):
    """Zero-friction broker connect using the Nivesh-hosted OpenAlgo.

    Flow when the user (already signed into Nivesh via Google) clicks a
    broker:

      1. Nivesh calls OpenAlgo's `/management/v1/users` with the user's
         Google email → OpenAlgo creates (or rotates) the user + mints
         an API key. The plaintext key is returned exactly once.
      2. Nivesh stores the key AES-256-GCM encrypted in `broker_accounts`.
      3. Nivesh runs the same handshake that `/connect` runs (calls
         `/api/v1/funds` to validate). If the handshake fails because
         the user hasn't yet completed broker auth on OpenAlgo, the
         `broker_account` row is still persisted with status=`pending`
         so the broker-OAuth-redirect step can resume it.

    The user never sees a URL field or an API-key paste box.
    """
    user = await get_current_user(request)
    user_id = user["user_id"]
    email = (user.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="Nivesh user has no email; cannot auto-provision.")

    broker = body.broker.strip().lower()
    if broker not in SUPPORTED_BROKERS:
        raise HTTPException(status_code=400, detail=f"Unsupported broker '{broker}'")

    base_url = _hosted_base_url()
    if not base_url:
        raise HTTPException(
            status_code=400,
            detail="Hosted OpenAlgo is not configured for this environment.",
        )
    if not _provisioner_configured():
        raise HTTPException(
            status_code=400,
            detail="OPENALGO_MANAGEMENT_TOKEN missing — admin must configure it before auto-provision can run.",
        )

    # Allocate the account_id up-front — the instance manager keys its
    # data dir + Mongo row by it, and we use the same id for the
    # per-instance proxy prefix `/api/openalgo/c/<account_id>`.
    account_id = f"ba_{uuid.uuid4().hex[:12]}"

    # Launch a dedicated OpenAlgo subprocess for this (user, broker)
    # pair. Different brokers per user means different instances —
    # OpenAlgo upstream is single-broker per deployment.
    try:
        instance = await _instance_mgr.launch(db, account_id, user_id, broker)
    except Exception as e:  # noqa: BLE001
        logger.exception("connect-hosted: launch instance failed")
        await _audit.record(
            user_id=user_id, action="broker_connect", outcome="error",
            ip=request.client.host if request.client else "",
            ua=request.headers.get("user-agent", ""),
            details={"broker": broker, "stage": "instance_launch", "reason": str(e)},
        )
        raise HTTPException(status_code=502, detail=f"Could not launch OpenAlgo instance: {e}")

    instance_url = instance["base_url"]

    # Provision the user's OpenAlgo account *inside* this dedicated
    # instance via its localhost management endpoint.
    try:
        provisioned = provision_for_email(email, base_url=instance_url)
    except OpenAlgoProvisioningError as e:
        # Roll back the instance — we can't use it without an account.
        try:
            await _instance_mgr.stop(db, account_id)
        except Exception:  # noqa: BLE001
            logger.exception("connect-hosted: rollback stop failed")
        await _audit.record(
            user_id=user_id, action="broker_connect", outcome="error",
            ip=request.client.host if request.client else "",
            ua=request.headers.get("user-agent", ""),
            details={"broker": broker, "stage": "provision", "reason": str(e)},
        )
        raise HTTPException(status_code=502, detail=f"OpenAlgo provisioning failed: {e}")

    api_key = provisioned["api_key"]

    # Light handshake — pre-OAuth `/api/v1/funds` returns an "auth"
    # error which is *expected* until the user completes broker OAuth.
    # Only fail loudly on transport errors (network/timeout/5xx).
    probe = OpenAlgoClient(base_url=instance_url, api_key=api_key)
    ok, msg = probe.health_check()
    transport_error = (not ok) and any(
        word in msg.lower() for word in ("network", "unreachable", "timed out", "500", "502", "503", "504")
    )
    if transport_error:
        try:
            await _instance_mgr.stop(db, account_id)
        except Exception:  # noqa: BLE001
            pass
        await _audit.record(
            user_id=user_id, action="broker_connect", outcome="error",
            ip=request.client.host if request.client else "",
            ua=request.headers.get("user-agent", ""),
            details={"broker": broker, "stage": "handshake", "reason": msg},
        )
        raise HTTPException(status_code=502, detail=f"OpenAlgo unreachable: {msg}")

    now = _now_iso()
    doc = {
        "account_id": account_id,
        "user_id": user_id,
        "broker": broker,
        "label": (body.label or SUPPORTED_BROKERS[broker]).strip()[:80],
        "openalgo_url": instance_url,
        "openalgo_hosted": True,
        "openalgo_username": provisioned.get("username"),
        "openalgo_auto_provisioned": True,
        "openalgo_per_account_instance": True,
        "api_key_encrypted": _pii.encrypt(api_key),
        "api_key_masked": mask_api_key(api_key),
        "status": "pending" if not ok else "active",
        "created_at": now,
        "updated_at": now,
        "last_sync_at": None,
        "last_sync_count": 0,
        "last_error": None if ok else msg,
    }
    await db.broker_accounts.insert_one(doc)

    await _audit.record(
        user_id=user_id, action="broker_connect", resource=account_id,
        outcome="success",
        ip=request.client.host if request.client else "",
        ua=request.headers.get("user-agent", ""),
        details={
            "broker": broker, "openalgo_username": provisioned.get("username"),
            "auto_provisioned": True,
        },
    )

    # Mint an SSO token so the user lands on OpenAlgo already signed in
    # as their per-Nivesh-user OpenAlgo account. The browser hits
    # /api/openalgo/auth/sso?token=...&next=/broker, OpenAlgo validates
    # the token, sets session["user"], and 302s to the React broker
    # picker. End user never sees the OpenAlgo login form.
    #
    # Why /broker (the picker) and not /<broker>/callback? Because each
    # broker's auth-init URL is different — Zerodha jumps to
    # kite.trade/connect/login, Upstox to upstox.com, Angel uses a
    # form-POST callback, Dhan has a custom /dhan/initiate-oauth, etc.
    # The React picker page already encodes those rules. Landing the
    # user there lets the picker assemble the right per-broker URL
    # using OpenAlgo's `BROKER_API_KEY` / `REDIRECT_URL` env vars.
    try:
        sso_token = mint_sso_token(provisioned["username"], base_url=instance_url)
    except OpenAlgoProvisioningError as e:
        logger.warning("connect-hosted: SSO mint failed: %s", e)
        sso_token = ""

    instance_prefix = f"/api/openalgo/c/{account_id}"
    if sso_token:
        next_path = quote("/broker", safe="/")
        broker_login_url = (
            f"{instance_prefix}/auth/sso?token={quote(sso_token, safe='')}&next={next_path}"
        )
    else:
        broker_login_url = f"{instance_prefix}/broker"

    return {
        "account": _public_account(doc),
        "broker_login_url": broker_login_url,
        "ok": True,
    }


@router.get("/accounts")
async def list_accounts(request: Request):
    user = await get_current_user(request)
    # Mark sessions whose broker expiry has passed before listing, so an
    # expired connection is reported as needing a reconnect.
    await _sessions.expire_due_sessions(db, user_id=user["user_id"])
    cursor = db.broker_accounts.find(
        {"user_id": user["user_id"]}, {"_id": 0},
    ).sort("created_at", -1)
    docs = await cursor.to_list(length=50)
    return {"accounts": [_public_account(d) for d in docs]}


@router.post("/connect")
async def connect_broker(request: Request, body: ConnectRequest):
    user = await get_current_user(request)
    user_id = user["user_id"]

    broker = body.broker.strip().lower()
    if broker not in SUPPORTED_BROKERS:
        raise HTTPException(status_code=400, detail=f"Unsupported broker '{broker}'")

    # Hosted-first: if the user didn't pass a URL, fall back to the
    # Nivesh-managed instance from secrets. Self-hosted users can still
    # override by passing `openalgo_url`.
    user_supplied = (body.openalgo_url or "").strip().rstrip("/")
    url = user_supplied or _hosted_base_url()
    if not url:
        raise HTTPException(
            status_code=400,
            detail="OpenAlgo is not configured for this environment. Ask admin to set OPENALGO_BASE_URL or pass your self-hosted URL.",
        )
    if not (url.startswith("http://") or url.startswith("https://")):
        raise HTTPException(status_code=400, detail="openalgo_url must be a full http(s) URL")
    api_key = body.api_key.strip()

    # Health-check before persisting — gives the user a clear signal that
    # their key + URL pair actually works against their self-hosted instance.
    probe = OpenAlgoClient(base_url=url, api_key=api_key)
    ok, msg = probe.health_check()
    if not ok:
        # Audit failed connect attempt — no secrets in details (the audit
        # sanitiser also redacts any "token"/"secret" keys defensively).
        await _audit.record(
            user_id=user_id, action="broker_connect", outcome="error",
            ip=request.client.host if request.client else "",
            ua=request.headers.get("user-agent", ""),
            details={"broker": broker, "openalgo_url": url, "reason": msg},
        )
        raise HTTPException(status_code=400, detail=f"OpenAlgo handshake failed: {msg}")

    account_id = f"ba_{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()
    is_hosted = not user_supplied  # hosted = user didn't bring their own URL
    doc = {
        "account_id": account_id,
        "user_id": user_id,
        "broker": broker,
        "label": (body.label or SUPPORTED_BROKERS[broker]).strip()[:80],
        # Persist the URL we actually verified; if hosted, that's the
        # admin-configured value at connect-time. If the secret rotates
        # later, sync auto-picks up the new value via the deref helper
        # in `_client_from`, but we keep the historical record here.
        "openalgo_url": url,
        "openalgo_hosted": is_hosted,
        "api_key_encrypted": _pii.encrypt(api_key),
        "api_key_masked": mask_api_key(api_key),
        "status": "active",
        "created_at": now,
        "updated_at": now,
        "last_sync_at": None,
        "last_sync_count": 0,
        "last_error": None,
    }
    await db.broker_accounts.insert_one(doc)

    await _audit.record(
        user_id=user_id, action="broker_connect", resource=account_id,
        outcome="success",
        ip=request.client.host if request.client else "",
        ua=request.headers.get("user-agent", ""),
        details={"broker": broker, "openalgo_url": url},
    )

    return {"account": _public_account(doc), "ok": True}


@router.post("/accounts/{account_id}/sync")
async def sync_broker_account(request: Request, account_id: str):
    user = await get_current_user(request)
    user_id = user["user_id"]
    doc = await _get_owned_account(user_id, account_id)

    if doc.get("native"):
        # Connected on the broker's own page: there is no OpenAlgo instance
        # behind this row, the stored broker session reads the holdings.
        # Only this branch depends on the `broker_hub` flag.
        await _hub_user(request)
        return await _sync_native_account(request, user_id, doc)

    client = await _client_from(doc)
    try:
        rows = client.fetch_normalized_holdings()
    except OpenAlgoError as e:
        msg = str(e)
        await db.broker_accounts.update_one(
            {"account_id": account_id},
            {"$set": {"status": "error", "last_error": msg, "updated_at": _now_iso()}},
        )
        await _audit.record(
            user_id=user_id, action="broker_sync", resource=account_id,
            outcome="error",
            ip=request.client.host if request.client else "",
            ua=request.headers.get("user-agent", ""),
            details={"broker": doc.get("broker"), "reason": msg},
        )
        raise HTTPException(status_code=502, detail=f"OpenAlgo sync failed: {msg}")

    saved = await _persist_broker_holdings(user_id, account_id, doc, rows)

    await db.broker_accounts.update_one(
        {"account_id": account_id},
        {"$set": {
            "status": "active",
            "last_sync_at": _now_iso(),
            "last_sync_count": len(saved),
            "last_error": None,
            "updated_at": _now_iso(),
        }},
    )
    await _audit.record(
        user_id=user_id, action="broker_sync", resource=account_id,
        outcome="success",
        ip=request.client.host if request.client else "",
        ua=request.headers.get("user-agent", ""),
        details={"broker": doc.get("broker"), "count": len(saved)},
    )

    return {"ok": True, "count": len(saved), "holdings": saved}


# ── Native (broker-session) reads ────────────────────────────────────────
# Off stops holdings sync and position reads for redirect-connected accounts
# (feature_flags.KNOWN_FEATURES). Listing, disconnecting and every OpenAlgo
# route do not depend on it.
FLAG = "broker_hub"


async def _hub_user(request: Request) -> dict:
    """The signed-in user, refused with 403 when `broker_hub` is off for them."""
    return await require_feature(
        FLAG, resolve_user=lambda r: get_current_user(r), get_db=lambda: db,
    )(request)


class BrokerSessionExpiredException(BusinessException):
    """The broker session behind the account has ended — reconnect needed."""
    error_code = _hub.CODE_SESSION_EXPIRED
    http_status = 409


# Read failure code → the domain exception the global handler turns into the
# standard error envelope (409 / 400 / 502).
_READ_ERRORS = {
    _hub.CODE_SESSION_EXPIRED: BrokerSessionExpiredException,
    _hub.CODE_NOT_SUPPORTED: ValidationException,
    _hub.CODE_READ_FAILED: IntegrationException,
}


def _account_details(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [{"broker": doc.get("broker"), "account_id": doc["account_id"]}]


def _read_error(exc: Exception, doc: Dict[str, Any], what: str) -> NiveshException:
    """The error for a failed native read: a stable `code`, a fixed-text
    message (`hub_reads.describe_failure`, never the broker's own error) and
    the broker + account in `details`. The broker's exception is not passed
    as `cause` — the handler logs a cause with its text — and callers raise
    this `from None` for the same reason."""
    code, message = _hub.describe_failure(exc, doc.get("broker") or "", what)
    return _READ_ERRORS[code](message, code=code, details=_account_details(doc))


async def _sync_native_account(
    request: Request, user_id: str, doc: Dict[str, Any],
) -> Dict[str, Any]:
    account_id = doc["account_id"]
    try:
        result = await _hub.sync_account(db, doc, trigger="manual")
    except Exception as e:  # noqa: BLE001
        err = _read_error(e, doc, "holdings")
        await _audit.record(
            user_id=user_id, action="broker_sync", resource=account_id,
            outcome="error",
            ip=request.client.host if request.client else "",
            ua=request.headers.get("user-agent", ""),
            details={
                "broker": doc.get("broker"), "native": True,
                "code": err.code, "reason": err.message,
            },
        )
        raise err from None

    await _audit.record(
        user_id=user_id, action="broker_sync", resource=account_id,
        outcome="success",
        ip=request.client.host if request.client else "",
        ua=request.headers.get("user-agent", ""),
        details={"broker": doc.get("broker"), "native": True, "count": result["count"]},
    )
    return {
        "ok": True,
        "count": result["count"],
        "holdings": result["holdings"],
        # The snapshot kept of this sync (null if it could not be written)
        # and what the duplicate check found.
        "snapshot_id": result["snapshot_id"],
        "duplicates": result["duplicates"],
    }


# Why an OpenAlgo account has no live read: its stored key is an OpenAlgo API
# key, not a broker session (`hub_reads._live_token`).
_NOT_NATIVE_HOLDINGS = (
    "Live holdings are available only for accounts connected by signing in on the broker's own page."
)
_NOT_NATIVE_POSITIONS = (
    "Live positions are available only for accounts connected by signing in on the broker's own page."
)


def _not_native(doc: Dict[str, Any], message: str) -> ValidationException:
    return ValidationException(message, code=_hub.CODE_NOT_SUPPORTED, details=_account_details(doc))


async def _user_accounts(user_id: str) -> List[Dict[str, Any]]:
    """Every broker account of the user, newest first (as GET /accounts)."""
    cursor = db.broker_accounts.find({"user_id": user_id}, {"_id": 0}).sort("created_at", -1)
    return await cursor.to_list(length=50)


def _account_entry(doc: Dict[str, Any]) -> Dict[str, Any]:
    """The fields that name an account in an all-accounts live read."""
    return {
        "account_id": doc["account_id"],
        "broker": doc.get("broker"),
        "broker_display": _broker_display(doc),
        "label": doc.get("label"),
    }


_NO_HOLDINGS_TOTALS: Dict[str, Optional[float]] = {
    "invested_rs": None, "value_rs": None, "pnl_rs": None, "pnl_pct": None,
}


@router.get("/accounts/{account_id}/holdings")
async def get_account_holdings(request: Request, account_id: str):
    """Current holdings of one natively connected account, read live from
    the broker on every call and never stored (the rows the last sync stored
    are not touched). Each row carries its value, cost and P&L, null when
    the broker gave no price or average; `totals` are null when any row
    lacks the figure.
    """
    user = await _hub_user(request)
    doc = await _get_owned_account(user["user_id"], account_id)
    if not doc.get("native"):
        raise _not_native(doc, _NOT_NATIVE_HOLDINGS)
    try:
        rows = await _hub.read_account_holdings(db, doc)
    except Exception as e:  # noqa: BLE001
        raise _read_error(e, doc, "holdings") from None
    return {
        **_account_entry(doc),
        "as_of": _now_iso(),
        "holdings": rows,
        "counts": {"total": len(rows)},
        "totals": _hub.holdings_totals(rows),
    }


@router.get("/holdings")
async def get_all_holdings(request: Request):
    """Current holdings across every broker account of the user, read live.
    Each account is read on its own, a few at a time: one failing — or
    needing a reconnect — is reported in its entry (`ok: false`, `error`)
    and never fails the others. An OpenAlgo account is listed with the
    not-supported error and is not read. Nothing is stored.
    """
    user = await _hub_user(request)
    docs = await _user_accounts(user["user_id"])
    gate = asyncio.Semaphore(_hub.LIVE_READ_CONCURRENCY)

    async def _read_one(doc: Dict[str, Any]) -> Dict[str, Any]:
        entry: Dict[str, Any] = {
            **_account_entry(doc),
            "ok": False,
            "error": None,
            "as_of": None,
            "holdings": [],
            # Not read: how many there are is not known.
            "counts": {"total": None},
            "totals": dict(_NO_HOLDINGS_TOTALS),
        }
        if not doc.get("native"):
            entry["error"] = {"code": _hub.CODE_NOT_SUPPORTED, "message": _NOT_NATIVE_HOLDINGS}
        else:
            try:
                async with gate:
                    rows = await _hub.read_account_holdings(db, doc)
            except Exception as e:  # noqa: BLE001
                code, message = _hub.describe_failure(e, doc.get("broker") or "", "holdings")
                entry["error"] = {"code": code, "message": message}
            else:
                entry.update(
                    ok=True, holdings=rows, counts={"total": len(rows)},
                    totals=_hub.holdings_totals(rows),
                )
        entry["as_of"] = _now_iso()
        return entry

    accounts = await asyncio.gather(*(_read_one(d) for d in docs))
    return {"as_of": _now_iso(), "accounts": list(accounts)}


def _position_counts(rows: List[Dict[str, Any]]) -> Dict[str, int]:
    return {
        "total": len(rows),
        "fno": sum(1 for r in rows if r.get("segment") == "fno"),
        "intraday": sum(1 for r in rows if r.get("is_intraday")),
    }


def _filter_positions(rows: List[Dict[str, Any]], segment: str) -> List[Dict[str, Any]]:
    if segment == "fno":
        return [r for r in rows if r.get("segment") == "fno"]
    if segment == "intraday":
        return [r for r in rows if r.get("is_intraday")]
    return rows


@router.get("/accounts/{account_id}/positions")
async def get_account_positions(
    request: Request,
    account_id: str,
    kind: Literal["net", "day"] = "net",
    segment: Literal["all", "fno", "intraday"] = "all",
):
    """Current positions of one natively connected account, read live from
    the broker on every call and never stored. `counts` describe the whole
    read; `segment` only narrows `positions`.
    """
    user = await _hub_user(request)
    doc = await _get_owned_account(user["user_id"], account_id)
    if not doc.get("native"):
        raise _not_native(doc, _NOT_NATIVE_POSITIONS)
    try:
        rows = await _hub.read_account_positions(db, doc, kind)
    except Exception as e:  # noqa: BLE001
        raise _read_error(e, doc, f"{kind} positions") from None
    return {
        "account_id": account_id,
        "broker": doc.get("broker"),
        "kind": kind,
        "segment": segment,
        "as_of": _now_iso(),
        "positions": _filter_positions(rows, segment),
        "counts": _position_counts(rows),
    }


@router.get("/accounts/{account_id}/contract-chart")
async def get_contract_chart(
    request: Request,
    account_id: str,
    symbol: str = Query(..., min_length=1, max_length=40),
    exchange: str = Query(..., min_length=2, max_length=10),
    instrument_type: Literal["FUT", "CE", "PE"] = Query(...),
    expiry: str = Query(..., min_length=10, max_length=10),
    strike: Optional[float] = Query(None),
    interval: Literal["5m", "30m"] = "5m",
):
    """The price history and latest quote of one futures or options contract
    the account holds — the contract's own price, not the underlying share's —
    read live from the broker on every call and never stored. The contract is
    named by the values of its position row.
    """
    user = await _hub_user(request)
    doc = await _get_owned_account(user["user_id"], account_id)
    if not doc.get("native"):
        raise ValidationException(
            "A contract chart is available only for accounts connected by signing in on the broker's own page.",
            code=_hub.CODE_NOT_SUPPORTED,
            details=_account_details(doc),
        )
    try:
        contract = _hub.parse_contract(symbol, exchange, instrument_type, expiry, strike)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from None
    try:
        chart = await _hub.read_contract_chart(db, doc, contract, interval)
    except Exception as e:  # noqa: BLE001
        raise _read_error(e, doc, "a contract chart") from None
    return {
        "account_id": account_id,
        "broker": doc.get("broker"),
        "broker_display": _hub.display_name(doc.get("broker") or ""),
        "contract": {
            "symbol": contract.symbol, "exchange": contract.exchange,
            "instrument_type": contract.instrument_type,
            "expiry": contract.expiry, "strike": contract.strike,
        },
        "interval": interval,
        "as_of": _now_iso(),
        "candles": chart["candles"],
        "quote": chart["quote"],
    }


@router.get("/positions")
async def get_all_positions(
    request: Request,
    kind: Literal["net", "day"] = "net",
    segment: Literal["all", "fno", "intraday"] = "all",
):
    """Current positions across every broker account of the user. Each
    account is read on its own, a few at a time: one failing — or needing a
    reconnect — is reported in its entry and never fails the others. An
    OpenAlgo account is listed with the not-supported error and is not read.
    """
    user = await _hub_user(request)
    docs = await _user_accounts(user["user_id"])
    gate = asyncio.Semaphore(_hub.LIVE_READ_CONCURRENCY)

    async def _read_one(doc: Dict[str, Any]) -> Dict[str, Any]:
        entry: Dict[str, Any] = {
            **_account_entry(doc),
            "ok": False,
            "error": None,
            "as_of": None,
            "positions": [],
            "counts": _position_counts([]),
        }
        if not doc.get("native"):
            entry["error"] = {"code": _hub.CODE_NOT_SUPPORTED, "message": _NOT_NATIVE_POSITIONS}
            entry["as_of"] = _now_iso()
            return entry
        try:
            async with gate:
                rows = await _hub.read_account_positions(db, doc, kind)
        except Exception as e:  # noqa: BLE001
            code, message = _hub.describe_failure(
                e, doc.get("broker") or "", f"{kind} positions",
            )
            entry["error"] = {"code": code, "message": message}
        else:
            entry["ok"] = True
            entry["positions"] = _filter_positions(rows, segment)
            entry["counts"] = _position_counts(rows)
        entry["as_of"] = _now_iso()
        return entry

    accounts = await asyncio.gather(*(_read_one(d) for d in docs))
    return {
        "as_of": _now_iso(),
        "kind": kind,
        "segment": segment,
        "accounts": list(accounts),
    }


# ── Sync snapshots ───────────────────────────────────────────────────────
# Reading one's own sync history needs a signed-in user but not the
# `broker_hub` flag: it must survive the flag being switched off.
@router.get("/accounts/{account_id}/snapshots")
async def list_account_snapshots(
    request: Request,
    account_id: str,
    limit: int = Query(30, ge=1, le=_snapshots.MAX_PER_ACCOUNT),
):
    """The holdings syncs of one of the user's accounts, newest first, each
    without its holdings rows (`GET /snapshots/{id}` has those)."""
    user = await get_current_user(request)
    doc = await _get_owned_account(user["user_id"], account_id)
    return {
        "account_id": account_id,
        "broker": doc.get("broker"),
        "snapshots": await _snapshots.list_for_account(db, user["user_id"], account_id, limit),
    }


@router.get("/snapshots/{snapshot_id}")
async def get_snapshot(request: Request, snapshot_id: str):
    """One sync snapshot with the holdings as they were stored, for the user
    it belongs to."""
    user = await get_current_user(request)
    snapshot = await _snapshots.get_for_owner(db, user["user_id"], snapshot_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail="Broker sync snapshot not found")
    return snapshot


@router.delete("/accounts/{account_id}")
async def disconnect_broker(request: Request, account_id: str):
    user = await get_current_user(request)
    user_id = user["user_id"]
    doc = await _get_owned_account(user_id, account_id)

    # Remove the account-scoped holdings so the dashboard reflects the
    # disconnect immediately. CAS / Excel rows for the same user stay.
    await db.holdings.delete_many(
        {"user_id": user_id, "broker_account_id": account_id},
    )
    # The sync snapshots are copies of those holdings: they go with them.
    await _snapshots.delete_for_account(db, user_id, account_id)
    await db.broker_accounts.delete_one({"account_id": account_id})

    # Stop the per-account OpenAlgo instance (if this account had one)
    # and wipe its data dir. Best-effort: do not fail the disconnect if
    # the kill / cleanup hits a snag — the broker_account row is
    # already gone so the user sees the disconnect succeed.
    if doc.get("openalgo_per_account_instance"):
        try:
            await _instance_mgr.stop(db, account_id)
        except Exception:  # noqa: BLE001
            logger.exception("disconnect: stop per-account instance failed for %s", account_id)

    await _audit.record(
        user_id=user_id, action="broker_disconnect", resource=account_id,
        outcome="success",
        ip=request.client.host if request.client else "",
        ua=request.headers.get("user-agent", ""),
        details={"broker": doc.get("broker"), "instance_stopped": bool(doc.get("openalgo_per_account_instance"))},
    )
    return {"ok": True}


# ── Holdings persistence ────────────────────────────────────────────────
async def _persist_broker_holdings(
    user_id: str,
    account_id: str,
    account_doc: Dict[str, Any],
    rows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Replace this account's prior holdings, leave other-source rows alone.

    Each broker holding gets `broker_account_id = <account>` so successive
    syncs (and disconnects) only touch their own rows.
    """
    await db.holdings.delete_many(
        {"user_id": user_id, "broker_account_id": account_id},
    )

    inserted: List[Dict[str, Any]] = []
    now = _now_iso()
    for r in rows:
        asset_type = r.get("asset_type", "equity")
        if asset_type not in ("equity", "mutual_fund", "etf", "bond", "gold", "fd", "other"):
            asset_type = "equity"
        holding_doc = {
            "holding_id": f"hold_{uuid.uuid4().hex[:12]}",
            "user_id": user_id,
            "portfolio_id": "",
            "name": r.get("name") or r.get("ticker") or "Unknown",
            "ticker": r.get("ticker") or "",
            "asset_type": asset_type,
            "quantity": float(r.get("quantity") or 0),
            "buy_price": float(r.get("buy_price") or 0),
            "current_price": float(r.get("current_price") or 0),
            "sector": r.get("sector") or "Other",
            "buy_date": None,
            "source": "openalgo",
            "source_id": r.get("source_id") or "",
            "broker": account_doc.get("broker"),
            "broker_account_id": account_id,
            "uploaded_at": now,
            "created_at": now,
        }
        await db.holdings.insert_one(holding_doc)
        inserted.append({
            "holding_id": holding_doc["holding_id"],
            "name": holding_doc["name"],
            "ticker": holding_doc["ticker"],
            "asset_type": asset_type,
            "quantity": holding_doc["quantity"],
        })

    try:
        await db.mfd_profile_signal_cache.delete_one({"user_id": user_id})
    except Exception:  # noqa: BLE001
        pass
    return inserted


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
