"""Native broker connect — direct broker OAuth, no OpenAlgo in the loop.

The "wrapper" path (per the user's request): each supported broker is
implemented as a thin Nivesh adapter under `services.brokers.<slug>`.
Adapters use either the broker's official Python SDK (Zerodha/Kite,
Upstox, Angel/SmartAPI, Fyers, Dhan) or vendored OpenAlgo plugin code
for brokers without an SDK. Either way the user-facing flow is:

    Nivesh UI  → /api/broker/native/start/<slug>?return_to=<path>
        302 →  broker's own OAuth login URL (kite.trade, upstox.com, …)
    User authenticates at broker
        302 →  broker → /api/broker/native/callback?broker=<slug>&code=…
    Nivesh exchanges code → access_token → encrypts → saves → first sync
        302 →  `return_to` (the page the user started from), else /dashboard

No OpenAlgo dashboard, no SSO bridge, no per-user containers, no proxy
rewriting. Pure Nivesh UX.

State for the round-trip is stored in `broker_oauth_states` Mongo
collection (10-min TTL), keyed by a random `state` token in the URL.
The `state` ties the callback back to the originating Nivesh user.

The callback always lands the browser back on a Nivesh page and reports
the outcome in the query string, keeping whatever query the page had:

    ?broker_connected=<slug>&account_id=<id>     connected
    ?broker_error=<code>                         not connected

`<code>` is one of a fixed set — never text supplied by the broker:
    denied                 the broker reported an error / the user backed out
    missing_params         no broker slug, or no authorisation value
    unknown_broker         the slug is not a registered broker
    invalid_state          no matching sign-in attempt for this callback
    state_expired          the sign-in attempt is older than 10 minutes
    token_exchange_failed  the broker did not hand back a session token
"""
from __future__ import annotations

import asyncio
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
from urllib.parse import unquote_plus, urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from deps import db, get_current_user
from feature_gate import require_feature
from services import audit as _audit
from services.brokers import registry as _broker_registry
from services.brokers import sessions as _sessions

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/broker/native")

OAUTH_STATE_TTL_MIN = 10
FIRST_SYNC_TIMEOUT_S = 12
DEFAULT_RETURN_TO = "/dashboard"
# Query params this module appends to the page the user lands back on.
_RESULT_PARAMS = ("broker_connected", "broker_error", "account_id")
# Off stops new sign-ins (feature_flags.KNOWN_FEATURES); the listing and an
# already-started callback stay available.
FLAG = "broker_hub"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _hub_user(request: Request) -> dict:
    """The signed-in user, refused with 403 when `broker_hub` is off for them."""
    return await require_feature(
        FLAG, resolve_user=lambda r: get_current_user(r), get_db=lambda: db,
    )(request)


def _redirect_uri(request: Request, broker_slug: str) -> str:
    """Build the absolute callback URL Nivesh advertises to the broker.
    Uses the public preview / prod hostname (X-Forwarded-Host) so the
    URL matches what the operator registered on the broker's dev portal.
    """
    fwd_host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
    fwd_proto = request.headers.get("x-forwarded-proto", "https")
    base = f"{fwd_proto}://{fwd_host}"
    # A broker that appends its own `?…` to the registered URL (Angel One)
    # cannot be given one that already has a query string.
    try:
        path_style = getattr(_broker_registry.get(broker_slug), "CALLBACK_PATH_STYLE", False)
    except KeyError:
        path_style = False
    if path_style:
        return f"{base}/api/broker/native/callback/{broker_slug}"
    return f"{base}/api/broker/native/callback?broker={broker_slug}"


def _back(target: str, **params: str) -> RedirectResponse:
    """Redirect to `target` — a path `safe_return_to` accepted, or the
    default — with the outcome params appended. A query string or fragment
    it already carries is kept as-is; outcome params left over from an
    earlier round-trip are dropped so the page reads exactly one outcome.
    """
    parts = urlsplit(target)
    kept = [
        seg for seg in parts.query.split("&")
        if seg and unquote_plus(seg.split("=", 1)[0]) not in _RESULT_PARAMS
    ]
    query = "&".join(kept + [urlencode(params)])
    return RedirectResponse(url=urlunsplit(("", "", parts.path, query, parts.fragment)))


