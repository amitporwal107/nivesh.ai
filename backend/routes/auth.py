"""Auth routes: Google OAuth, session management."""
from fastapi import APIRouter, HTTPException, Request, Response
from datetime import datetime, timezone, timedelta
import uuid
import httpx
import logging

from deps import db, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, get_current_user, check_whitelist

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


@router.post("/auth/google")
async def google_auth(request: Request, response: Response):
    """Exchange Google OAuth credential (id_token) for a session."""
    body = await request.json()
    credential = body.get("credential")
    if not credential:
        raise HTTPException(status_code=400, detail="Google credential required")

    try:
        async with httpx.AsyncClient() as http_client:
            resp = await http_client.get(
                f"https://oauth2.googleapis.com/tokeninfo?id_token={credential}"
            )
            if resp.status_code != 200:
                raise HTTPException(status_code=401, detail="Invalid Google token")

            token_data = resp.json()

            if GOOGLE_CLIENT_ID and token_data.get("aud") != GOOGLE_CLIENT_ID:
                raise HTTPException(status_code=401, detail="Token audience mismatch")

            email = token_data.get("email", "").strip().lower()
            name = token_data.get("name", "")
            picture = token_data.get("picture", "")

            if not email:
                raise HTTPException(status_code=401, detail="No email in Google token")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Google token verification failed: {e}")
        raise HTTPException(status_code=401, detail="Failed to verify Google token")

    # Whitelist Check
    whitelist_entry = await check_whitelist(email)
    if not whitelist_entry:
        logger.warning(f"Access denied for non-whitelisted email: {email}")
        raise HTTPException(
            status_code=403,
            detail="Access is currently restricted. Your email is not on the invite list. Please request an invite from the admin."
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
    response.set_cookie(
        key="session_token",
        value=session_token,
        httponly=True,
        secure=True,
        samesite="none",
        path="/",
        max_age=7 * 24 * 3600
    )

    user_doc = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    return user_doc


@router.post("/auth/session")
async def exchange_session(request: Request, response: Response):
    """Legacy session exchange — removed."""
    raise HTTPException(status_code=410, detail="Emergent auth removed. Use Google OAuth via /api/auth/google")


@router.get("/auth/me")
async def get_me(request: Request):
    user = await get_current_user(request)
    return user


@router.post("/auth/logout")
async def logout(request: Request, response: Response):
    session_token = request.cookies.get("session_token")
    if session_token:
        await db.user_sessions.delete_many({"session_token": session_token})
    response.delete_cookie(key="session_token", path="/", samesite="none", secure=True)
    return {"message": "Logged out"}


@router.get("/auth/google-client-id")
async def get_google_client_id():
    """Return the Google OAuth client ID for the frontend."""
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=500, detail="Google OAuth not configured")
    return {"client_id": GOOGLE_CLIENT_ID}
