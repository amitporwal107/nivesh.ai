"""Auth routes: Google OAuth, session management."""
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse as _RedirectResponse
from datetime import datetime, timezone, timedelta
import urllib.parse
import uuid
import hmac
import httpx
import logging

from deps import db, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, get_current_user, check_whitelist, COOKIE_SECURE, COOKIE_SAMESITE
from helpers import secrets
from helpers.otp import generate_otp, hash_otp
from services import email_service
from core.logging_config import mask_email
from core.exceptions import (
    AuthenticationException, AuthorizationException, ValidationException,
    ResourceNotFoundException, SystemException,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

_DEFAULT_SESSION_DAYS = 7
_LONG_SESSION_DAYS = 3650  # ~10y — effectively non-expiring


async def _session_days(user_id: str) -> int:
    """Session lifetime in days. Founder/admin accounts on NON-production get an
    effectively non-expiring session (frictionless staging dev/verify); everyone
    else — and ALL of production — keeps the standard 7-day window."""
    try:
        from helpers import secrets as _secrets
        from deps import SEED_FOUNDER_EMAILS
        if _secrets.current_env() == "production":
            return _DEFAULT_SESSION_DAYS
        u = await db.users.find_one({"user_id": user_id}, {"_id": 0, "email": 1})
        email = ((u or {}).get("email") or "").strip().lower()
        founders = {e.strip().lower() for e in SEED_FOUNDER_EMAILS}
        return _LONG_SESSION_DAYS if email in founders else _DEFAULT_SESSION_DAYS
    except Exception:  # noqa: BLE001 — never block login on this
        return _DEFAULT_SESSION_DAYS

# ── Magic-link whitelist validation ──────────────────────────────────────
# Self-serve flow behind the "or a whitelisted email" box on the login page.
# A visitor submits any valid email; if it isn't already whitelisted we email
# them a one-time validation link valid for 24h. Opening the link adds the
# address to the whitelist so they can then sign in.
MAGIC_LINK_TTL_HOURS = 24

# ── Email OTP sign-in ─────────────────────────────────────────────────────
# Passwordless login: any valid email → 6-digit code → verify → session.
# Codes are stored hashed, single-use, rate-limited, and attempt-capped.
OTP_TTL_MINUTES = 30
OTP_MAX_ATTEMPTS = 5              # wrong guesses before a code is burned
OTP_RESEND_COOLDOWN_SECONDS = 60  # min gap between two code requests for an email
OTP_MAX_PER_HOUR = 6              # code requests per email per rolling hour


def _iso_is_expired(iso_str: str) -> bool:
    """True if the given ISO-8601 timestamp is in the past (UTC). Pure helper
    so the expiry rule is unit-testable without a DB."""
    if not iso_str:
        return False
    try:
        dt = datetime.fromisoformat(iso_str)
    except ValueError:
        return True
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) > dt


def _resolve_public_base(request: Request) -> str:
    """Externally-reachable base URL for links sent in email.

    Precedence mirrors client_cas_invite._resolve_redirect_uri:
      1. PUBLIC_APP_URL secret/env override
      2. X-Forwarded-Host (public hostname set by ingress) + proto
      3. request.base_url (cluster-internal — local dev only)
    """
    override = secrets.get("PUBLIC_APP_URL")
    if override:
        return override.rstrip("/")
    fwd_host = request.headers.get("x-forwarded-host") or request.headers.get("host")
    fwd_proto = request.headers.get("x-forwarded-proto", "https")
    if fwd_host:
        return f"{fwd_proto}://{fwd_host}"
    return str(request.base_url).rstrip("/")


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
    _days = await _session_days(user_id)
    await db.user_sessions.insert_one({
        "user_id": user_id,
        "session_token": session_token,
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=_days)).isoformat(),
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
    _days = await _session_days(user_id)
    await db.user_sessions.insert_one({
        "user_id": user_id,
        "session_token": session_token,
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=_days)).isoformat(),
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
    _days = await _session_days(user_id)
    await db.user_sessions.insert_one({
        "user_id": user_id,
        "session_token": session_token,
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=_days)).isoformat(),
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


