"""Auth routes: Google OAuth, session management."""
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse as _RedirectResponse
from datetime import datetime, timezone, timedelta
import urllib.parse
import uuid
import httpx
import logging

from deps import db, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, get_current_user, check_whitelist, COOKIE_SECURE, COOKIE_SAMESITE
from core.logging_config import mask_email
from core.exceptions import (
    AuthenticationException, AuthorizationException, ValidationException,
    ResourceNotFoundException, SystemException,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


@router.post("/auth/google")
async def google_auth(request: Request, response: Response):
    """Exchange Google OAuth credential (id_token) for a session."""
    body = await request.json()
    credential = body.get("credential")
    if not credential:
        raise ValidationException("Google credential required", code="VAL-002")

    try:
        async with httpx.AsyncClient() as http_client:
            resp = await http_client.get(
                f"https://oauth2.googleapis.com/tokeninfo?id_token={credential}"
            )
            if resp.status_code != 200:
                raise AuthenticationException("Invalid Google token", code="AUTH-003")

            token_data = resp.json()

            if GOOGLE_CLIENT_ID and token_data.get("aud") != GOOGLE_CLIENT_ID:
                raise AuthenticationException("Token audience mismatch", code="AUTH-003")

            email = token_data.get("email", "").strip().lower()
            name = token_data.get("name", "")
            picture = token_data.get("picture", "")

            if not email:
                raise AuthenticationException("No email in Google token", code="AUTH-003")
    except (AuthenticationException, ValidationException):
        raise
    except Exception as e:
        logger.error("Google token verification failed: %s", type(e).__name__)
        raise AuthenticationException("Failed to verify Google token", code="AUTH-003", cause=e)

    # Whitelist Check
    whitelist_entry = await check_whitelist(email)
    if not whitelist_entry:
        logger.warning("Access denied — email not whitelisted: %s", mask_email(email))
        raise AuthorizationException(
            "Access is currently restricted. Your email is not on the invite list. Please request an invite from the admin.",
            code="AUTHZ-001",
        )

    update_fields = {"status": "active", "registered_at": datetime.now(timezone.utc).isoformat()}
    await db.whitelisted_users.update_one({"email": email}, {"$set": update_fields})

    is_admin = whitelist_entry.get("is_admin", False)

    existing_user = await db.users.find_one({"email": email}, {"_id": 0})
    if existing_user:
        user_id = existing_user["user_id"]
        await db.users.update_one({"email": email}, {"$set": {"name": name, "picture": picture, "is_admin": is_admin}})
    else:
        user_id = f"user_{uuid.uuid4().hex[:12]}"
        await db.users.insert_one({
            "user_id": user_id,
            "email": email,
            "name": name,
            "picture": picture,
            "is_admin": is_admin,
            "created_at": datetime.now(timezone.utc).isoformat()
        })

    session_token = str(uuid.uuid4())
    await db.user_sessions.insert_one({
        "user_id": user_id,
        "session_token": session_token,
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
        "created_at": datetime.now(timezone.utc).isoformat()
    })

    # REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS, THIS BREAKS THE AUTH
    # COOKIE_SECURE / COOKIE_SAMESITE come from env — set to false/lax on HTTP-only deploys.
    response.set_cookie(
        key="session_token",
        value=session_token,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        path="/",
        max_age=7 * 24 * 3600
    )

    # DPDP audit — record successful sign-in.
    try:
        from services import audit
        await audit.record(
            user_id=user_id, action="login",
            ip=request.client.host if request.client else "",
            ua=request.headers.get("user-agent", ""),
            details={"email": email, "new_user": not existing_user},
        )
    except Exception:  # noqa: BLE001
        pass

    user_doc = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    # Use user_profiles as the authoritative source for onboarding_completed
    # so that admin resets (which write to user_profiles) are reflected at login.
    profile = await db.user_profiles.find_one({"user_id": user_id}, {"_id": 0}) or {}
    user_doc["onboarding_completed"] = bool(profile.get("onboarding_completed", False))
    # Also return the session token in the body so the mobile app can send it as
    # `Authorization: Bearer` — Android WebViews don't reliably keep the cross-site
    # session cookie. get_current_user already accepts this header.
    user_doc["session_token"] = session_token
    return user_doc


@router.post("/auth/firebase")
async def firebase_auth(request: Request, response: Response):
    """Exchange a Firebase ID token (email/password beta login) for a session.

    Mirrors /auth/google exactly — same whitelist gate, user upsert, session
    cookie + Bearer token — only the token verification differs. Used by the
    Android beta build so testers can sign in with email/password instead of
    Google OAuth. Testers' emails must still be whitelisted, like Google users.
    """
    from services import firebase_auth as fb

    if not fb.is_configured():
        raise SystemException("Firebase auth not configured", code="SYS-003")

    body = await request.json()
    id_token = (body.get("id_token") or body.get("credential") or "").strip()
    if not id_token:
        raise ValidationException("Firebase id_token required", code="VAL-002")

    try:
        decoded = fb.verify_id_token(id_token)
    except (AuthenticationException, ValidationException):
        raise
    except Exception as e:
        logger.error("Firebase token verification failed: %s", type(e).__name__)
        raise AuthenticationException("Failed to verify Firebase token", code="AUTH-003", cause=e)

    email = (decoded.get("email") or "").strip().lower()
    name = decoded.get("name") or (email.split("@")[0] if email else "")
    picture = decoded.get("picture", "")
    if not email:
        raise AuthenticationException("No email in Firebase token", code="AUTH-003")

    # Whitelist Check — identical gate to /auth/google.
    whitelist_entry = await check_whitelist(email)
    if not whitelist_entry:
        logger.warning("Access denied — email not whitelisted: %s", mask_email(email))
        raise AuthorizationException(
            "Access is currently restricted. Your email is not on the invite list. Please request an invite from the admin.",
            code="AUTHZ-001",
        )

    await db.whitelisted_users.update_one(
        {"email": email},
        {"$set": {"status": "active", "registered_at": datetime.now(timezone.utc).isoformat()}},
    )
    is_admin = whitelist_entry.get("is_admin", False)

    existing_user = await db.users.find_one({"email": email}, {"_id": 0})
    if existing_user:
        user_id = existing_user["user_id"]
        await db.users.update_one({"email": email}, {"$set": {"name": name, "picture": picture, "is_admin": is_admin}})
    else:
        user_id = f"user_{uuid.uuid4().hex[:12]}"
        await db.users.insert_one({
            "user_id": user_id,
            "email": email,
            "name": name,
            "picture": picture,
            "is_admin": is_admin,
            "auth_provider": "firebase",
            "created_at": datetime.now(timezone.utc).isoformat()
        })

    session_token = str(uuid.uuid4())
    await db.user_sessions.insert_one({
        "user_id": user_id,
        "session_token": session_token,
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
        "created_at": datetime.now(timezone.utc).isoformat()
    })
    response.set_cookie(
        key="session_token",
        value=session_token,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        path="/",
        max_age=7 * 24 * 3600
    )

    try:
        from services import audit
        await audit.record(
            user_id=user_id, action="login",
            ip=request.client.host if request.client else "",
            ua=request.headers.get("user-agent", ""),
            details={"email": email, "new_user": not existing_user, "provider": "firebase"},
        )
    except Exception:  # noqa: BLE001
        pass

    user_doc = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    profile = await db.user_profiles.find_one({"user_id": user_id}, {"_id": 0}) or {}
    user_doc["onboarding_completed"] = bool(profile.get("onboarding_completed", False))
    # Mobile WebViews don't reliably keep the cross-site session cookie — return
    # the token so the client can send it as Authorization: Bearer (same as Google).
    user_doc["session_token"] = session_token
    return user_doc


@router.post("/auth/session")
async def exchange_session(request: Request, response: Response):
    """Legacy session exchange — removed."""
    raise ValidationException("Emergent auth removed. Use Google OAuth via /api/auth/google", code="VAL-001")


@router.get("/auth/me")
async def get_me(request: Request):
    user = await get_current_user(request)
    # Mirror the login handlers (/auth/google, /auth/gmail-session): user_profiles
    # is the authoritative source for onboarding_completed. Without this, the
    # field is absent for users whose flag lives only in user_profiles (e.g.
    # admin-invited accounts), which fails the frontend UserProfileC contract and
    # wedges useMe() in a permanent error → RequireAuth remount loop.
    profile = await db.user_profiles.find_one({"user_id": user["user_id"]}, {"_id": 0}) or {}
    user["onboarding_completed"] = bool(profile.get("onboarding_completed", False))
    # workspace_type drives the advisor-vs-investor primary navigation on the
    # client. Resolved for the *session owner* (the logged-in account), NOT the
    # effective user — so it stays "ADVISORY" for an advisor whether or not they
    # are currently impersonating a client. The client distinguishes "advisor at
    # root" from "advisor inside a client" via active_profile_id (below). Keying
    # this off the effective user used to make it go null during impersonation,
    # which left the nav flipping on a stale /auth/me cache.
    session_owner_id = user.get("_session_user_id") or user["user_id"]
    ws = await db.workspaces.find_one(
        {"owner_user_id": session_owner_id}, {"_id": 0, "type": 1},
    )
    user["workspace_type"] = (ws or {}).get("type")
    # Surface the session's active impersonation so the client can reconcile its
    # (localStorage-persisted) impersonation state with backend truth. Without
    # this, a persisted "Viewing <client>" banner can outlive the server session
    # (e.g. after re-login) and show a phantom client view while the backend is
    # actually at the advisor root.
    user["active_profile_id"] = user.get("_active_profile_id")
    return user


@router.post("/auth/logout")
async def logout(request: Request, response: Response):
    session_token = request.cookies.get("session_token")
    uid = None
    if session_token:
        sess = await db.user_sessions.find_one({"session_token": session_token}, {"_id": 0, "user_id": 1})
        uid = (sess or {}).get("user_id")
        await db.user_sessions.delete_many({"session_token": session_token})
    response.delete_cookie(key="session_token", path="/", samesite=COOKIE_SAMESITE, secure=COOKIE_SECURE)
    if uid:
        try:
            from services import audit
            await audit.record(
                user_id=uid, action="logout",
                ip=request.client.host if request.client else "",
                ua=request.headers.get("user-agent", ""),
            )
        except Exception:  # noqa: BLE001
            pass
    return {"message": "Logged out"}


@router.get("/auth/google-client-id")
async def get_google_client_id():
    """Return the Google OAuth client ID for the frontend."""
    if not GOOGLE_CLIENT_ID:
        raise SystemException("Google OAuth not configured", code="SYS-003")
    return {"client_id": GOOGLE_CLIENT_ID}

@router.post("/auth/gmail-session")
async def exchange_gmail_session(request: Request, response: Response):
    """Exchange a short-lived gmail_code (set by the OAuth callback) for a
    real session cookie. Called by the frontend immediately after landing
    back from Gmail OAuth — avoids relying on cross-site cookie survival."""
    body = await request.json()
    code = (body.get("code") or "").strip()
    if not code:
        raise ValidationException("code required", code="VAL-002")

    doc = await db.gmail_success_codes.find_one({"code": code}, {"_id": 0})
    if not doc:
        raise AuthenticationException("Invalid or expired gmail code", code="AUTH-003")

    expires_at = doc.get("expires_at", "")
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) > expires_at:
        await db.gmail_success_codes.delete_one({"code": code})
        raise AuthenticationException("Gmail code expired", code="AUTH-002")

    await db.gmail_success_codes.delete_one({"code": code})

    user_id = doc["user_id"]
    session_token = str(uuid.uuid4())
    await db.user_sessions.insert_one({
        "user_id": user_id,
        "session_token": session_token,
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    response.set_cookie(
        key="session_token", value=session_token,
        httponly=True, secure=COOKIE_SECURE, samesite=COOKIE_SAMESITE,
        path="/", max_age=7 * 24 * 3600,
    )
    user = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    profile = await db.user_profiles.find_one({"user_id": user_id}, {"_id": 0}) or {}
    user["onboarding_completed"] = bool(profile.get("onboarding_completed", False))
    return user


@router.get("/auth/gmail-exchange")
async def gmail_exchange(code: str, return_to: str = "/v2/app"):
    """Exchange a short-lived gmail_code for a session cookie via a same-origin
    GET redirect.

    The Gmail OAuth callback now redirects HERE (same origin as the app) rather
    than directly to the frontend with the code in the URL. This endpoint:
      1. Looks up and validates the code
      2. Creates a session and sets the cookie on THIS response
      3. Redirects to `return_to?gmail=connected`

    Because the Set-Cookie is on a same-origin niveshcopilot.com response (not
    on the cross-site OAuth redirect from Google), browsers and Cloudflare
    accept it reliably — solving the "goes to login page" bug without requiring
    frontend changes.
    """
    # Guard against open-redirect: only relative paths allowed.
    if not return_to.startswith("/") or "://" in return_to:
        return_to = "/v2/app"

    doc = await db.gmail_success_codes.find_one({"code": code}, {"_id": 0})
    if not doc:
        return _RedirectResponse(url=f"{return_to}?gmail_error=invalid_code", status_code=302)

    expires_at = doc.get("expires_at", "")
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) > expires_at:
        await db.gmail_success_codes.delete_one({"code": code})
        return _RedirectResponse(url=f"{return_to}?gmail_error=code_expired", status_code=302)

    await db.gmail_success_codes.delete_one({"code": code})

    user_id = doc["user_id"]
    session_token = str(uuid.uuid4())
    await db.user_sessions.insert_one({
        "user_id": user_id,
        "session_token": session_token,
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    })

    target = f"{return_to}?gmail=connected"
    redirect_resp = _RedirectResponse(url=target, status_code=302)
    redirect_resp.set_cookie(
        key="session_token",
        value=session_token,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        path="/",
        max_age=7 * 24 * 3600,
    )
    return redirect_resp


@router.get("/auth/dev-set-cookie")
async def dev_set_cookie(token: str, response: Response):
    """Dev-only: set a pre-created session cookie directly (screenshot helper)."""
    sess = await db.user_sessions.find_one({"session_token": token}, {"_id": 0, "user_id": 1})
    if not sess:
        raise ResourceNotFoundException("Session not found", code="RES-001")
    response.set_cookie(
        key="session_token", value=token,
        httponly=True, secure=True, samesite="none", path="/", max_age=7 * 24 * 3600,
    )
    return {"ok": True, "user_id": sess["user_id"]}
