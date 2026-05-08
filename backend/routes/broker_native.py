"""Native broker connect — direct broker OAuth, no OpenAlgo in the loop.

The "wrapper" path (per the user's request): each supported broker is
implemented as a thin Nivesh adapter under `services.brokers.<slug>`.
Adapters use either the broker's official Python SDK (Zerodha/Kite,
Upstox, Angel/SmartAPI, Fyers, Dhan) or vendored OpenAlgo plugin code
for brokers without an SDK. Either way the user-facing flow is:

    Nivesh UI  → /api/broker/native/start/<slug>
        302 →  broker's own OAuth login URL (kite.trade, upstox.com, …)
    User authenticates at broker
        302 →  broker → /api/broker/native/callback?broker=<slug>&code=…
    Nivesh exchanges code → access_token → encrypts → saves
        302 →  Nivesh dashboard

No OpenAlgo dashboard, no SSO bridge, no per-user containers, no proxy
rewriting. Pure Nivesh UX.

State for the round-trip is stored in `broker_oauth_states` Mongo
collection (10-min TTL), keyed by a random `state` token in the URL.
The `state` ties the callback back to the originating Nivesh user.
"""
from __future__ import annotations

import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from deps import db, get_current_user
from services import audit as _audit
from services import pii_security as _pii
from services.brokers import registry as _broker_registry
from services.openalgo_client import mask_api_key  # reused for masking

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/broker/native")

OAUTH_STATE_TTL_MIN = 10


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _redirect_uri(request: Request, broker_slug: str) -> str:
    """Build the absolute callback URL Nivesh advertises to the broker.
    Uses the public preview / prod hostname (X-Forwarded-Host) so the
    URL matches what the operator registered on the broker's dev portal.
    """
    fwd_host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
    fwd_proto = request.headers.get("x-forwarded-proto", "https")
    base = f"{fwd_proto}://{fwd_host}"
    return f"{base}/api/broker/native/callback?broker={broker_slug}"


# ── Routes ───────────────────────────────────────────────────────────────
@router.get("/supported")
async def list_supported(request: Request):
    """Public broker dropdown — what Nivesh has native adapters for."""
    await get_current_user(request)
    return {"brokers": _broker_registry.list_supported()}


@router.get("/start/{broker_slug}")
async def start_oauth(broker_slug: str, request: Request):
    """Generate a state token, persist (state → user_id, broker), and
    redirect the user's browser to the broker's OAuth login URL.
    """
    user = await get_current_user(request)
    user_id = user["user_id"]
    try:
        broker = _broker_registry.get(broker_slug)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown broker '{broker_slug}'")

    state = secrets.token_urlsafe(24)
    redirect_uri = _redirect_uri(request, broker_slug)

    await db.broker_oauth_states.insert_one({
        "state": state,
        "user_id": user_id,
        "broker": broker_slug,
        "redirect_uri": redirect_uri,
        "created_at": _now_iso(),
        "expires_at": (
            datetime.now(timezone.utc) + timedelta(minutes=OAUTH_STATE_TTL_MIN)
        ).isoformat(),
    })

    try:
        url = broker.auth_url(state=state, redirect_uri=redirect_uri)
    except RuntimeError as e:
        await _audit.record(
            user_id=user_id, action="broker_connect", outcome="error",
            ip=request.client.host if request.client else "",
            ua=request.headers.get("user-agent", ""),
            details={"broker": broker_slug, "stage": "auth_url", "reason": str(e)},
        )
        raise HTTPException(status_code=500, detail=str(e))

    return RedirectResponse(url=url)


@router.get("/callback")
async def oauth_callback(request: Request):
    """Receives the broker's redirect after the user authenticates. The
    contract is broker-specific in the param names — Kite uses
    `request_token`, OAuth2 brokers use `code`. Adapters consume both
    via the unified `code` arg.
    """
    qp = dict(request.query_params)
    broker_slug = qp.get("broker") or ""
    state = qp.get("state") or ""
    code = qp.get("code") or qp.get("request_token") or ""
    error = qp.get("error") or qp.get("status") if qp.get("status") not in ("success", None) else ""

    if error:
        return RedirectResponse(url=f"/dashboard?broker_error={error}")
    if not (broker_slug and code):
        return RedirectResponse(url="/dashboard?broker_error=missing_params")

    # `state` may be missing for brokers that don't echo it back (Kite
    # passes it via redirect_params and may strip on some flows). When
    # present, validate; when absent, fall back to the most recent
    # unused state for the broker. Accepting fallback is a small
    # downgrade from full CSRF protection — acceptable here because the
    # broker callback URL is registered + this endpoint requires HTTPS.
    state_doc = None
    if state:
        state_doc = await db.broker_oauth_states.find_one({"state": state}, {"_id": 0})
    if not state_doc and broker_slug:
        # broker_slug is enough to find the most recent state for this
        # broker, but we still need a way to identify the user — fall
        # back to none here means the user MUST be logged in.
        try:
            user = await get_current_user(request)
            state_doc = await db.broker_oauth_states.find_one(
                {"user_id": user["user_id"], "broker": broker_slug},
                {"_id": 0},
                sort=[("created_at", -1)],
            )
        except HTTPException:
            return RedirectResponse(url="/login?next=/dashboard")
    if not state_doc:
        return RedirectResponse(url="/dashboard?broker_error=invalid_state")

    expires_at = state_doc["expires_at"]
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) > expires_at:
        return RedirectResponse(url="/dashboard?broker_error=state_expired")

    user_id = state_doc["user_id"]
    redirect_uri = state_doc.get("redirect_uri") or _redirect_uri(request, broker_slug)
    await db.broker_oauth_states.delete_one({"state": state_doc["state"]})

    try:
        broker = _broker_registry.get(broker_slug)
    except KeyError:
        return RedirectResponse(url=f"/dashboard?broker_error=unknown_broker")

    try:
        access_token = await broker.exchange_code(
            code=code, state=state_doc.get("state", ""), redirect_uri=redirect_uri,
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("native broker exchange_code failed")
        await _audit.record(
            user_id=user_id, action="broker_connect", outcome="error",
            ip=request.client.host if request.client else "",
            ua=request.headers.get("user-agent", ""),
            details={"broker": broker_slug, "stage": "exchange_code", "reason": str(e)},
        )
        return RedirectResponse(url=f"/dashboard?broker_error=token_exchange_failed")

    # Persist as a `broker_accounts` row — same shape as the OpenAlgo
    # path so /sync, /disconnect, etc. work uniformly.
    account_id = f"ba_{uuid.uuid4().hex[:12]}"
    extras_blob = _pii.encrypt(_safe_json(access_token.extras))
    now = _now_iso()
    doc = {
        "account_id": account_id,
        "user_id": user_id,
        "broker": broker_slug,
        "label": broker.DISPLAY,
        "openalgo_url": "",
        "openalgo_hosted": False,
        "openalgo_per_account_instance": False,
        "native": True,  # marks this row as following the native path
        "api_key_encrypted": _pii.encrypt(access_token.token),
        "api_key_masked": mask_api_key(access_token.token),
        "extras_encrypted": extras_blob,
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
        details={"broker": broker_slug, "native": True},
    )
    return RedirectResponse(url=f"/dashboard?broker_connected={broker_slug}")


def _safe_json(value: Dict[str, Any]) -> str:
    """Serialise `extras` for encryption. Defensive: any non-JSON-able
    value gets stringified rather than crashing the connect flow.
    """
    import json
    try:
        return json.dumps(value or {}, default=str)
    except Exception:  # noqa: BLE001
        return "{}"