@router.post("/auth/magic-link")
async def request_magic_link(request: Request):
    """Self-serve whitelist request.

    Body: {"email": "..."}.
      * Already whitelisted  → no-op, friendly message (we "ignore" it).
      * Not whitelisted      → create a 24h one-time token + email a
                               validation link. The address is NOT added to
                               the whitelist until the link is opened.
    """
    body = await request.json()
    email = (body.get("email") or "").strip().lower()

    # Format gate only — any valid email may self-serve a magic link. The
    # address is not whitelisted until the emailed link is actually opened.
    if not email or "@" not in email or "." not in email.split("@")[-1]:
        raise ValidationException("A valid email address is required", code="VAL-003")

    # Already on the list → ignore (do not re-add, do not send a link).
    if await check_whitelist(email):
        logger.info("Magic-link requested for already-whitelisted email: %s", mask_email(email))
        return {
            "message": "This email is already approved — you can sign in above.",
            "already_whitelisted": True,
        }

    # Fail loud if we can't actually send mail — never pretend a link went out.
    if not email_service.is_configured():
        logger.error("Magic-link requested but SMTP is not configured")
        raise SystemException(
            "Email delivery is not configured on the server. Please contact the admin.",
            code="SYS-003",
        )

    token = uuid.uuid4().hex
    now = datetime.now(timezone.utc)
    await db.magic_link_tokens.insert_one({
        "token": token,
        "email": email,
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=MAGIC_LINK_TTL_HOURS)).isoformat(),
        "used": False,
        "used_at": None,
    })

    base = _resolve_public_base(request)
    validation_url = f"{base}/api/auth/magic-link/validate?token={token}"

    try:
        await email_service.send_validation_email(email, validation_url, MAGIC_LINK_TTL_HOURS)
    except Exception as e:  # noqa: BLE001
        # Drop the just-created token so a failed send can't leave a usable
        # link the user never received, and surface the real failure.
        await db.magic_link_tokens.delete_one({"token": token})
        logger.error("Failed to send magic-link email: %s", type(e).__name__)
        raise SystemException(
            "We couldn't send the validation email right now. Please try again later.",
            code="SYS-003", cause=e,
        )

    return {
        "message": f"Validation link sent to {email}. It expires in {MAGIC_LINK_TTL_HOURS} hours.",
        "already_whitelisted": False,
    }


async def _issue_email_session(request: Request, response: Response, email: str) -> dict:
    """Whitelist the address (self-serve), create/find the user, mint a 7-day
    session, set the cookie, and return the user doc. Mirrors the tail of
    google_auth so an OTP sign-in lands on the dashboard exactly like Google."""
    now = datetime.now(timezone.utc)

    # Self-serve whitelist: a verified OTP proves control of the address, so we
    # add it (idempotent). Set invite-only posture by requiring an existing
    # whitelist entry here instead.
    whitelist_entry = await check_whitelist(email)
    if not whitelist_entry:
        await db.whitelisted_users.update_one(
            {"email": email},
            {"$set": {"email": email, "status": "active",
                      "registered_at": now.isoformat(), "source": "otp"}},
            upsert=True,
        )
        whitelist_entry = await check_whitelist(email) or {}
    is_admin = whitelist_entry.get("is_admin", False)

    existing_user = await db.users.find_one({"email": email}, {"_id": 0})
    if existing_user:
        user_id = existing_user["user_id"]
        await db.users.update_one({"email": email}, {"$set": {"is_admin": is_admin}})
    else:
        user_id = f"user_{uuid.uuid4().hex[:12]}"
        await db.users.insert_one({
            "user_id": user_id, "email": email, "name": "", "picture": "",
            "is_admin": is_admin, "created_at": now.isoformat(),
        })

    session_token = str(uuid.uuid4())
    _days = await _session_days(user_id)
    await db.user_sessions.insert_one({
        "user_id": user_id, "session_token": session_token,
        "expires_at": (now + timedelta(days=_days)).isoformat(),
        "created_at": now.isoformat(),
    })
    response.set_cookie(
        key="session_token", value=session_token, httponly=True,
        secure=COOKIE_SECURE, samesite=COOKIE_SAMESITE, path="/",
        max_age=7 * 24 * 3600,
    )

    try:
        from services import audit
        await audit.record(
            user_id=user_id, action="login",
            ip=request.client.host if request.client else "",
            ua=request.headers.get("user-agent", ""),
            details={"email": email, "new_user": not existing_user, "method": "otp"},
        )
    except Exception:  # noqa: BLE001
        pass

    user_doc = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    profile = await db.user_profiles.find_one({"user_id": user_id}, {"_id": 0}) or {}
    user_doc["onboarding_completed"] = bool(profile.get("onboarding_completed", False))
    user_doc["session_token"] = session_token
    return user_doc


