"""Shared dependencies: DB, repos, config, auth helpers."""
from motor.motor_asyncio import AsyncIOMotorClient
from fastapi import HTTPException, Request
from datetime import datetime, timezone
import os
import logging

from repository import UserRepository, SessionRepository, PortfolioRepository, HoldingRepository
from services.ai_engine import AIEngine

logger = logging.getLogger(__name__)

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Config
EMERGENT_LLM_KEY = os.environ.get('EMERGENT_LLM_KEY', '')
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')
GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID', '')
GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET', '')
GMAIL_REDIRECT_URI = os.environ.get("GMAIL_REDIRECT_URI", "")
ADMIN_EMAIL = "priyankamantri@gmail.com"
# Co-admin / founder accounts that should always be seeded on a fresh
# deploy, irrespective of which Mongo we land on. Both lands as
# `is_admin=True` on whitelisted_users so they can sign in via Google
# OAuth on first boot of a clean cluster.
SEED_FOUNDER_EMAILS = ["priyankamantri@gmail.com", "aporwal107@gmail.com"]

# Repos & services
user_repo = UserRepository(db)
session_repo = SessionRepository(db)
portfolio_repo = PortfolioRepository(db)
holding_repo = HoldingRepository(db)
ai_engine = AIEngine(OPENAI_API_KEY)


async def get_current_user(request: Request) -> dict:
    session_token = request.cookies.get("session_token")
    if not session_token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            session_token = auth_header.split(" ")[1]
    if not session_token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    session_doc = await db.user_sessions.find_one({"session_token": session_token}, {"_id": 0})
    if not session_doc:
        raise HTTPException(status_code=401, detail="Invalid session")

    expires_at = session_doc["expires_at"]
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="Session expired")

    # ── MFD profile impersonation ──────────────────────────────────────
    # If the session has an active_profile_id (set via the MFD dashboard
    # "Open client" action), resolve the effective user_id to the profile's
    # shadow user. The entire existing engine (portfolio/insights/goals/V3)
    # then runs against that client's data without needing any route-level
    # changes. See services/mfd_workspace.py for details.
    effective_user_id = session_doc["user_id"]
    if session_doc.get("active_profile_id"):
        try:
            from services import mfd_workspace
            effective_user_id = await mfd_workspace.resolve_effective_user(session_doc)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"profile impersonation failed, falling back: {e}")

    user_doc = await db.users.find_one({"user_id": effective_user_id}, {"_id": 0})
    if not user_doc:
        raise HTTPException(status_code=401, detail="User not found")
    # Expose the real (logged-in) user_id and active-profile metadata so
    # MFD-specific routes can enforce workspace ownership.
    user_doc["_session_user_id"] = session_doc["user_id"]
    user_doc["_active_profile_id"] = session_doc.get("active_profile_id")
    return user_doc


async def require_admin(request: Request) -> dict:
    """Get current user and verify they are an admin."""
    user = await get_current_user(request)
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


async def check_whitelist(email: str) -> dict:
    """Check if email is in the whitelist. Returns the whitelist doc or None."""
    normalized = email.strip().lower()
    return await db.whitelisted_users.find_one({"email": normalized}, {"_id": 0})


async def seed_admin_and_whitelist():
    """Ensure every founder email is whitelisted, marked as admin, AND
    has a `users` + `user_profiles` row with onboarding pre-completed —
    so that on a fresh prod Mongo, the first OAuth sign-in lands the
    user directly on a clean dashboard (no onboarding flow). Idempotent;
    re-running is a no-op when rows already exist with the right flags.
    """
    import uuid as _uuid
    now = datetime.now(timezone.utc).isoformat()
    for raw in SEED_FOUNDER_EMAILS:
        email = raw.strip().lower()

        # 1. whitelisted_users — must exist with is_admin=True
        existing_wl = await db.whitelisted_users.find_one({"email": email})
        if not existing_wl:
            await db.whitelisted_users.insert_one({
                "email": email, "status": "invited", "is_admin": True,
                "invited_at": now, "registered_at": None, "invited_by": "system",
            })
            logger.info(f"Seeded founder whitelist: {email}")
        elif not existing_wl.get("is_admin"):
            await db.whitelisted_users.update_one({"email": email}, {"$set": {"is_admin": True}})

        # 2. users — pre-seed so OAuth picks up an existing row and
        #    preserves the onboarding-skipped state.
        existing_user = await db.users.find_one({"email": email}, {"_id": 0, "user_id": 1})
        if not existing_user:
            user_id = f"user_{_uuid.uuid4().hex[:12]}"
            await db.users.insert_one({
                "user_id": user_id,
                "email": email,
                "email_norm": email,
                "name": email.split("@")[0],          # placeholder; OAuth will fill on sign-in
                "is_admin": True,
                "onboarding_completed": True,         # founders skip onboarding
                "created_at": now,
                "updated_at": now,
            })
            logger.info(f"Seeded founder user: {email} ({user_id})")
        else:
            user_id = existing_user["user_id"]
            await db.users.update_one(
                {"email": email},
                {"$set": {"is_admin": True, "onboarding_completed": True, "updated_at": now}},
            )

        # 3. user_profiles — same pre-seeding so dashboard treats them
        #    as fully-onboarded immediately.
        await db.user_profiles.update_one(
            {"user_id": user_id},
            {"$setOnInsert": {
                "user_id": user_id,
                "created_at": now,
                "journey_type": None,
                "risk_profile": None,
                "goals": [],
                "playbook": None,
                "selected_sources": [],
            },
             "$set": {"onboarding_completed": True, "updated_at": now}},
            upsert=True,
        )

    await db.whitelisted_users.create_index("email", unique=True)
