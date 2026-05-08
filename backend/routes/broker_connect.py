"""Broker Connect routes — Nivesh Secure Portfolio Connect.

Read-only broker integration via OpenAlgo. Per-user OpenAlgo API keys are
encrypted with AES-256-GCM (`services.pii_security`) before storage; we
never persist raw broker passwords, TOTP seeds, or trading PINs.

Routes (all under /api/broker, all authenticated):

    GET    /api/broker/supported              — list of brokers we accept
    GET    /api/broker/accounts               — current user's connections
    POST   /api/broker/connect                — store + verify a new conn
    POST   /api/broker/accounts/{id}/sync     — fetch holdings via OpenAlgo
    DELETE /api/broker/accounts/{id}          — disconnect (delete + audit)

The sync endpoint imports holdings into the same `db.holdings` collection
as CAS / Excel imports. Source-tracking distinguishes broker rows from
CAS rows: `source = "openalgo"`, `source_id = "{exchange}:{symbol}"`,
`broker_account_id = "<account>"`. Re-syncing the same account replaces
*only that account's* prior rows so concurrent CAS imports stay intact.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from deps import db, get_current_user
from services import audit as _audit
from services import pii_security as _pii
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
    return {
        "account_id": doc["account_id"],
        "broker": doc.get("broker"),
        "broker_display": SUPPORTED_BROKERS.get(doc.get("broker") or "", doc.get("broker")),
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