@router.post("/auth/otp/request")
async def request_otp(request: Request):
    """Send a 6-digit sign-in code to any valid email (self-serve).

    Body: {"email": "..."}. Rate-limited per email. Requires SMTP to be
    configured — we never pretend a code went out.
    """
    body = await request.json()
    email = (body.get("email") or "").strip().lower()
    if not email or "@" not in email or "." not in email.split("@")[-1]:
        raise ValidationException("A valid email address is required", code="VAL-003")

    # Fail loud if we can't actually send mail — never pretend a code went out.
    if not email_service.is_configured():
        logger.error("OTP requested but SMTP is not configured")
        raise SystemException(
            "Email delivery is not configured on the server. Please contact the admin.",
            code="SYS-003",
        )

    now = datetime.now(timezone.utc)
    # Rate limit: resend cooldown + hourly cap per email (anti email-bombing).
    window_start = (now - timedelta(hours=1)).isoformat()
    recent = await db.email_otp_codes.find(
        {"email": email, "created_at": {"$gte": window_start}}
    ).to_list(50)
    if recent:
        latest = max(recent, key=lambda d: d.get("created_at", ""))
        secs = (now - datetime.fromisoformat(latest["created_at"])).total_seconds()
        if secs < OTP_RESEND_COOLDOWN_SECONDS:
            raise ValidationException(
                "Please wait a moment before requesting another code.", code="VAL-003")
        if len(recent) >= OTP_MAX_PER_HOUR:
            raise ValidationException(
                "Too many codes requested. Please try again later.", code="VAL-003")

    # Invalidate any earlier live codes so only the newest one works.
    await db.email_otp_codes.update_many(
        {"email": email, "used": False},
        {"$set": {"used": True, "used_at": now.isoformat()}},
    )

    code = generate_otp()
    result = await db.email_otp_codes.insert_one({
        "email": email,
        "code_hash": hash_otp(email, code),
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=OTP_TTL_MINUTES)).isoformat(),
        "attempts": 0,
        "used": False,
        "used_at": None,
        "request_ip": request.client.host if request.client else "",
    })

    try:
        await email_service.send_otp_email(email, code, OTP_TTL_MINUTES)
    except Exception as e:  # noqa: BLE001
        # Drop the just-created code so a failed send can't leave a live code
        # the user never received, and surface the real failure.
        await db.email_otp_codes.delete_one({"_id": result.inserted_id})
        logger.error("Failed to send OTP email: %s", type(e).__name__)
        raise SystemException(
            "We couldn't send the code right now. Please try again later.",
            code="SYS-003", cause=e,
        )

    return {
        "message": f"A 6-digit code was sent to {email}. It expires in {OTP_TTL_MINUTES} minutes.",
        "expires_in_minutes": OTP_TTL_MINUTES,
    }


@router.post("/auth/otp/verify")
async def verify_otp(request: Request, response: Response):
    """Verify a 6-digit code and sign the user in (sets the session cookie)."""
    body = await request.json()
    email = (body.get("email") or "").strip().lower()
    code = (body.get("code") or "").strip()
    if not email or not code:
        raise ValidationException("Email and code are required", code="VAL-003")

    now = datetime.now(timezone.utc)
    doc = await db.email_otp_codes.find_one(
        {"email": email, "used": False}, sort=[("created_at", -1)]
    )
    if not doc:
        raise ValidationException(
            "No active code for this email. Request a new one.", code="VAL-003")

    if _iso_is_expired(doc.get("expires_at", "")):
        await db.email_otp_codes.update_one(
            {"_id": doc["_id"]}, {"$set": {"used": True, "used_at": now.isoformat()}})
        raise ValidationException("This code has expired. Request a new one.", code="VAL-003")

    if doc.get("attempts", 0) >= OTP_MAX_ATTEMPTS:
        await db.email_otp_codes.update_one(
            {"_id": doc["_id"]}, {"$set": {"used": True, "used_at": now.isoformat()}})
        raise ValidationException(
            "Too many incorrect attempts. Request a new code.", code="VAL-003")

    if not hmac.compare_digest(doc.get("code_hash", ""), hash_otp(email, code)):
        await db.email_otp_codes.update_one({"_id": doc["_id"]}, {"$inc": {"attempts": 1}})
        raise ValidationException("Incorrect code. Please try again.", code="VAL-003")

    # Correct — consume the code (single-use) and issue the session.
    await db.email_otp_codes.update_one(
        {"_id": doc["_id"]}, {"$set": {"used": True, "used_at": now.isoformat()}})
    return await _issue_email_session(request, response, email)


@router.get("/auth/magic-link/validate")
async def validate_magic_link(token: str):
    """Open a magic-link validation token. On success the email is added to
    the whitelist and the user is bounced to /login to sign in. All outcomes
    redirect to the login page with a status query param so the SPA can show
    an appropriate message."""
    doc = await db.magic_link_tokens.find_one({"token": token}, {"_id": 0})
    if not doc:
        return _RedirectResponse(url="/login?magic_error=invalid", status_code=302)

    if doc.get("used"):
        return _RedirectResponse(url="/login?magic_error=used", status_code=302)

    if _iso_is_expired(doc.get("expires_at", "")):
        # Expire it: a stale token is removed so it can never be reused.
        await db.magic_link_tokens.delete_one({"token": token})
        return _RedirectResponse(url="/login?magic_error=expired", status_code=302)

    email = doc["email"]
    # Add to the whitelist — idempotent, so a double-click can't error out and
    # an already-whitelisted address is left untouched.
    await db.whitelisted_users.update_one(
        {"email": email},
        {"$setOnInsert": {
            "email": email,
            "status": "invited",
            "is_admin": False,
            "invited_at": datetime.now(timezone.utc).isoformat(),
            "registered_at": None,
            "invited_by": "magic-link",
        }},
        upsert=True,
    )
    # Burn the token (single use).
    await db.magic_link_tokens.update_one(
        {"token": token},
        {"$set": {"used": True, "used_at": datetime.now(timezone.utc).isoformat()}},
    )
    logger.info("Magic-link validated, email added to whitelist: %s", mask_email(email))
    return _RedirectResponse(url="/login?validated=1", status_code=302)


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