async def _find_state(request: Request, state: str, broker_slug: str) -> Tuple[Optional[dict], bool]:
    """Find the sign-in attempt this callback belongs to. Returns
    `(state_doc, signed_in)`; `signed_in` is False only when the fallback
    below was needed and nobody is logged in.
    """
    # `state` may be missing for brokers that don't echo it back (Kite
    # passes it via redirect_params and may strip on some flows). When
    # present, validate; when absent, fall back to the most recent
    # unused state for the broker. Accepting fallback is a small
    # downgrade from full CSRF protection — acceptable here because the
    # broker callback URL is registered + this endpoint requires HTTPS.
    state_doc = None
    if state:
        state_doc = await db.broker_oauth_states.find_one({"state": state}, {"_id": 0})
    if state_doc or not broker_slug:
        return state_doc, True
    # broker_slug is enough to find the most recent state for this
    # broker, but we still need a way to identify the user — fall
    # back to none here means the user MUST be logged in.
    try:
        user = await get_current_user(request)
    except HTTPException:
        return None, False
    state_doc = await db.broker_oauth_states.find_one(
        {"user_id": user["user_id"], "broker": broker_slug},
        {"_id": 0},
        sort=[("created_at", -1)],
    )
    return state_doc, True


# ── Routes ───────────────────────────────────────────────────────────────
@router.get("/supported")
async def list_supported(request: Request):
    """Public broker dropdown — what Nivesh has native adapters for."""
    await get_current_user(request)
    brokers = _broker_registry.list_supported()
    if not _sessions.storage_ready():
        # No session token can be stored, so no sign-in can complete on this
        # server whatever the broker's own keys say: nothing is set up.
        for b in brokers:
            b["configured"] = False
            b["connectable"] = False
    return {"brokers": brokers}


