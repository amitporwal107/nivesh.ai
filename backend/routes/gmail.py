"""Gmail auto-fetch routes.

Server-side CAS parsing was removed alongside the casparser.in REST API
chain. /api/gmail/import now returns 410 — clients should use the
Connect SDK widget (CasUploadButton) which has Gmail inbox access built
in (`enableInbox: true`) and parses entirely in-browser. The remaining
gmail/* endpoints still mediate Google OAuth so the SDK widget can pick
up the connected token.
"""
from fastapi import APIRouter, HTTPException, Request, BackgroundTasks
from fastapi.responses import RedirectResponse
from datetime import datetime, timezone, timedelta
import logging
import urllib.parse
import uuid

from deps import db, get_current_user, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GMAIL_REDIRECT_URI, COOKIE_SECURE, COOKIE_SAMESITE
from services.gmail_service import (
    get_authorization_url, exchange_code_for_tokens,
    get_gmail_credentials, build_gmail_service,
    scan_for_cas_emails,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


def _resolve_gmail_redirect_uri(request: Request) -> str:
    """Build the OAuth redirect URI.

    Priority:
      1. `GMAIL_REDIRECT_URI` env/secret override (explicit production value)
      2. Reconstruct from `X-Forwarded-Host` + `X-Forwarded-Proto` headers,
         which the Kubernetes ingress sets to the **public** hostname
         (request.base_url unfortunately returns the cluster-internal host
         behind the ingress, which Google has NOT whitelisted → 400
         redirect_uri_mismatch).
      3. Fall back to `request.base_url` for local dev.
    """
    if GMAIL_REDIRECT_URI:
        return GMAIL_REDIRECT_URI
    fwd_host = request.headers.get("x-forwarded-host") or request.headers.get("host")
    fwd_proto = request.headers.get("x-forwarded-proto", "https")
    if fwd_host:
        return f"{fwd_proto}://{fwd_host}/api/oauth/gmail/callback"
    base = str(request.base_url).rstrip("/")
    return f"{base}/api/oauth/gmail/callback"


@router.get("/gmail/connect")
async def gmail_connect(request: Request, return_to: str = ""):
    """Start Gmail OAuth flow. Optional `return_to` path is stored in the
    state doc and used by the callback to redirect back to the caller's page
    (e.g. /v2/app for V2 onboarding, /v2/dashboard for V1 dashboard)."""
    user = await get_current_user(request)

    redirect_uri = _resolve_gmail_redirect_uri(request)

    # Open-redirect guard: the callback appends a one-time session-minting code
    # to return_to, so only a local (non protocol-relative) path may be stored.
    if not return_to.startswith("/") or return_to.startswith("//") or "://" in return_to:
        return_to = "/v2/dashboard"

    state = f"{user['user_id']}_{uuid.uuid4().hex[:8]}"
    await db.gmail_oauth_states.insert_one({
        "state": state,
        "user_id": user["user_id"],
        "return_to": return_to,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
    })

    url, code_verifier = get_authorization_url(GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, redirect_uri, state)

    await db.gmail_oauth_states.update_one(
        {"state": state},
        {"$set": {"code_verifier": code_verifier}}
    )

    return {"auth_url": url}


@router.get("/oauth/gmail/callback")
async def gmail_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    """Handle Gmail OAuth callback from Google.

    Dispatches by `state` prefix:
      - `invite_*`  → client CAS invite flow (public, no session required)
      - else        → standard logged-in user Gmail connect flow
    """
    # ── Dispatch: invite flow uses a dedicated handler that does not
    # require the caller to be logged in to our app (the client who
    # opened the public link is a stranger to our auth system).
    if state and state.startswith("invite_"):
        from routes.client_cas_invite import _handle_invite_oauth_callback
        return await _handle_invite_oauth_callback(request, code, state, error)

    # Resolve the caller's relay page (return_to) up-front so EVERY exit path —
    # success *and* failure — sends the popup back to it. Google echoes the
    # `state` parameter on error responses too (RFC 6749 §4.1.2.1), so even a
    # user who declines consent can be returned to the popup relay, which posts
    # the outcome to the opener and closes itself. Hard-coding a path here left
    # the popup stranded on a non-relay route (the v5 app has no /v2/dashboard);
    # the user closing that stranded popup surfaced as a misleading
    # "Gmail connection was cancelled" with no real reason shown.
    state_doc = await db.gmail_oauth_states.find_one({"state": state}, {"_id": 0}) if state else None
    return_to = (state_doc or {}).get("return_to") or "/v2/dashboard"
    # Defence in depth: re-validate before redirecting to it with a one-time code.
    if not return_to.startswith("/") or return_to.startswith("//") or "://" in return_to:
        return_to = "/v2/dashboard"

    def _fail(reason: str) -> RedirectResponse:
        sep = "&" if "?" in return_to else "?"
        return RedirectResponse(url=f"{return_to}{sep}gmail_error={reason}")

    if error:
        logger.warning("Gmail OAuth declined/error: %s", error)
        return _fail("denied")

    if not code or not state:
        return _fail("missing_params")

    if not state_doc:
        return _fail("invalid_state")

    expires_at = state_doc["expires_at"]
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) > expires_at:
        return _fail("state_expired")

    user_id = state_doc["user_id"]
    code_verifier = state_doc.get("code_verifier")
    await db.gmail_oauth_states.delete_one({"state": state})

    redirect_uri = _resolve_gmail_redirect_uri(request)

    try:
        tokens = exchange_code_for_tokens(GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, redirect_uri, code, code_verifier=code_verifier)
    except Exception as e:
        logger.error("Gmail token exchange failed: %s", e)
        return _fail("token_exchange_failed")

    await db.gmail_tokens.update_one(
        {"user_id": user_id},
        {"$set": {
            "user_id": user_id,
            **tokens,
            "connected_at": datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True,
    )

    logger.info("Gmail connected for user %s", user_id)

    # Store a short-lived one-time code and redirect to the frontend with it
    # in the URL.  AuthContext.checkAuth() detects ?gmail_code=xxx, POSTs it to
    # /api/auth/gmail-session (a direct non-redirect response), receives the
    # session cookie there, and sets the user — much more reliable than trying
    # to preserve Set-Cookie across a server-side redirect chain.
    gmail_code = uuid.uuid4().hex
    await db.gmail_success_codes.insert_one({
        "code": gmail_code,
        "user_id": user_id,
        "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=120)).isoformat(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    sep = "&" if "?" in return_to else "?"
    return RedirectResponse(url=f"{return_to}{sep}gmail_code={gmail_code}")


@router.get("/gmail/status")
async def gmail_status(request: Request):
    """Check if user has Gmail connected."""
    user = await get_current_user(request)
    token_doc = await db.gmail_tokens.find_one({"user_id": user["user_id"]}, {"_id": 0})
    if not token_doc:
        return {"connected": False}

    last_import = await db.gmail_imports.find_one(
        {"user_id": user["user_id"], "status": "completed"},
        {"_id": 0},
        sort=[("imported_at", -1)]
    )

    return {
        "connected": True,
        "connected_at": token_doc.get("connected_at"),
        "last_import": {
            "filename": last_import.get("filename"),
            "imported_at": last_import.get("imported_at"),
            "count": last_import.get("count", 0),
        } if last_import else None,
        # Auto-import: only effective once the user has successfully done a
        # manual import (because we save the unlocking PAN at that moment).
        "auto_import_enabled": bool(token_doc.get("auto_import_enabled")),
        "auto_import_ready": bool(token_doc.get("cas_password")),
        "last_auto_import_at": token_doc.get("last_auto_import_at"),
    }


@router.get("/gmail/history")
async def gmail_import_history(request: Request):
    """Get history of all Gmail imports for this user."""
    user = await get_current_user(request)
    imports = await db.gmail_imports.find(
        {"user_id": user["user_id"]},
        {"_id": 0}
    ).sort("imported_at", -1).to_list(50)
    return {"imports": imports}


@router.get("/portfolio/upload-history")
async def upload_history(request: Request):
    """Get history of all file uploads for this user."""
    user = await get_current_user(request)
    tasks = await db.upload_tasks.find(
        {"user_id": user["user_id"]},
        {"_id": 0, "task_id": 1, "status": 1, "message": 1, "count": 1, "source": 1, "created_at": 1, "completed_at": 1}
    ).sort("created_at", -1).to_list(50)
    return {"uploads": tasks}


@router.post("/gmail/disconnect")
async def gmail_disconnect(request: Request):
    """Disconnect Gmail."""
    user = await get_current_user(request)
    await db.gmail_tokens.delete_one({"user_id": user["user_id"]})
    return {"message": "Gmail disconnected"}


@router.post("/gmail/auto-import/run")
async def gmail_auto_import_run(request: Request):
    """Manually trigger the auto-import sweep for the calling user.
    Equivalent to what the daily 06:30 IST scheduler does, but on-demand.
    Useful for testing and as a 'pull now' button on the dashboard."""
    user = await get_current_user(request)
    from services.gmail_auto_import import auto_import_for_user
    result = await auto_import_for_user(db, user["user_id"])
    return result


@router.post("/gmail/auto-import/toggle")
async def gmail_auto_import_toggle(request: Request):
    """Enable or disable scheduled auto-import for this user. Body:
    {"enabled": bool}. Default-on once a user successfully imports
    manually (the manual import flow sets `auto_import_enabled=True`)."""
    user = await get_current_user(request)
    body = await request.json()
    enabled = bool(body.get("enabled", True))
    await db.gmail_tokens.update_one(
        {"user_id": user["user_id"]},
        {"$set": {"auto_import_enabled": enabled}},
    )
    return {"auto_import_enabled": enabled}


@router.post("/gmail/scan")
async def gmail_scan(request: Request):
    """Scan Gmail for CAS emails."""
    user = await get_current_user(request)
    token_doc = await db.gmail_tokens.find_one({"user_id": user["user_id"]}, {"_id": 0})
    if not token_doc:
        raise HTTPException(status_code=400, detail="Gmail not connected. Please connect Gmail first.")

    try:
        creds = get_gmail_credentials(token_doc)
        service = build_gmail_service(creds)

        if creds.token != token_doc["access_token"]:
            await db.gmail_tokens.update_one(
                {"user_id": user["user_id"]},
                {"$set": {
                    "access_token": creds.token,
                    "expires_at": creds.expiry.replace(tzinfo=timezone.utc).isoformat() if creds.expiry else None,
                }}
            )

        emails = scan_for_cas_emails(service, max_results=20)

        holdings_exist = await db.holdings.count_documents({"user_id": user["user_id"]}) > 0
        imported_ids = set()
        if holdings_exist:
            existing = await db.gmail_imports.find({"user_id": user["user_id"], "status": "completed"}, {"_id": 0, "message_id": 1}).to_list(500)
            imported_ids = {e["message_id"] for e in existing}

        for email in emails:
            email["already_imported"] = email["message_id"] in imported_ids

        return {"emails": emails, "total": len(emails)}
    except Exception as e:
        logger.error("Gmail scan failed: %s", e)
        if "invalid_grant" in str(e).lower() or "token" in str(e).lower():
            await db.gmail_tokens.delete_one({"user_id": user["user_id"]})
            raise HTTPException(status_code=401, detail="Gmail session expired. Please reconnect Gmail.")
        raise HTTPException(status_code=500, detail=f"Gmail scan failed: {str(e)}")


@router.post("/gmail/import")
async def gmail_import(request: Request, background_tasks: BackgroundTasks):  # noqa: ARG001
    """DEPRECATED — server-side Gmail CAS parsing was removed when we
    consolidated CAS parsing into the Connect SDK widget.

    The Connect SDK has built-in Gmail inbox access (`enableInbox: true`)
    that runs entirely in the user's browser: it authorises with Gmail,
    fetches CAS emails, parses them via casparser.in, and returns the
    parsed JSON which is POSTed to /api/portfolio/import-connect. Use
    that flow instead of this endpoint.
    """
    raise HTTPException(status_code=410, detail=(
        "Server-side Gmail CAS import is no longer supported. "
        "Use the Connect SDK widget (CasUploadButton) — it has Gmail "
        "inbox access built in and parses everything client-side."
    ))


# Server-side Gmail CAS background processor removed alongside the
# /api/gmail/import endpoint. CAS parsing now happens exclusively inside
# the Connect SDK widget (enableInbox: true gives the widget direct Gmail
# access), and the widget returns parsed JSON which is POSTed to
# /api/portfolio/import-connect.