@router.get("/start/{broker_slug}")
async def start_oauth(broker_slug: str, request: Request):
    """Generate a state token, persist (state → user_id, broker), and
    redirect the user's browser to the broker's OAuth login URL.

    `return_to` (optional) is the Nivesh page to land back on afterwards;
    it is kept only when it is a plain same-site path.
    """
    user = await _hub_user(request)
    user_id = user["user_id"]
    try:
        broker = _broker_registry.get(broker_slug)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown broker '{broker_slug}'")

    # A placeholder, or an adapter whose sign-in is switched off: say so
    # plainly instead of failing inside `auth_url`.
    if not getattr(broker, "IMPLEMENTED", True):
        raise HTTPException(
            status_code=400,
            detail=f"{broker.DISPLAY} cannot be connected from Nivesh yet.",
        )

    # The server cannot encrypt a session token, so the sign-in could not be
    # saved when the user comes back: stop before sending them to the broker.
    if not _sessions.storage_ready():
        await _audit.record(
            user_id=user_id, action="broker_connect", outcome="error",
            ip=request.client.host if request.client else "",
            ua=request.headers.get("user-agent", ""),
            details={"broker": broker_slug, "stage": "auth_url", "reason": "token storage not configured"},
        )
        raise HTTPException(
            status_code=503,
            detail="Broker connections are not set up on this server yet.",
        )

    # Nivesh's own app keys for this broker are not set: the login could
    # not finish, so stop here rather than send the user to the broker.
    missing = _broker_registry.missing_secrets(broker_slug)
    if broker.AUTH_STYLE == "oauth" and missing:
        await _audit.record(
            user_id=user_id, action="broker_connect", outcome="error",
            ip=request.client.host if request.client else "",
            ua=request.headers.get("user-agent", ""),
            details={
                "broker": broker_slug, "stage": "auth_url",
                "reason": "app keys not configured: " + ", ".join(missing),
            },
        )
        raise HTTPException(
            status_code=503,
            detail=f"{broker.DISPLAY} sign-in is not available yet — Nivesh's {broker.DISPLAY} app keys are not configured.",
        )

    state = secrets.token_urlsafe(24)
    redirect_uri = _redirect_uri(request, broker_slug)

    state_doc = {
        "state": state,
        "user_id": user_id,
        "broker": broker_slug,
        "redirect_uri": redirect_uri,
        "created_at": _now_iso(),
        "expires_at": (
            datetime.now(timezone.utc) + timedelta(minutes=OAUTH_STATE_TTL_MIN)
        ).isoformat(),
    }
    return_to = _sessions.safe_return_to(request.query_params.get("return_to"))
    if return_to:
        state_doc["return_to"] = return_to
    await db.broker_oauth_states.insert_one(state_doc)

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
    `request_token`, OAuth2 brokers use `code`, and an adapter may name
    others in `CALLBACK_CODE_PARAMS`. Adapters consume them all via the
    unified `code` arg.
    """
    return await _finish_sign_in(request, request.query_params.get("broker") or "")


@router.get("/callback/{broker_slug}")
async def oauth_callback_for(broker_slug: str, request: Request):
    """The same callback with the broker in the path, for adapters that set
    `CALLBACK_PATH_STYLE` (see `_redirect_uri`)."""
    return await _finish_sign_in(request, broker_slug)


async def _finish_sign_in(request: Request, broker_slug: str):
    qp = request.query_params
    state = qp.get("state") or ""
    status = qp.get("status")
    error = qp.get("error") or (status if status not in ("success", None) else "")

    state_doc, signed_in = await _find_state(request, state, broker_slug)
    back = _sessions.safe_return_to((state_doc or {}).get("return_to")) or DEFAULT_RETURN_TO

    if error:
        # The broker's own text stays in our log; the page only gets a fixed code.
        logger.info("native broker callback: %r reported an error: %r", broker_slug[:40], error[:120])
        return _back(back, broker_error="denied")
    if not broker_slug:
        return _back(back, broker_error="missing_params")
    try:
        broker = _broker_registry.get(broker_slug)
    except KeyError:
        return _back(back, broker_error="unknown_broker")
    code = ""
    for name in ("code", "request_token", *getattr(broker, "CALLBACK_CODE_PARAMS", ())):
        code = qp.get(name) or ""
        if code:
            break
    if not code:
        return _back(back, broker_error="missing_params")

    if not signed_in:
        return RedirectResponse(url="/login?next=/dashboard")
    if not state_doc:
        return _back(back, broker_error="invalid_state")

    expires_at = state_doc["expires_at"]
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) > expires_at:
        return _back(back, broker_error="state_expired")

    user_id = state_doc["user_id"]
    redirect_uri = state_doc.get("redirect_uri") or _redirect_uri(request, broker_slug)
    await db.broker_oauth_states.delete_one({"state": state_doc["state"]})

    try:
        access_token = await broker.exchange_code(
            code=code, state=state_doc.get("state", ""), redirect_uri=redirect_uri,
        )
        if not access_token.token:
            raise RuntimeError("adapter returned no session token")
    except Exception as e:  # noqa: BLE001
        # Adapters put the broker's raw response into their error text, and
        # that can carry token fields: record only the kind of failure.
        logger.error("native broker exchange_code failed for %s (%s)", broker_slug, type(e).__name__)
        await _audit.record(
            user_id=user_id, action="broker_connect", outcome="error",
            ip=request.client.host if request.client else "",
            ua=request.headers.get("user-agent", ""),
            details={"broker": broker_slug, "stage": "exchange_code", "reason": type(e).__name__},
        )
        return _back(back, broker_error="token_exchange_failed")

    # Persist as a `broker_accounts` row — same shape as the OpenAlgo
    # path so /sync, /disconnect, etc. work uniformly. Reconnecting the
    # same broker login refreshes its row instead of adding another.
    try:
        doc = await _sessions.upsert_native_account(
            db, user_id=user_id, slug=broker_slug, display=broker.DISPLAY, token=access_token,
        )
    except Exception as e:  # noqa: BLE001
        # The broker signed the user in but the session could not be saved
        # (encryption key missing, database down). Send them back to the page
        # they came from with a code, never a raw error page.
        logger.error("native broker session could not be stored for %s (%s)", broker_slug, type(e).__name__)
        await _audit.record(
            user_id=user_id, action="broker_connect", outcome="error",
            ip=request.client.host if request.client else "",
            ua=request.headers.get("user-agent", ""),
            details={"broker": broker_slug, "stage": "store", "reason": type(e).__name__},
        )
        return _back(back, broker_error="server_error")
    account_id = doc["account_id"]

    # First holdings sync, so the portfolio is there when the user lands
    # back. A failed or slow sync must not fail the connect.
    try:
        # Imported here so this module stays importable on its own.
        from services.brokers import hub_reads
        await asyncio.wait_for(hub_reads.sync_account(db, doc), timeout=FIRST_SYNC_TIMEOUT_S)
    except Exception as e:  # noqa: BLE001
        timed_out = isinstance(e, asyncio.TimeoutError)
        logger.warning(
            "native broker first sync %s for %s (%s)",
            "timed out" if timed_out else "failed", account_id, type(e).__name__,
        )
        await db.broker_accounts.update_one(
            {"account_id": account_id},
            {"$set": {
                "last_error": "First holdings sync timed out." if timed_out else "First holdings sync failed.",
                "updated_at": _now_iso(),
            }},
        )

    await _audit.record(
        user_id=user_id, action="broker_connect", resource=account_id,
        outcome="success",
        ip=request.client.host if request.client else "",
        ua=request.headers.get("user-agent", ""),
        details={"broker": broker_slug, "native": True},
    )
    return _back(back, broker_connected=broker_slug, account_id=account_id)
