from fastapi import FastAPI, APIRouter, HTTPException, Request, Response, UploadFile, File, BackgroundTasks
from fastapi.responses import JSONResponse, RedirectResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
import uuid
import httpx
import json
import io
import csv
import asyncio
from pathlib import Path
from typing import List, Optional
from datetime import datetime, timezone, timedelta

# Local modules
from models import PortfolioCreate, HoldingCreate, HoldingUpdate, ChatMessageInput, AssetType, JourneyInput, RiskProfileInput, QuickSetupInput
from repository import UserRepository, SessionRepository, PortfolioRepository, HoldingRepository
from services import compute_health_score, compute_risk_analysis, generate_recommendations, simulate_optimized_portfolio
from services.ai_engine import AIEngine
from services.amfi_nav import fetch_nav_data, update_holdings_nav, lookup_nav
from services.fund_performance import compute_benchmark_ratings
from services.live_price import fetch_live_prices
from services.sgb_prices import apply_sgb_issue_prices
from services.gmail_service import (
    get_authorization_url, exchange_code_for_tokens,
    get_gmail_credentials, build_gmail_service,
    scan_for_cas_emails, download_attachment,
)
from middleware import RateLimitMiddleware, validate_env

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# Ensure poppler-utils is installed (needed for image-based CAS PDFs)
import subprocess
try:
    subprocess.run(["which", "pdftoppm"], check=True, capture_output=True)
except subprocess.CalledProcessError:
    subprocess.run(["apt-get", "update", "-qq"], capture_output=True)
    subprocess.run(["apt-get", "install", "-y", "poppler-utils"], capture_output=True)

# Validate env on startup
validate_env()

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# LLM Key
EMERGENT_LLM_KEY = os.environ.get('EMERGENT_LLM_KEY', '')
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')

# Google OAuth
GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID', '')
GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET', '')

# Admin email — seeded on startup
ADMIN_EMAIL = "priyankamantri@gmail.com"

# Initialize layers
user_repo = UserRepository(db)
session_repo = SessionRepository(db)
portfolio_repo = PortfolioRepository(db)
holding_repo = HoldingRepository(db)
ai_engine = AIEngine(OPENAI_API_KEY)

app = FastAPI(title="nivesh.ai API", version="2.0")
api_router = APIRouter(prefix="/api")

# Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ==================== AUTH HELPERS ====================

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
    
    user_doc = await db.users.find_one({"user_id": session_doc["user_id"]}, {"_id": 0})
    if not user_doc:
        raise HTTPException(status_code=401, detail="User not found")
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
    """Ensure admin email is whitelisted and marked as admin on startup."""
    email = ADMIN_EMAIL.strip().lower()
    existing = await db.whitelisted_users.find_one({"email": email})
    if not existing:
        await db.whitelisted_users.insert_one({
            "email": email,
            "status": "invited",
            "is_admin": True,
            "invited_at": datetime.now(timezone.utc).isoformat(),
            "registered_at": None,
            "invited_by": "system",
        })
        logger.info(f"Seeded admin whitelist: {email}")
    elif not existing.get("is_admin"):
        await db.whitelisted_users.update_one({"email": email}, {"$set": {"is_admin": True}})
    # Also ensure indexes
    await db.whitelisted_users.create_index("email", unique=True)


# ==================== AUTH ROUTES ====================

@api_router.post("/auth/google")
async def google_auth(request: Request, response: Response):
    """Exchange Google OAuth credential (id_token) for a session.
    Checks whitelist before allowing access."""
    body = await request.json()
    credential = body.get("credential")
    if not credential:
        raise HTTPException(status_code=400, detail="Google credential required")

    # Verify the Google ID token
    try:
        async with httpx.AsyncClient() as http_client:
            # Verify token with Google's tokeninfo endpoint
            resp = await http_client.get(
                f"https://oauth2.googleapis.com/tokeninfo?id_token={credential}"
            )
            if resp.status_code != 200:
                raise HTTPException(status_code=401, detail="Invalid Google token")
            
            token_data = resp.json()
            
            # Verify the audience matches our client ID
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

    # ── Whitelist Check ──
    whitelist_entry = await check_whitelist(email)
    if not whitelist_entry:
        logger.warning(f"Access denied for non-whitelisted email: {email}")
        raise HTTPException(
            status_code=403,
            detail="Access is currently restricted. Your email is not on the invite list. Please request an invite from the admin."
        )

    # Update whitelist status
    update_fields = {"status": "active", "registered_at": datetime.now(timezone.utc).isoformat()}
    await db.whitelisted_users.update_one({"email": email}, {"$set": update_fields})

    is_admin = whitelist_entry.get("is_admin", False)

    # Create or update user
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

    # Create session
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


@api_router.post("/auth/session")
async def exchange_session(request: Request, response: Response):
    """Legacy session exchange — redirect to Google auth."""
    raise HTTPException(status_code=410, detail="Emergent auth removed. Use Google OAuth via /api/auth/google")


@api_router.get("/auth/me")
async def get_me(request: Request):
    user = await get_current_user(request)
    return user

@api_router.post("/auth/logout")
async def logout(request: Request, response: Response):
    session_token = request.cookies.get("session_token")
    if session_token:
        await db.user_sessions.delete_many({"session_token": session_token})
    response.delete_cookie(key="session_token", path="/", samesite="none", secure=True)
    return {"message": "Logged out"}

@api_router.get("/auth/google-client-id")
async def get_google_client_id():
    """Return the Google OAuth client ID for the frontend."""
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=500, detail="Google OAuth not configured")
    return {"client_id": GOOGLE_CLIENT_ID}


# ==================== WHITELIST / ADMIN ROUTES ====================

@api_router.get("/admin/whitelist")
async def list_whitelist(request: Request):
    """List all whitelisted users. Admin only."""
    await require_admin(request)
    entries = await db.whitelisted_users.find({}, {"_id": 0}).sort("invited_at", -1).to_list(1000)
    # Enrich with user registration info
    for entry in entries:
        user = await db.users.find_one({"email": entry["email"]}, {"_id": 0})
        entry["user_name"] = user.get("name", "") if user else ""
        entry["user_picture"] = user.get("picture", "") if user else ""
    return entries


@api_router.post("/admin/whitelist/add")
async def add_to_whitelist(request: Request):
    """Add a single email to the whitelist. Admin only."""
    admin = await require_admin(request)
    body = await request.json()
    email = body.get("email", "").strip().lower()
    is_admin = body.get("is_admin", False)

    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Valid email required")

    existing = await db.whitelisted_users.find_one({"email": email})
    if existing:
        raise HTTPException(status_code=409, detail=f"{email} is already whitelisted")

    await db.whitelisted_users.insert_one({
        "email": email,
        "status": "invited",
        "is_admin": is_admin,
        "invited_at": datetime.now(timezone.utc).isoformat(),
        "registered_at": None,
        "invited_by": admin.get("email", "admin"),
    })

    return {"message": f"{email} added to whitelist", "email": email}


@api_router.post("/admin/whitelist/bulk-upload")
async def bulk_upload_whitelist(request: Request):
    """Bulk upload emails via CSV. Admin only.
    Expects JSON body with 'emails' array."""
    admin = await require_admin(request)
    body = await request.json()
    emails = body.get("emails", [])

    if not emails:
        raise HTTPException(status_code=400, detail="No emails provided")

    added = 0
    skipped = 0
    errors = []
    for raw_email in emails:
        email = raw_email.strip().lower()
        if not email or "@" not in email:
            errors.append(f"Invalid: {raw_email}")
            continue
        existing = await db.whitelisted_users.find_one({"email": email})
        if existing:
            skipped += 1
            continue
        await db.whitelisted_users.insert_one({
            "email": email,
            "status": "invited",
            "is_admin": False,
            "invited_at": datetime.now(timezone.utc).isoformat(),
            "registered_at": None,
            "invited_by": admin.get("email", "admin"),
        })
        added += 1

    return {"added": added, "skipped": skipped, "errors": errors, "total": len(emails)}


@api_router.delete("/admin/whitelist/{email}")
async def remove_from_whitelist(request: Request, email: str):
    """Remove an email from the whitelist. Admin only. Cannot remove self."""
    admin = await require_admin(request)
    email = email.strip().lower()

    if email == admin.get("email", "").lower():
        raise HTTPException(status_code=400, detail="Cannot remove yourself from the whitelist")

    result = await db.whitelisted_users.delete_one({"email": email})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Email not found in whitelist")

    # Also invalidate their sessions
    user = await db.users.find_one({"email": email}, {"_id": 0})
    if user:
        await db.user_sessions.delete_many({"user_id": user["user_id"]})

    return {"message": f"{email} removed from whitelist"}


@api_router.patch("/admin/whitelist/{email}")
async def update_whitelist_entry(request: Request, email: str):
    """Update whitelist entry (toggle admin, change status). Admin only."""
    await require_admin(request)
    body = await request.json()
    email = email.strip().lower()

    entry = await db.whitelisted_users.find_one({"email": email})
    if not entry:
        raise HTTPException(status_code=404, detail="Email not found in whitelist")

    update = {}
    if "is_admin" in body:
        update["is_admin"] = bool(body["is_admin"])
    if "status" in body and body["status"] in ("invited", "active", "blocked"):
        update["status"] = body["status"]
        # If blocking, invalidate sessions
        if body["status"] == "blocked":
            user = await db.users.find_one({"email": email}, {"_id": 0})
            if user:
                await db.user_sessions.delete_many({"user_id": user["user_id"]})

    if update:
        await db.whitelisted_users.update_one({"email": email}, {"$set": update})
        # Also update user record if admin status changed
        if "is_admin" in update:
            await db.users.update_one({"email": email}, {"$set": {"is_admin": update["is_admin"]}})

    return {"message": f"Updated {email}", "updates": update}


@api_router.get("/admin/stats")
async def get_admin_stats(request: Request):
    """Get whitelist and usage statistics. Admin only."""
    await require_admin(request)

    total_whitelisted = await db.whitelisted_users.count_documents({})
    active_users = await db.whitelisted_users.count_documents({"status": "active"})
    invited_pending = await db.whitelisted_users.count_documents({"status": "invited"})
    blocked = await db.whitelisted_users.count_documents({"status": "blocked"})
    total_users = await db.users.count_documents({})
    total_holdings = await db.holdings.count_documents({})
    total_portfolios = await db.portfolios.count_documents({})

    return {
        "whitelist": {
            "total": total_whitelisted,
            "active": active_users,
            "pending": invited_pending,
            "blocked": blocked,
            "conversion_rate": round((active_users / total_whitelisted * 100) if total_whitelisted > 0 else 0, 1),
        },
        "usage": {
            "total_users": total_users,
            "total_portfolios": total_portfolios,
            "total_holdings": total_holdings,
        },
    }

# ==================== GMAIL AUTO-FETCH ROUTES ====================

GMAIL_REDIRECT_URI = os.environ.get("GMAIL_REDIRECT_URI", "")

@api_router.get("/gmail/connect")
async def gmail_connect(request: Request):
    """Start Gmail OAuth flow — redirects user to Google consent screen."""
    user = await get_current_user(request)

    redirect_uri = GMAIL_REDIRECT_URI
    if not redirect_uri:
        # REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS, THIS BREAKS THE AUTH
        raise HTTPException(status_code=500, detail="GMAIL_REDIRECT_URI not configured")

    state = f"{user['user_id']}_{uuid.uuid4().hex[:8]}"
    await db.gmail_oauth_states.insert_one({
        "state": state,
        "user_id": user["user_id"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
    })

    url, code_verifier = get_authorization_url(GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, redirect_uri, state)

    # Store code_verifier with the state for PKCE
    await db.gmail_oauth_states.update_one(
        {"state": state},
        {"$set": {"code_verifier": code_verifier}}
    )

    return {"auth_url": url}


@api_router.get("/oauth/gmail/callback")
async def gmail_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    """Handle Gmail OAuth callback from Google."""
    if error:
        logger.error(f"Gmail OAuth error: {error}")
        return RedirectResponse(url="/dashboard?gmail_error=denied")

    if not code or not state:
        return RedirectResponse(url="/dashboard?gmail_error=missing_params")

    # Verify state
    state_doc = await db.gmail_oauth_states.find_one({"state": state}, {"_id": 0})
    if not state_doc:
        return RedirectResponse(url="/dashboard?gmail_error=invalid_state")

    # Check expiry
    expires_at = state_doc["expires_at"]
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) > expires_at:
        return RedirectResponse(url="/dashboard?gmail_error=state_expired")

    user_id = state_doc["user_id"]
    code_verifier = state_doc.get("code_verifier")
    await db.gmail_oauth_states.delete_one({"state": state})

    redirect_uri = GMAIL_REDIRECT_URI
    if not redirect_uri:
        return RedirectResponse(url="/dashboard?gmail_error=config_error")

    try:
        tokens = exchange_code_for_tokens(GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, redirect_uri, code, code_verifier=code_verifier)
    except Exception as e:
        logger.error(f"Gmail token exchange failed: {e}")
        return RedirectResponse(url="/dashboard?gmail_error=token_exchange_failed")

    # Store tokens
    await db.gmail_tokens.update_one(
        {"user_id": user_id},
        {"$set": {
            "user_id": user_id,
            **tokens,
            "connected_at": datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True,
    )

    logger.info(f"Gmail connected for user {user_id}")
    return RedirectResponse(url="/dashboard?gmail=connected")


@api_router.get("/gmail/status")
async def gmail_status(request: Request):
    """Check if user has Gmail connected, with last import info."""
    user = await get_current_user(request)
    token_doc = await db.gmail_tokens.find_one({"user_id": user["user_id"]}, {"_id": 0})
    if not token_doc:
        return {"connected": False}
    
    # Get last successful import
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
    }


@api_router.get("/gmail/history")
async def gmail_import_history(request: Request):
    """Get history of all Gmail imports for this user."""
    user = await get_current_user(request)
    imports = await db.gmail_imports.find(
        {"user_id": user["user_id"]},
        {"_id": 0}
    ).sort("imported_at", -1).to_list(50)
    return {"imports": imports}


@api_router.get("/portfolio/upload-history")
async def upload_history(request: Request):
    """Get history of all file uploads (CAS, CSV, Excel) for this user."""
    user = await get_current_user(request)
    tasks = await db.upload_tasks.find(
        {"user_id": user["user_id"]},
        {"_id": 0, "task_id": 1, "status": 1, "message": 1, "count": 1, "source": 1, "created_at": 1, "completed_at": 1}
    ).sort("created_at", -1).to_list(50)
    return {"uploads": tasks}


@api_router.post("/gmail/disconnect")
async def gmail_disconnect(request: Request):
    """Disconnect Gmail — remove stored tokens."""
    user = await get_current_user(request)
    await db.gmail_tokens.delete_one({"user_id": user["user_id"]})
    return {"message": "Gmail disconnected"}


@api_router.post("/gmail/scan")
async def gmail_scan(request: Request):
    """Scan Gmail for CAS emails. Returns list of found emails with attachment info."""
    user = await get_current_user(request)
    token_doc = await db.gmail_tokens.find_one({"user_id": user["user_id"]}, {"_id": 0})
    if not token_doc:
        raise HTTPException(status_code=400, detail="Gmail not connected. Please connect Gmail first.")

    try:
        creds = get_gmail_credentials(token_doc)
        service = build_gmail_service(creds)

        # Update stored token if refreshed
        if creds.token != token_doc["access_token"]:
            await db.gmail_tokens.update_one(
                {"user_id": user["user_id"]},
                {"$set": {
                    "access_token": creds.token,
                    "expires_at": creds.expiry.replace(tzinfo=timezone.utc).isoformat() if creds.expiry else None,
                }}
            )

        emails = scan_for_cas_emails(service, max_results=20)

        # Check which have already been imported (only if holdings still exist)
        holdings_exist = await db.holdings.count_documents({"user_id": user["user_id"]}) > 0
        imported_ids = set()
        if holdings_exist:
            existing = await db.gmail_imports.find({"user_id": user["user_id"], "status": "completed"}, {"_id": 0, "message_id": 1}).to_list(500)
            imported_ids = {e["message_id"] for e in existing}

        for email in emails:
            email["already_imported"] = email["message_id"] in imported_ids

        return {"emails": emails, "total": len(emails)}
    except Exception as e:
        logger.error(f"Gmail scan failed: {e}")
        if "invalid_grant" in str(e).lower() or "token" in str(e).lower():
            await db.gmail_tokens.delete_one({"user_id": user["user_id"]})
            raise HTTPException(status_code=401, detail="Gmail session expired. Please reconnect Gmail.")
        raise HTTPException(status_code=500, detail=f"Gmail scan failed: {str(e)}")


@api_router.post("/gmail/import")
async def gmail_import(request: Request, background_tasks: BackgroundTasks):
    """Import a specific CAS email attachment. Triggers background processing."""
    user = await get_current_user(request)
    body = await request.json()
    message_id = body.get("message_id")
    attachment_id = body.get("attachment_id")
    filename = body.get("filename", "cas.pdf")
    password = body.get("password", "")
    portfolio_id = body.get("portfolio_id", "")

    if not message_id or not attachment_id:
        raise HTTPException(status_code=400, detail="message_id and attachment_id required")

    # Check deduplication — allow re-import if holdings were cleared
    existing = await db.gmail_imports.find_one({
        "user_id": user["user_id"],
        "message_id": message_id,
        "attachment_id": attachment_id,
    })
    if existing and existing.get("status") == "completed":
        # Check if holdings still exist — if cleared, allow re-import
        holdings_exist = await db.holdings.count_documents({"user_id": user["user_id"]})
        if holdings_exist > 0:
            raise HTTPException(status_code=409, detail="This attachment has already been imported")
        # Holdings were cleared — remove old import record to allow re-import
        await db.gmail_imports.delete_one({"_id": existing["_id"]})

    token_doc = await db.gmail_tokens.find_one({"user_id": user["user_id"]}, {"_id": 0})
    if not token_doc:
        raise HTTPException(status_code=400, detail="Gmail not connected")

    try:
        creds = get_gmail_credentials(token_doc)
        service = build_gmail_service(creds)
        content = download_attachment(service, message_id, attachment_id)
    except Exception as e:
        logger.error(f"Gmail attachment download failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to download attachment from Gmail")

    # Create task and process in background
    task_id = f"gmail_{uuid.uuid4().hex[:12]}"
    await db.upload_tasks.insert_one({
        "task_id": task_id,
        "user_id": user["user_id"],
        "status": "processing",
        "message": f"Importing {filename} from Gmail...",
        "count": 0,
        "holdings": [],
        "source": "email",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })

    # Record import attempt
    await db.gmail_imports.update_one(
        {"user_id": user["user_id"], "message_id": message_id, "attachment_id": attachment_id},
        {"$set": {
            "user_id": user["user_id"],
            "message_id": message_id,
            "attachment_id": attachment_id,
            "filename": filename,
            "task_id": task_id,
            "status": "processing",
            "imported_at": datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True,
    )

    background_tasks.add_task(
        _process_gmail_cas_background, content, user["user_id"], task_id, portfolio_id, password, message_id, attachment_id
    )

    return {"task_id": task_id, "status": "processing", "message": f"Importing {filename} from Gmail..."}


async def _process_gmail_cas_background(
    content: bytes, user_id: str, task_id: str, portfolio_id: str, password: str,
    message_id: str, attachment_id: str
):
    """Background task for Gmail CAS import."""
    try:
        await db.upload_tasks.update_one(
            {"task_id": task_id},
            {"$set": {"status": "processing", "message": "Parsing CAS PDF from Gmail with AI..."}}
        )
        parsed = await parse_cas_pdf(content, password=password)
        if not parsed:
            await db.upload_tasks.update_one(
                {"task_id": task_id},
                {"$set": {"status": "completed", "message": "No holdings found in CAS email", "count": 0}}
            )
            await db.gmail_imports.update_one(
                {"user_id": user_id, "message_id": message_id, "attachment_id": attachment_id},
                {"$set": {"status": "completed", "count": 0}}
            )
            return

        # Tag source as 'email' and add confidence
        for h in parsed:
            h["source"] = "email"
            h["confidence"] = 0.95

        await _save_holdings_with_dedup(user_id, parsed, "Gmail CAS", task_id, portfolio_id)

        # Update import record
        final_task = await db.upload_tasks.find_one({"task_id": task_id}, {"_id": 0})
        await db.gmail_imports.update_one(
            {"user_id": user_id, "message_id": message_id, "attachment_id": attachment_id},
            {"$set": {"status": "completed", "count": final_task.get("count", 0)}}
        )
    except HTTPException as he:
        error_msg = he.detail if hasattr(he, 'detail') else str(he)
        await db.upload_tasks.update_one(
            {"task_id": task_id},
            {"$set": {"status": "error", "message": error_msg}}
        )
        await db.gmail_imports.update_one(
            {"user_id": user_id, "message_id": message_id, "attachment_id": attachment_id},
            {"$set": {"status": "error"}}
        )
    except Exception as e:
        error_msg = str(e)
        if "password" in error_msg.lower() or "decrypt" in error_msg.lower():
            error_msg = "PDF is password-protected. Please provide the password."
        await db.upload_tasks.update_one(
            {"task_id": task_id},
            {"$set": {"status": "error", "message": error_msg}}
        )
        await db.gmail_imports.update_one(
            {"user_id": user_id, "message_id": message_id, "attachment_id": attachment_id},
            {"$set": {"status": "error"}}
        )


async def _save_holdings_with_dedup(user_id: str, parsed: list, source_label: str, task_id: str, portfolio_id: str):
    """Save holdings from Gmail CAS — replaces all existing holdings (latest CAS = source of truth)."""
    
    # CAS is the full snapshot — clear old holdings
    delete_query = {"user_id": user_id}
    if portfolio_id:
        delete_query["portfolio_id"] = portfolio_id
    old_count = await db.holdings.count_documents(delete_query)
    await db.holdings.delete_many(delete_query)
    logger.info(f"Gmail CAS import: cleared {old_count} old holdings for user {user_id}")

    new_count = 0
    saved_holdings = []

    for h in parsed:
        name = h.get("name", "").strip()
        isin = h.get("isin", h.get("ticker", "")).upper().strip()
        
        holding_id = f"hold_{uuid.uuid4().hex[:12]}"
        asset_type = h.get("asset_type", "mutual_fund")
        if asset_type not in ["equity", "mutual_fund", "etf", "bond", "gold", "fd", "other"]:
            asset_type = "mutual_fund" if "fund" in name.lower() else "equity"
        
        doc = {
            "holding_id": holding_id,
            "portfolio_id": portfolio_id or "",
            "user_id": user_id,
            "name": name,
            "ticker": isin,
            "asset_type": asset_type,
            "quantity": h.get("quantity", 0),
            "buy_price": h.get("buy_price", h.get("avg_price", 0)),
            "current_price": h.get("current_price", h.get("buy_price", 0)),
            "sector": h.get("sector", "Other"),
            "buy_date": h.get("buy_date", ""),
            "source": "email",
            "confidence": h.get("confidence", 0.95),
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.holdings.insert_one(doc)
        doc.pop("_id", None)
        saved_holdings.append(doc)
        new_count += 1

    msg = f"{new_count} holdings imported from {source_label}"
    if old_count > 0:
        msg += f" (replaced {old_count} previous)"

    await db.upload_tasks.update_one(
        {"task_id": task_id},
        {"$set": {"status": "completed", "message": msg, "count": new_count, "holdings": saved_holdings[:50]}}
    )
    
    # Invalidate cached analytics
    await db.fund_performance_cache.delete_many({"user_id": user_id})


# ==================== PORTFOLIO MANAGEMENT ROUTES ====================

@api_router.get("/portfolios")
async def list_portfolios(request: Request):
    user = await get_current_user(request)
    portfolios = await db.portfolios.find({"user_id": user["user_id"]}, {"_id": 0}).to_list(50)
    # Add holdings count per portfolio
    for p in portfolios:
        count = await db.holdings.count_documents({"user_id": user["user_id"], "portfolio_id": p["portfolio_id"]})
        p["holdings_count"] = count
    return portfolios

@api_router.post("/portfolios")
async def create_portfolio(request: Request, data: PortfolioCreate):
    user = await get_current_user(request)
    doc = {
        "portfolio_id": f"pf_{uuid.uuid4().hex[:12]}",
        "user_id": user["user_id"],
        "name": data.name,
        "member_name": data.member_name,
        "relationship": data.relationship,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.portfolios.insert_one(doc)
    result = await db.portfolios.find_one({"portfolio_id": doc["portfolio_id"]}, {"_id": 0})
    return result

@api_router.delete("/portfolios/{portfolio_id}")
async def delete_portfolio(request: Request, portfolio_id: str):
    user = await get_current_user(request)
    result = await db.portfolios.delete_one({"portfolio_id": portfolio_id, "user_id": user["user_id"]})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    # Cascade delete holdings
    deleted = await db.holdings.delete_many({"user_id": user["user_id"], "portfolio_id": portfolio_id})
    return {"message": f"Portfolio deleted with {deleted.deleted_count} holdings"}

# ==================== INSTRUMENT SEARCH / AUTOCOMPLETE ====================

@api_router.get("/search/instruments")
async def search_instruments(q: str = ""):
    from instruments_data import INDIAN_INSTRUMENTS
    if not q or len(q) < 2:
        return []
    q_lower = q.lower()
    results = []
    for inst in INDIAN_INSTRUMENTS:
        if q_lower in inst["name"].lower() or q_lower in inst["ticker"].lower():
            results.append(inst)
        if len(results) >= 15:
            break
    return results

# ==================== HOLDINGS ROUTES ====================

@api_router.get("/portfolio/holdings")
async def get_holdings(request: Request, portfolio_id: str = "", asset_type: str = ""):
    user = await get_current_user(request)
    query = {"user_id": user["user_id"]}
    if portfolio_id:
        query["portfolio_id"] = portfolio_id
    if asset_type:
        query["asset_type"] = asset_type
    holdings = await db.holdings.find(query, {"_id": 0}).to_list(2000)
    return holdings

@api_router.post("/portfolio/holdings")
async def add_holding(request: Request, holding: HoldingCreate):
    user = await get_current_user(request)
    holding_doc = {
        "holding_id": f"hold_{uuid.uuid4().hex[:12]}",
        "user_id": user["user_id"],
        "portfolio_id": holding.portfolio_id or "",
        "name": holding.name,
        "ticker": holding.ticker,
        "asset_type": holding.asset_type,
        "quantity": holding.quantity,
        "buy_price": holding.buy_price,
        "current_price": holding.current_price,
        "sector": holding.sector or "Other",
        "buy_date": holding.buy_date or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.holdings.insert_one(holding_doc)
    result = await db.holdings.find_one({"holding_id": holding_doc["holding_id"]}, {"_id": 0})
    return result

@api_router.put("/portfolio/holdings/{holding_id}")
async def update_holding(request: Request, holding_id: str, holding: HoldingUpdate):
    user = await get_current_user(request)
    update_data = {k: v for k, v in holding.model_dump().items() if v is not None}
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")
    await db.holdings.update_one(
        {"holding_id": holding_id, "user_id": user["user_id"]},
        {"$set": update_data}
    )
    result = await db.holdings.find_one({"holding_id": holding_id}, {"_id": 0})
    if not result:
        raise HTTPException(status_code=404, detail="Holding not found")
    return result

@api_router.delete("/portfolio/holdings/{holding_id}")
async def delete_holding(request: Request, holding_id: str):
    user = await get_current_user(request)
    result = await db.holdings.delete_one({"holding_id": holding_id, "user_id": user["user_id"]})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Holding not found")
    return {"message": "Holding deleted"}

@api_router.delete("/portfolio/holdings-all")
async def clear_all_holdings(request: Request):
    """Delete ALL holdings and associated data for the current user. Full reset."""
    user = await get_current_user(request)
    uid = user["user_id"]
    
    holdings_deleted = (await db.holdings.delete_many({"user_id": uid})).deleted_count
    await db.fund_performance_cache.delete_many({"user_id": uid})
    await db.gmail_imports.delete_many({"user_id": uid})
    await db.portfolio_analysis.delete_many({"user_id": uid})
    await db.ai_insights.delete_many({"user_id": uid})
    await db.upload_tasks.delete_many({"user_id": uid})
    await db.chat_messages.delete_many({"user_id": uid})
    
    return {"message": f"{holdings_deleted} holdings cleared. All portfolio data reset.", "deleted": holdings_deleted}


async def parse_csv_holdings(content: bytes) -> list:
    """Parse CSV/Excel files into holding rows."""
    holdings = []
    # Try UTF-8, then latin-1
    for encoding in ["utf-8", "latin-1", "cp1252"]:
        try:
            text = content.decode(encoding)
            break
        except (UnicodeDecodeError, Exception):
            continue
    else:
        raise HTTPException(status_code=400, detail="Could not decode file. Please use UTF-8 encoding.")
    
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        name = row.get("name") or row.get("Name") or row.get("STOCK") or row.get("stock") or row.get("Scheme Name") or row.get("scheme_name") or row.get("Fund") or ""
        if not name.strip():
            continue
        holdings.append({
            "name": name.strip(),
            "ticker": (row.get("ticker") or row.get("Ticker") or row.get("SYMBOL") or row.get("symbol") or row.get("ISIN") or "").strip(),
            "asset_type": (row.get("asset_type") or row.get("Type") or row.get("type") or row.get("Asset Type") or "equity").strip().lower(),
            "quantity": float(row.get("quantity") or row.get("Quantity") or row.get("QTY") or row.get("qty") or row.get("Units") or row.get("units") or row.get("Balance Units") or 0),
            "buy_price": float(row.get("buy_price") or row.get("Buy Price") or row.get("avg_price") or row.get("cost") or row.get("Avg. Cost") or row.get("NAV") or 0),
            "current_price": float(row.get("current_price") or row.get("Current Price") or row.get("ltp") or row.get("cmp") or row.get("Current NAV") or row.get("Market Value") or 0),
            "sector": (row.get("sector") or row.get("Sector") or "Other").strip(),
            "buy_date": (row.get("buy_date") or row.get("Buy Date") or row.get("date") or row.get("Date") or "").strip(),
        })
    return holdings

async def parse_excel_holdings(content: bytes) -> list:
    """Parse Excel (.xlsx) files into holding rows."""
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []
    
    headers = [str(h).strip().lower() if h else "" for h in rows[0]]
    holdings = []
    
    def col(names):
        for n in names:
            if n.lower() in headers:
                return headers.index(n.lower())
        return None
    
    name_i = col(["name", "scheme name", "fund", "stock", "scheme"])
    qty_i = col(["quantity", "qty", "units", "balance units"])
    buy_i = col(["buy price", "buy_price", "avg price", "avg. cost", "nav", "cost"])
    cur_i = col(["current price", "current_price", "ltp", "cmp", "current nav", "market value"])
    type_i = col(["asset_type", "type", "asset type"])
    sector_i = col(["sector"])
    ticker_i = col(["ticker", "symbol", "isin"])
    date_i = col(["buy_date", "buy date", "date"])
    
    for row in rows[1:]:
        if not row or name_i is None or name_i >= len(row) or not row[name_i]:
            continue
        name = str(row[name_i]).strip()
        if not name:
            continue
        holdings.append({
            "name": name,
            "ticker": str(row[ticker_i]).strip() if ticker_i is not None and ticker_i < len(row) and row[ticker_i] else "",
            "asset_type": str(row[type_i]).strip().lower() if type_i is not None and type_i < len(row) and row[type_i] else "equity",
            "quantity": float(row[qty_i]) if qty_i is not None and qty_i < len(row) and row[qty_i] else 0,
            "buy_price": float(row[buy_i]) if buy_i is not None and buy_i < len(row) and row[buy_i] else 0,
            "current_price": float(row[cur_i]) if cur_i is not None and cur_i < len(row) and row[cur_i] else 0,
            "sector": str(row[sector_i]).strip() if sector_i is not None and sector_i < len(row) and row[sector_i] else "Other",
            "buy_date": str(row[date_i]).strip() if date_i is not None and date_i < len(row) and row[date_i] else "",
        })
    wb.close()
    return holdings


def _classify_mf_sector(scheme_name: str) -> str:
    """Classify mutual fund into sector based on scheme name."""
    name = scheme_name.lower()
    if any(k in name for k in ["index", "nifty", "sensex", "etf"]): return "Index"
    if any(k in name for k in ["small cap", "smallcap"]): return "Small Cap"
    if any(k in name for k in ["mid cap", "midcap"]): return "Mid Cap"
    if any(k in name for k in ["large cap", "largecap", "bluechip", "large & mid"]): return "Large Cap"
    if any(k in name for k in ["flexi cap", "flexicap", "multi cap", "multicap"]): return "Flexi Cap"
    if any(k in name for k in ["balanced", "hybrid", "advantage", "dynamic"]): return "Balanced"
    if any(k in name for k in ["elss", "tax"]): return "ELSS"
    if any(k in name for k in ["debt", "bond", "gilt", "liquid", "money market", "overnight", "short", "credit", "duration", "arbitrage"]): return "Debt"
    if any(k in name for k in ["gold", "sgb", "sovereign"]): return "Gold"
    if any(k in name for k in ["international", "global", "us ", "nasdaq", "fang", "nyse"]): return "International"
    if any(k in name for k in ["banking", "financial"]): return "Banking"
    if any(k in name for k in ["pharma", "health"]): return "Healthcare"
    if any(k in name for k in ["technology", "digital", "it "]): return "IT"
    if any(k in name for k in ["contra", "value"]): return "Value"
    if any(k in name for k in ["focused", "opportunities"]): return "Focused"
    return "Other"


def _convert_casparser_to_holdings(cas_data: dict) -> list:
    """Convert casparser output dict to our holdings format."""
    holdings = []
    folios = cas_data.get("folios", [])
    if not folios:
        return []

    for folio in folios:
        for scheme in folio.get("schemes", []):
            # Get current units balance
            units = scheme.get("close_calculated") or scheme.get("close", 0) or 0
            if units <= 0:
                continue

            scheme_name = scheme.get("scheme", "Unknown Fund")
            isin = scheme.get("isin", "") or ""
            valuation = scheme.get("valuation", {}) or {}
            nav = valuation.get("nav", 0) or 0

            # Calculate average cost from transactions
            total_cost = 0.0
            total_purchase_units = 0.0
            for tx in scheme.get("transactions", []):
                tx_type = (tx.get("type", "") or "").upper()
                tx_amount = tx.get("amount", 0) or 0
                tx_units = tx.get("units", 0) or 0
                if tx_type in ("PURCHASE", "PURCHASE_SIP", "SWITCH_IN", "SWITCH_IN_MERGER",
                               "NEW_FUND_OFFER", "REINVESTMENT", "SYSTEMATIC_INVESTMENT"):
                    if tx_amount > 0 and tx_units > 0:
                        total_cost += abs(tx_amount)
                        total_purchase_units += abs(tx_units)
                elif tx_type in ("REDEMPTION", "SWITCH_OUT"):
                    if tx_amount > 0 and tx_units > 0:
                        # Reduce cost proportionally
                        if total_purchase_units > 0:
                            cost_per_unit = total_cost / total_purchase_units
                            total_cost -= cost_per_unit * abs(tx_units)
                            total_purchase_units -= abs(tx_units)

            avg_cost = total_cost / total_purchase_units if total_purchase_units > 0 else 0

            # Determine asset type
            name_lower = scheme_name.lower()
            if any(k in name_lower for k in ["gold", "sgb", "sovereign gold"]):
                asset_type = "gold"
            elif any(k in name_lower for k in ["etf", "exchange traded"]):
                asset_type = "etf"
            else:
                asset_type = "mutual_fund"

            holdings.append({
                "name": scheme_name,
                "ticker": isin,
                "asset_type": asset_type,
                "quantity": round(units, 4),
                "buy_price": round(avg_cost, 4) if avg_cost > 0 else round(nav, 4),
                "current_price": round(nav, 4),
                "sector": _classify_mf_sector(scheme_name),
            })

    logger.info(f"casparser: processed {len(folios)} folios → {len(holdings)} holdings")
    return holdings


async def parse_cas_pdf(content: bytes, password: str = "") -> list:
    """Parse CAS (Consolidated Account Statement) PDF.
    Uses casparser library first (accurate, structured), falls back to AI if needed."""
    
    # ── 1st: CAS Parser API (casparser.in) — fast, accurate, no local OCR ──
    try:
        from services.cas_api_client import parse_cas_via_api, is_configured
        if is_configured():
            api_holdings = parse_cas_via_api(content, password or "")
            if api_holdings:
                logger.info(f"CAS Parser API extracted {len(api_holdings)} holdings")
                # Enrich with masterdata (live prices, name cleanup, plan/option)
                try:
                    from services.masterdata import validate_and_enrich_holdings
                    api_holdings = validate_and_enrich_holdings(api_holdings)
                except Exception as e:
                    logger.info(f"Masterdata enrichment skipped: {e}")
                return api_holdings
            logger.info("CAS Parser API returned no holdings, falling back")
    except Exception as e:
        logger.info(f"CAS Parser API failed: {e}, falling back to casparser library")

    # ── 2nd: casparser library (text-based, for digital PDFs) ──
    try:
        import casparser
        cas_data = casparser.read_cas_pdf(io.BytesIO(content), password or "", output="dict")
        holdings = _convert_casparser_to_holdings(cas_data)
        if holdings:
            logger.info(f"casparser extracted {len(holdings)} holdings successfully")
            return holdings
        logger.info("casparser returned no holdings, falling back to AI parsing")
    except Exception as e:
        logger.info(f"casparser failed: {e}, falling back to local OCR parsing")

    # ── Fallback: Local Tesseract OCR (no cloud dependency) ──
    from services.cas_parser import parse_nsdl_cas_image
    local_holdings = parse_nsdl_cas_image(content, password)
    if local_holdings:
        logger.info(f"Local OCR parser extracted {len(local_holdings)} holdings")
        return local_holdings

    import base64
    
    cas_system_message = """You are a CAS (Consolidated Account Statement) parser for Indian mutual funds and investments.
Extract ALL investment holdings from the CAS data provided.

Return ONLY a valid JSON array. Each object must have:
- "name": scheme/fund name (string, clean and readable)
- "ticker": ISIN code if found (string, empty if not found)
- "asset_type": one of "mutual_fund", "equity", "etf", "bond", "gold", "fd", "other"
- "quantity": number of units/shares (float)
- "buy_price": average cost per unit (float, 0 if unknown)
- "current_price": current NAV or market price per unit (float, 0 if unknown)
- "sector": category like "Large Cap", "Mid Cap", "Small Cap", "Flexi Cap", "Multi Cap", "Balanced", "Debt", "ELSS", "Index", "Gold", "Banking", "IT", "Other" (string)

IMPORTANT RULES:
- If same fund appears with different folios, keep them SEPARATE (don't combine)
- For mutual funds, use the NAV as current_price and avg cost as buy_price
- For equities, use market price as current_price
- For ETFs, classify as "etf" not "mutual_fund"
- For Sovereign Gold Bonds, use asset_type "gold"
- Extract ALL holdings, don't skip any
- Return ONLY the JSON array, no explanation"""

    # Try text extraction first (works for text-based PDFs)
    text = ""
    pdf_is_encrypted = False
    decrypt_succeeded = False
    try:
        from PyPDF2 import PdfReader
        reader = PdfReader(io.BytesIO(content))
        pdf_is_encrypted = reader.is_encrypted
        if reader.is_encrypted:
            if not password:
                raise HTTPException(status_code=400, detail="PDF is password-protected. Please provide the password.")
            decrypt_result = reader.decrypt(password)
            # PyPDF2 3.x returns PasswordType enum: NOT_DECRYPTED=0, USER_PASSWORD=1, OWNER_PASSWORD=2
            if not decrypt_result:
                raise HTTPException(status_code=400, detail="Incorrect PDF password. Please try again.")
            decrypt_succeeded = True
            logger.info(f"PDF decrypted successfully (type={decrypt_result})")
        for page in reader.pages:
            extracted = page.extract_text()
            if extracted:
                text += extracted + "\n"
    except HTTPException:
        raise
    except Exception as e:
        err_str = str(e)
        logger.warning(f"PyPDF2 text extraction failed: {err_str}")
        # Missing PyCryptodome for AES-encrypted PDFs — give explicit error
        if "pycryptodome" in err_str.lower() or "aes" in err_str.lower():
            raise HTTPException(status_code=500, detail="Server missing PyCryptodome library for AES-encrypted PDFs. Please contact support.")
        # If we know it's encrypted and password wasn't provided or failed, raise clear error
        if pdf_is_encrypted and not decrypt_succeeded and not password:
            raise HTTPException(status_code=400, detail="PDF is password-protected. Please provide the password.")
        if pdf_is_encrypted and not decrypt_succeeded and password:
            raise HTTPException(status_code=400, detail="Incorrect PDF password or the file is corrupted. Please check and try again.")

    if text.strip() and len(text.strip()) > 200:
        # Process page-by-page for accuracy (each page is a logical unit)
        # Combine pages into groups that are under token limits
        from PyPDF2 import PdfReader as _PdfReader
        page_texts = []
        try:
            _reader = _PdfReader(io.BytesIO(content))
            if _reader.is_encrypted and password:
                _reader.decrypt(password)
            for pg in _reader.pages:
                pt = pg.extract_text() or ""
                if pt.strip():
                    page_texts.append(pt)
        except Exception:
            # Fallback: split full text by page markers or size
            page_texts = [text]
        
        if not page_texts:
            page_texts = [text]
        
        all_parsed = []
        # Group pages into batches that stay under ~12K chars each
        current_batch = ""
        batch_num = 0
        for pt in page_texts:
            if len(current_batch) + len(pt) > 12000 and current_batch:
                # Process this batch
                try:
                    parsed = await ai_engine.parse_cas_text(current_batch, f"cas_txt_b{batch_num}_{uuid.uuid4().hex[:6]}")
                    if parsed:
                        all_parsed.extend(parsed)
                        logger.info(f"CAS text batch {batch_num}: {len(parsed)} holdings")
                except Exception as e:
                    logger.warning(f"CAS text batch {batch_num} failed: {e}")
                current_batch = pt
                batch_num += 1
            else:
                current_batch += "\n" + pt
        
        # Process final batch
        if current_batch.strip():
            try:
                parsed = await ai_engine.parse_cas_text(current_batch, f"cas_txt_b{batch_num}_{uuid.uuid4().hex[:6]}")
                if parsed:
                    all_parsed.extend(parsed)
                    logger.info(f"CAS text batch {batch_num}: {len(parsed)} holdings")
            except Exception as e:
                logger.warning(f"CAS text batch {batch_num} failed: {e}")
        
        if all_parsed:
            # Deduplicate by ISIN+name
            seen = set()
            unique = []
            for h in all_parsed:
                isin = (h.get("ticker") or h.get("isin") or "").strip().upper()
                name = h.get("name", "").strip().lower()[:40]
                key = f"{isin}__{name}" if isin else f"__{name}__{h.get('quantity',0)}"
                if key not in seen:
                    seen.add(key)
                    unique.append(h)
            logger.info(f"CAS text total: {len(all_parsed)} raw → {len(unique)} unique holdings")
            return unique
    
    # Image-based PDF — convert pages to images and use OpenAI vision
    logger.info(f"CAS PDF is image-based, processing via OpenAI vision (password={'yes' if password else 'no'})")
    try:
        from pdf2image import convert_from_bytes, pdfinfo_from_bytes
        import asyncio
        
        # Get page count
        pdfinfo_kwargs = {}
        if password:
            pdfinfo_kwargs["userpw"] = password
        try:
            info = pdfinfo_from_bytes(content, **pdfinfo_kwargs)
            total_pages = info.get("Pages", 0)
        except Exception as e:
            logger.warning(f"pdfinfo failed: {e}")
            total_pages = 0
        
        if total_pages == 0:
            detail = "Could not read PDF."
            if not password:
                detail += " The file may be password-protected — please provide the password."
            raise HTTPException(status_code=400, detail=detail)
        
        logger.info(f"CAS has {total_pages} pages, processing 3 pages per batch in parallel")
        
        # Convert ALL pages to images in one go (faster than per-batch conversion)
        convert_kwargs = {"dpi": 130}
        if password:
            convert_kwargs["userpw"] = password
        all_page_images = convert_from_bytes(content, **convert_kwargs)
        logger.info(f"Converted {len(all_page_images)} pages to images")
        
        # Build batches of 3 pages
        batches = []
        batch_size = 3
        for start in range(0, len(all_page_images), batch_size):
            end = min(start + batch_size, len(all_page_images))
            image_data_list = []
            for img in all_page_images[start:end]:
                img_buf = io.BytesIO()
                img.save(img_buf, format="PNG", optimize=True)
                image_data_list.append(img_buf.getvalue())
            batches.append((start + 1, end, image_data_list))
        
        # Process ALL batches in parallel
        async def parse_batch(start_page, end_page, images):
            try:
                holdings = await ai_engine.parse_cas_images(
                    images, f"{start_page}-{end_page}",
                    f"cas_p{start_page}_{uuid.uuid4().hex[:6]}"
                )
                if holdings:
                    logger.info(f"Pages {start_page}-{end_page}: {len(holdings)} holdings")
                return holdings or []
            except Exception as e:
                logger.warning(f"Pages {start_page}-{end_page} failed: {e}")
                return []
        
        results = await asyncio.gather(
            *[parse_batch(s, e, imgs) for s, e, imgs in batches]
        )
        
        all_holdings = []
        for batch_result in results:
            all_holdings.extend(batch_result)
        
        # Deduplicate by name+quantity+current_price
        seen = set()
        unique_holdings = []
        for h in all_holdings:
            key = f"{h.get('name','').strip()}__{h.get('quantity',0)}__{h.get('current_price',0)}"
            if key not in seen:
                seen.add(key)
                unique_holdings.append(h)
        
        logger.info(f"Total unique holdings from CAS: {len(unique_holdings)}")
        
        if not unique_holdings:
            raise HTTPException(status_code=422, detail="Could not extract any holdings from the CAS PDF. Please ensure the file contains valid CAS data.")
        
        return unique_holdings
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"CAS PDF parsing error: {e}")
        raise HTTPException(status_code=422, detail=f"Could not parse CAS PDF. Error: {str(e)}")

def _parse_json_response(response: str) -> list:
    """Parse JSON array from LLM response, handling markdown code blocks."""
    clean = response.strip()
    if clean.startswith("```"):
        lines = clean.split("\n")
        start = 1
        end = len(lines) - 1
        if lines[0].startswith("```json"):
            start = 1
        for i in range(len(lines) - 1, 0, -1):
            if lines[i].strip() == "```":
                end = i
                break
        clean = "\n".join(lines[start:end])
    try:
        result = json.loads(clean.strip())
        return result if isinstance(result, list) else []
    except json.JSONDecodeError:
        import re
        match = re.search(r'\[[\s\S]*\]', clean)
        if match:
            try:
                result = json.loads(match.group())
                return result if isinstance(result, list) else []
            except json.JSONDecodeError:
                pass
        return []

def _parse_json_response_obj(response: str) -> dict:
    """Parse JSON object from LLM response."""
    clean = response.strip()
    if clean.startswith("```"):
        lines = clean.split("\n")
        start = 1
        end = len(lines) - 1
        for i in range(len(lines) - 1, 0, -1):
            if lines[i].strip() == "```":
                end = i
                break
        clean = "\n".join(lines[start:end])
    try:
        result = json.loads(clean.strip())
        return result if isinstance(result, dict) else {}
    except json.JSONDecodeError:
        import re
        match = re.search(r'\{[\s\S]*\}', clean)
        if match:
            try:
                result = json.loads(match.group())
                return result if isinstance(result, dict) else {}
            except json.JSONDecodeError:
                pass
        return {}

async def _save_holdings(user_id: str, parsed: list, file_type: str, task_id: str = None, portfolio_id: str = ""):
    """Save parsed holdings to DB. For CAS uploads, replaces ALL existing holdings
    (latest CAS = source of truth). For manual/other uploads, appends."""
    
    is_cas = "cas" in file_type.lower()
    
    if is_cas:
        # CAS is the full portfolio snapshot — replace everything
        delete_query = {"user_id": user_id}
        if portfolio_id:
            delete_query["portfolio_id"] = portfolio_id
        old_count = await db.holdings.count_documents(delete_query)
        await db.holdings.delete_many(delete_query)
        logger.info(f"CAS upload: cleared {old_count} old holdings for user {user_id}")
    
    holdings_added = []
    for h in parsed:
        asset_type = h.get("asset_type", "equity")
        if asset_type not in ["equity", "mutual_fund", "etf", "bond", "gold", "fd", "other"]:
            asset_type = "mutual_fund" if "fund" in h.get("name", "").lower() else "equity"
        
        buy_price_val = float(h.get("buy_price", 0))
        current_price_val = float(h.get("current_price", 0))
        # CAS PDFs often don't include cost basis — use current_price as fallback
        if buy_price_val == 0 and current_price_val > 0:
            buy_price_val = current_price_val
        
        holding_doc = {
            "holding_id": f"hold_{uuid.uuid4().hex[:12]}",
            "user_id": user_id,
            "portfolio_id": portfolio_id,
            "name": h.get("name", "Unknown"),
            "ticker": h.get("ticker", ""),
            "asset_type": asset_type,
            "quantity": float(h.get("quantity", 0)),
            "buy_price": buy_price_val,
            "current_price": current_price_val,
            "sector": h.get("sector", "Other"),
            "buy_date": h.get("buy_date", "") or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "source": "cas" if is_cas else h.get("source", "manual"),
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        await db.holdings.insert_one(holding_doc)
        holdings_added.append({
            "holding_id": holding_doc["holding_id"],
            "name": holding_doc["name"],
            "asset_type": holding_doc["asset_type"],
            "quantity": holding_doc["quantity"],
        })
    
    msg = f"{len(holdings_added)} holdings imported from {file_type}"
    if is_cas and old_count > 0:
        msg = f"{len(holdings_added)} holdings imported from {file_type} (replaced {old_count} previous)"
    
    if task_id:
        await db.upload_tasks.update_one(
            {"task_id": task_id},
            {"$set": {
                "status": "completed",
                "message": msg,
                "count": len(holdings_added),
                "holdings": holdings_added,
                "completed_at": datetime.now(timezone.utc).isoformat()
            }}
        )
    
    # Invalidate cached analytics
    await db.fund_performance_cache.delete_many({"user_id": user_id})
    
    return holdings_added

async def _process_cas_background(content: bytes, user_id: str, task_id: str, portfolio_id: str = "", password: str = ""):
    """Background task for CAS PDF processing."""
    try:
        logger.info(f"Background CAS task {task_id}: password={'provided' if password else 'none'}, size={len(content)}")
        await db.upload_tasks.update_one(
            {"task_id": task_id},
            {"$set": {"status": "processing", "message": "Parsing CAS PDF with AI..."}}
        )
        parsed = await parse_cas_pdf(content, password=password)
        if not parsed:
            await db.upload_tasks.update_one(
                {"task_id": task_id},
                {"$set": {"status": "completed", "message": "No holdings found in CAS PDF", "count": 0, "holdings": []}}
            )
            return
        await _save_holdings(user_id, parsed, "CAS PDF", task_id, portfolio_id)
    except HTTPException as he:
        # HTTPException from parse_cas_pdf (password errors, parse failures)
        error_msg = he.detail if hasattr(he, 'detail') else str(he)
        logger.error(f"Background CAS processing HTTPException: {error_msg}")
        await db.upload_tasks.update_one(
            {"task_id": task_id},
            {"$set": {"status": "error", "message": error_msg, "count": 0, "holdings": []}}
        )
    except Exception as e:
        logger.error(f"Background CAS processing error: {e}")
        error_msg = str(e)
        # Extract clean message for password/decrypt failures
        if "password" in error_msg.lower() or "decrypt" in error_msg.lower() or "encrypted" in error_msg.lower():
            error_msg = "PDF is password-protected. Please provide the correct password."
        elif "could not read" in error_msg.lower():
            error_msg = "Could not read PDF. The file may be corrupted or in an unsupported format."
        await db.upload_tasks.update_one(
            {"task_id": task_id},
            {"$set": {"status": "error", "message": error_msg, "count": 0, "holdings": []}}
        )

@api_router.post("/portfolio/upload")
async def upload_portfolio(request: Request, file: UploadFile = File(...)):
    """Upload portfolio file - supports CSV, Excel (.xlsx), and CAS PDF."""
    user = await get_current_user(request)
    filename = (file.filename or "").lower()
    user_id = user["user_id"]
    
    # Read file synchronously via underlying SpooledTemporaryFile (faster than async read for large files)
    content = file.file.read()
    
    # For PDF files, process asynchronously (can take 1-3 minutes)
    if filename.endswith(".pdf"):
        task_id = f"task_{uuid.uuid4().hex[:12]}"
        await db.upload_tasks.insert_one({
            "task_id": task_id,
            "user_id": user_id,
            "status": "processing",
            "message": "CAS PDF received, AI parsing started...",
            "count": 0,
            "holdings": [],
            "created_at": datetime.now(timezone.utc).isoformat()
        })
        
        logger.info(f"CAS PDF received: {len(content)} bytes, task {task_id}")
        asyncio.create_task(_process_cas_background(content, user_id, task_id))
        return {
            "task_id": task_id,
            "status": "processing",
            "message": "CAS PDF is being processed by AI. This may take 1-2 minutes.",
            "count": 0,
            "holdings": []
        }
    
    # For CSV/Excel, process synchronously
    if filename.endswith(".xlsx") or filename.endswith(".xls"):
        parsed = await parse_excel_holdings(content)
        file_type = "Excel"
    elif filename.endswith(".csv"):
        parsed = await parse_csv_holdings(content)
        file_type = "CSV"
    else:
        try:
            parsed = await parse_csv_holdings(content)
            file_type = "CSV"
        except Exception:
            raise HTTPException(status_code=400, detail="Unsupported file format. Please upload CSV, Excel (.xlsx), or CAS PDF.")
    
    if not parsed:
        return {"message": "No holdings found in the uploaded file", "count": 0, "holdings": []}
    
    holdings_added = await _save_holdings(user_id, parsed, file_type)
    return {
        "message": f"{len(holdings_added)} holdings imported from {file_type}",
        "count": len(holdings_added),
        "holdings": holdings_added
    }

@api_router.post("/portfolio/upload-raw")
async def upload_portfolio_raw(request: Request):
    """Raw upload endpoint for large files - avoids multipart parsing overhead.
    Send file as raw body with X-Filename, X-Portfolio-Id, X-Password headers."""
    user = await get_current_user(request)
    filename = request.headers.get("X-Filename", "upload.pdf").lower()
    portfolio_id = request.headers.get("X-Portfolio-Id", "")
    pdf_password = request.headers.get("X-Password", "")
    user_id = user["user_id"]
    
    # Stream the body directly
    body_chunks = []
    async for chunk in request.stream():
        body_chunks.append(chunk)
    content = b"".join(body_chunks)
    
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")
    
    logger.info(f"Raw upload received: {len(content)} bytes, filename: {filename}, password={'yes' if pdf_password else 'no'}, portfolio: {portfolio_id}")
    
    if filename.endswith(".pdf"):
        task_id = f"task_{uuid.uuid4().hex[:12]}"
        await db.upload_tasks.insert_one({
            "task_id": task_id,
            "user_id": user_id,
            "status": "processing",
            "message": "CAS PDF received, AI parsing started...",
            "count": 0,
            "holdings": [],
            "created_at": datetime.now(timezone.utc).isoformat()
        })
        asyncio.create_task(_process_cas_background(content, user_id, task_id, portfolio_id, pdf_password))
        return {
            "task_id": task_id,
            "status": "processing",
            "message": "CAS PDF is being processed by AI. This may take 1-2 minutes.",
            "count": 0,
            "holdings": []
        }
    
    # CSV/Excel via raw
    if filename.endswith(".xlsx") or filename.endswith(".xls"):
        parsed = await parse_excel_holdings(content)
        file_type = "Excel"
    elif filename.endswith(".csv"):
        parsed = await parse_csv_holdings(content)
        file_type = "CSV"
    else:
        raise HTTPException(status_code=400, detail="Unsupported format")
    
    if not parsed:
        return {"message": "No holdings found", "count": 0, "holdings": []}
    holdings_added = await _save_holdings(user_id, parsed, file_type, portfolio_id=portfolio_id)
    return {"message": f"{len(holdings_added)} holdings imported from {file_type}", "count": len(holdings_added), "holdings": holdings_added}

@api_router.get("/portfolio/upload-status/{task_id}")
async def get_upload_status(request: Request, task_id: str):
    """Poll the status of a CAS PDF upload task."""
    user = await get_current_user(request)
    task = await db.upload_tasks.find_one(
        {"task_id": task_id, "user_id": user["user_id"]}, {"_id": 0}
    )
    if not task:
        raise HTTPException(status_code=404, detail="Upload task not found")
    return task

@api_router.get("/portfolio/upload-latest-task")
async def get_latest_upload_task(request: Request):
    """Get the most recent upload task for the user (for timeout recovery)."""
    user = await get_current_user(request)
    task = await db.upload_tasks.find_one(
        {"user_id": user["user_id"]},
        {"_id": 0},
        sort=[("created_at", -1)]
    )
    if not task:
        raise HTTPException(status_code=404, detail="No upload tasks found")
    return task

# Keep old endpoint for backward compatibility
@api_router.post("/portfolio/upload-csv")
async def upload_csv_legacy(request: Request, file: UploadFile = File(...)):
    return await upload_portfolio(request, file)

# ── CAS Parser: Portfolio Connect SDK integration ──────────────────────

@api_router.post("/casparser/access-token")
async def casparser_access_token(request: Request):
    """
    Mint a short-lived CAS Parser `at_` access token for the frontend widget.
    The production `sk_` key never leaves the backend.
    """
    user = await get_current_user(request)  # authn required
    from services.cas_api_client import generate_access_token, is_configured
    if not is_configured():
        raise HTTPException(status_code=503, detail="CAS Parser not configured")
    token_payload = generate_access_token(expiry_minutes=60)
    if not token_payload:
        raise HTTPException(status_code=502, detail="Failed to mint CAS Parser access token")
    logger.info(f"Minted CAS Parser access token for user={user['user_id']}")
    return token_payload


@api_router.post("/portfolio/import-connect")
async def portfolio_import_from_connect(request: Request):
    """
    Ingest the parsed portfolio payload that the Portfolio Connect widget
    delivers via `onSuccess`. Body: the full CAS Parser ParsedData object
    (optionally wrapped in `{ "data": { ... }, "metadata": { ... } }`).
    """
    user = await get_current_user(request)
    body = await request.json()
    # Widget's onSuccess gives { data, metadata } — unwrap if present.
    parsed_data = body.get("data") if isinstance(body, dict) and "data" in body else body
    if not isinstance(parsed_data, dict):
        raise HTTPException(status_code=400, detail="Invalid payload: expected parsed CAS JSON")

    from services.cas_api_client import map_api_response_to_holdings
    holdings = map_api_response_to_holdings(parsed_data)
    if not holdings:
        raise HTTPException(status_code=422, detail="No holdings found in parsed data")

    # Enrich with masterdata (live NAV/prices, plan/option, fuzzy names)
    try:
        from services.masterdata import validate_and_enrich_holdings
        holdings = validate_and_enrich_holdings(holdings)
    except Exception as e:
        logger.info(f"Masterdata enrichment skipped: {e}")

    saved = await _save_holdings(user["user_id"], holdings, "CAS Connect")
    cas_type = (parsed_data.get("meta") or {}).get("cas_type", "")
    investor_name = (parsed_data.get("investor") or {}).get("name", "")
    logger.info(
        f"CAS Connect: saved {len(saved)} holdings for user={user['user_id']} "
        f"cas_type={cas_type} investor={investor_name}"
    )
    return {
        "message": f"{len(saved)} holdings imported via Portfolio Connect",
        "count": len(saved),
        "holdings": saved,
        "cas_type": cas_type,
        "investor": investor_name,
    }



@api_router.get("/portfolio/analytics")
async def get_analytics(request: Request, portfolio_id: str = ""):
    user = await get_current_user(request)
    query = {"user_id": user["user_id"]}
    if portfolio_id:
        query["portfolio_id"] = portfolio_id
    holdings = await db.holdings.find(query, {"_id": 0}).to_list(2000)
    
    # Update mutual fund holdings with live NAV from AMFI
    holdings = await update_holdings_nav(holdings)
    # Persist updated NAV prices back to DB
    for h in holdings:
        if h.get("nav_source") == "AMFI" and h.get("holding_id"):
            await db.holdings.update_one(
                {"holding_id": h["holding_id"]},
                {"$set": {"current_price": h["current_price"], "nav_date": h.get("nav_date", ""), "nav_source": "AMFI"}}
            )
    
    # Update equity and ETF holdings with live prices from Yahoo Finance
    holdings, live_price_stats = await fetch_live_prices(holdings)
    # Persist live prices back to DB
    for h in holdings:
        if h.get("price_source") == "yahoo_finance" and h.get("holding_id"):
            await db.holdings.update_one(
                {"holding_id": h["holding_id"]},
                {"$set": {
                    "current_price": h["current_price"],
                    "price_source": "yahoo_finance",
                    "price_updated_at": h.get("price_updated_at", ""),
                    "nse_symbol": h.get("nse_symbol", ""),
                }}
            )
    
    # Apply SGB issue prices from RBI mapping
    holdings, sgb_updated = apply_sgb_issue_prices(holdings)
    # Persist SGB buy prices back to DB
    for h in holdings:
        if h.get("price_source_buy") == "rbi_sgb_mapping" and h.get("holding_id"):
            await db.holdings.update_one(
                {"holding_id": h["holding_id"]},
                {"$set": {
                    "buy_price": h["buy_price"],
                    "sgb_series": h.get("sgb_series", ""),
                    "sgb_issue_date": h.get("sgb_issue_date", ""),
                    "price_source_buy": "rbi_sgb_mapping",
                }}
            )
    
    if not holdings:
        return {
            "total_invested": 0, "current_value": 0, "total_returns": 0,
            "returns_pct": 0, "asset_allocation": [], "sector_exposure": [],
            "risk_score": 0, "risk_label": "N/A", "holdings_count": 0,
            "top_gainers": [], "top_losers": []
        }
    
    total_invested = 0
    current_value = 0
    asset_map = {}
    sector_map_equity = {}  # Equity-only sector exposure
    holding_perf = []
    missing_cmp_count = 0
    assumed_cost_count = 0
    
    for h in holdings:
        buy_p = h["buy_price"] if h["buy_price"] > 0 else h["current_price"]
        inv = h["quantity"] * buy_p
        cur = h["quantity"] * h["current_price"]
        total_invested += inv
        current_value += cur
        
        # Track data quality flags
        if h["buy_price"] > 0 and abs(h["buy_price"] - h["current_price"]) < 0.01:
            missing_cmp_count += 1
        if h["buy_price"] == 0 or (h.get("source") == "cas" and abs(h["buy_price"] - h["current_price"]) < 0.01):
            assumed_cost_count += 1
        
        at = h.get("asset_type", "other")
        asset_map[at] = asset_map.get(at, 0) + cur
        
        # Sector exposure: equity holdings only (not MFs, ETFs, etc.)
        if at == "equity":
            sec = h.get("sector", "Other")
            sector_map_equity[sec] = sector_map_equity.get(sec, 0) + cur
        
        pct_change = ((cur - inv) / inv * 100) if inv > 0 else 0
        holding_perf.append({"name": h["name"], "pct_change": round(pct_change, 2), "value": cur, "asset_type": h.get("asset_type", "other")})
    
    total_returns = current_value - total_invested
    returns_pct = (total_returns / total_invested * 100) if total_invested > 0 else 0
    
    asset_allocation = [{"name": k, "value": round(v, 2)} for k, v in asset_map.items()]
    sector_exposure = [{"name": k, "value": round(v, 2)} for k, v in sector_map_equity.items()]
    
    # Risk scoring: based on concentration and diversification
    risk_score = 0
    if len(holdings) < 3:
        risk_score += 30
    elif len(holdings) < 5:
        risk_score += 15
    
    if asset_allocation:
        max_asset_pct = max(a["value"] for a in asset_allocation) / current_value * 100 if current_value > 0 else 0
        if max_asset_pct > 80:
            risk_score += 30
        elif max_asset_pct > 60:
            risk_score += 20
        elif max_asset_pct > 40:
            risk_score += 10
    
    if sector_exposure:
        max_sector_pct = max(s["value"] for s in sector_exposure) / current_value * 100 if current_value > 0 else 0
        if max_sector_pct > 50:
            risk_score += 25
        elif max_sector_pct > 30:
            risk_score += 15
    
    equity_val_total = (asset_map.get("equity", 0) + asset_map.get("mutual_fund", 0) + asset_map.get("etf", 0))
    equity_pct = equity_val_total / current_value * 100 if current_value > 0 else 0
    if equity_pct > 80:
        risk_score += 15
    
    risk_score = min(risk_score, 100)
    risk_label = "Low" if risk_score < 30 else "Moderate" if risk_score < 60 else "High"
    
    holding_perf.sort(key=lambda x: x["pct_change"], reverse=True)
    top_gainers = holding_perf[:10]
    top_losers = list(reversed(holding_perf[-10:])) if len(holding_perf) > 10 else []
    
    # Heatmap data: all holdings with value and return info for treemap
    heatmap_data = []
    for h in holdings:
        inv = h["quantity"] * h["buy_price"]
        cur = h["quantity"] * h["current_price"]
        pct = ((cur - inv) / inv * 100) if inv > 0 else 0
        if cur > 0:
            heatmap_data.append({
                "name": h["name"][:30],
                "ticker": h.get("ticker", ""),
                "value": round(cur, 2),
                "invested": round(inv, 2),
                "return_pct": round(pct, 1),
                "asset_type": h.get("asset_type", "other"),
                "sector": h.get("sector", "Other"),
            })
    heatmap_data.sort(key=lambda x: x["value"], reverse=True)
    
    # Performance trend: modeled 30-day portfolio value based on current data
    # SIMULATED — no real historical price data available
    import hashlib
    trend = []
    base = total_invested if total_invested > 0 else current_value * 0.9
    for i in range(30):
        day_offset = 29 - i
        d = datetime.now(timezone.utc) - timedelta(days=day_offset)
        day_hash = int(hashlib.md5(d.strftime("%Y-%m-%d").encode()).hexdigest()[:8], 16)
        noise = ((day_hash % 1000) / 1000.0 - 0.5) * 0.03
        progress = (30 - day_offset) / 30
        modeled = base + (total_returns * progress) + (noise * current_value)
        trend.append({
            "date": d.strftime("%b %d"),
            "value": round(max(modeled, base * 0.85), 0),
        })
    if trend:
        trend[-1]["value"] = round(current_value, 0)
    
    # Day change: SIMULATED — no real-time market feed connected
    today_hash = int(hashlib.md5(datetime.now(timezone.utc).strftime("%Y-%m-%d").encode()).hexdigest()[:8], 16)
    day_pct = ((today_hash % 2000) / 2000.0 - 0.5) * 0.04
    day_change = round(current_value * day_pct, 2)
    day_change_pct = round((day_change / current_value * 100) if current_value > 0 else 0, 2)
    
    # ── Data Quality Flags ──
    data_flags = {
        "day_change_simulated": True,
        "performance_trend_simulated": True,
        "missing_cmp_count": missing_cmp_count,
        "assumed_cost_count": assumed_cost_count,
        "total_holdings": len(holdings),
        "sector_exposure_equity_only": True,
        "explanations": {
            "day_change": "Day change is simulated using a deterministic model. Real-time market data feed is not connected. Actual day change requires a live stock/MF price API.",
            "performance_trend": "The 30-day trend is modeled, not based on actual historical portfolio values. Historical price API integration is needed for real data.",
            "risk_score": f"Risk Score ({risk_score}/100): Based on concentration risk (top holding %), asset diversity ({len(set(h.get('asset_type') for h in holdings))} asset types), sector concentration, and equity overweight ({equity_pct:.0f}%). Higher score = Higher risk.",
            "health_diversification": "Diversification: Measured using HHI (Herfindahl-Hirschman Index) for concentration, number of asset types (equity, MF, gold, etc.), and sector spread. More diverse = higher score.",
            "health_risk": "Risk Management: Inverse of the raw risk score. Lower portfolio risk = higher risk management score.",
            "health_cost": "Cost Efficiency: Penalizes Regular plan mutual funds vs Direct plans. More Direct plans = higher cost efficiency.",
            "health_performance": "Performance: Based on overall portfolio return %. 15%+ return = 95, 10-15% = 80, 5-10% = 65, 0-5% = 50, negative = lower.",
            "health_overall": "Overall Health = 30% Diversification + 25% Risk Management + 20% Cost Efficiency + 25% Performance. Grade: A+ (90+), A (80+), B+ (70+), B (60+), C (50+), D (35+), F (<35).",
            "sector_exposure": "Sector exposure is calculated for equity (stock) holdings only. Mutual funds are excluded as their underlying sector allocation is not available from CAS data.",
            "missing_cmp": f"{missing_cmp_count} holdings have Current Market Price (CMP) equal to Buy Price — this usually means no live price data is available. P&L for these holdings will show as zero.",
        }
    }
    
    return {
        "total_invested": round(total_invested, 2),
        "current_value": round(current_value, 2),
        "total_returns": round(total_returns, 2),
        "returns_pct": round(returns_pct, 2),
        "day_change": day_change,
        "day_change_pct": day_change_pct,
        "asset_allocation": asset_allocation,
        "sector_exposure": sector_exposure,
        "risk_score": risk_score,
        "risk_label": risk_label,
        "holdings_count": len(holdings),
        "top_gainers": top_gainers,
        "top_losers": top_losers,
        "heatmap_data": heatmap_data[:40],
        "performance_trend": trend,
        "data_flags": data_flags,
        "live_price_stats": live_price_stats,
        # ── Product Intelligence ──
        "health_score": compute_health_score(holdings, total_invested, current_value),
        "risk_analysis": compute_risk_analysis(holdings, current_value),
        "recommendations": generate_recommendations(holdings, current_value, total_invested),
    }

# ==================== NAV & DEEP ANALYTICS ROUTES ====================

@api_router.post("/portfolio/refresh-prices")
async def refresh_equity_prices(request: Request):
    """Manually refresh live equity/ETF prices from Yahoo Finance."""
    user = await get_current_user(request)
    holdings = await db.holdings.find(
        {"user_id": user["user_id"], "asset_type": {"$in": ["equity", "etf"]}},
        {"_id": 0}
    ).to_list(2000)
    
    if not holdings:
        return {"updated": 0, "message": "No equity/ETF holdings found"}
    
    holdings, stats = await fetch_live_prices(holdings)
    # Persist
    for h in holdings:
        if h.get("price_source") == "yahoo_finance" and h.get("holding_id"):
            await db.holdings.update_one(
                {"holding_id": h["holding_id"]},
                {"$set": {
                    "current_price": h["current_price"],
                    "price_source": "yahoo_finance",
                    "price_updated_at": h.get("price_updated_at", ""),
                    "nse_symbol": h.get("nse_symbol", ""),
                }}
            )
    return {"message": "Prices refreshed", **stats}

@api_router.get("/portfolio/simulate")
async def simulate_portfolio(request: Request, portfolio_id: str = ""):
    """Simulate optimized portfolio if all recommendations are implemented."""
    user = await get_current_user(request)
    query = {"user_id": user["user_id"]}
    if portfolio_id:
        query["portfolio_id"] = portfolio_id
    holdings = await db.holdings.find(query, {"_id": 0}).to_list(2000)
    if not holdings:
        return {"current_returns_pct": 0, "optimized_returns_pct": 0, "additional_returns": 0, "actions": []}
    
    # Fetch live prices first
    holdings, _ = await fetch_live_prices(holdings)
    holdings = await update_holdings_nav(holdings)
    
    total_invested = sum(h["quantity"] * (h["buy_price"] if h["buy_price"] > 0 else h["current_price"]) for h in holdings)
    current_value = sum(h["quantity"] * h["current_price"] for h in holdings)
    
    return simulate_optimized_portfolio(holdings, current_value, total_invested)

@api_router.post("/nav/refresh")
async def refresh_nav(request: Request):
    """Manually refresh AMFI NAV cache and update all MF holdings."""
    user = await get_current_user(request)
    nav_map = await fetch_nav_data()
    holdings = await db.holdings.find({"user_id": user["user_id"], "asset_type": "mutual_fund"}, {"_id": 0}).to_list(2000)
    updated_count = 0
    for h in holdings:
        isin = (h.get("ticker") or "").upper().strip()
        name = h.get("name", "")
        nav_entry = None
        if isin and isin in nav_map:
            nav_entry = nav_map[isin]
        elif name:
            nav_entry = await lookup_nav(name=name)
        if nav_entry:
            await db.holdings.update_one(
                {"holding_id": h["holding_id"]},
                {"$set": {"current_price": nav_entry["nav"], "nav_date": nav_entry["date"], "nav_source": "AMFI"}}
            )
            updated_count += 1
    return {"updated": updated_count, "total_mf": len(holdings), "nav_entries": len(nav_map)}


@api_router.get("/portfolio/fund-performance")
async def get_fund_performance(request: Request, portfolio_id: str = "", force: str = ""):
    """Get MF benchmark ratings, performance distribution, and category overlap.
    Cached in MongoDB for 2 hours. Pass force=1 to refresh."""
    user = await get_current_user(request)
    user_id = user["user_id"]

    # Check cache first (2-hour TTL)
    if not force:
        cached = await db.fund_performance_cache.find_one({"user_id": user_id}, {"_id": 0})
        if cached:
            cached_at = cached.get("cached_at", "")
            if cached_at:
                try:
                    from dateutil.parser import parse as parse_date
                    age = (datetime.now(timezone.utc) - parse_date(cached_at).replace(tzinfo=timezone.utc)).total_seconds()
                    if age < 7200:  # 2 hours
                        return cached.get("data", {})
                except Exception:
                    pass

    query = {"user_id": user_id}
    if portfolio_id:
        query["portfolio_id"] = portfolio_id
    holdings = await db.holdings.find(query, {"_id": 0}).to_list(2000)

    if not holdings:
        return {"fund_ratings": [], "performance_distribution": {}, "category_overlap": [], "summary": {}}

    nav_cache = await fetch_nav_data()
    result = await compute_benchmark_ratings(holdings, nav_cache)

    # Cache the result
    await db.fund_performance_cache.update_one(
        {"user_id": user_id},
        {"$set": {"user_id": user_id, "data": result, "cached_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True
    )

    return result


@api_router.get("/portfolio/deep-analytics")
async def get_deep_analytics(request: Request, portfolio_id: str = ""):
    """Advanced analytics: overexposure, fund overlap, performance cards."""
    user = await get_current_user(request)
    query = {"user_id": user["user_id"]}
    if portfolio_id:
        query["portfolio_id"] = portfolio_id
    holdings = await db.holdings.find(query, {"_id": 0}).to_list(2000)

    if not holdings:
        return {"overexposure": {}, "overlap_matrix": [], "performance_cards": []}

    # Fetch live prices for equity/ETF
    holdings, _ = await fetch_live_prices(holdings)
    # Apply SGB issue prices
    holdings, _ = apply_sgb_issue_prices(holdings)

    total_value = sum(h["quantity"] * h["current_price"] for h in holdings)
    if total_value == 0:
        return {"overexposure": {}, "overlap_matrix": [], "performance_cards": []}

    # ── 1. Overexposure Analysis ──
    # Fund house / AMC concentration
    fund_house_map = {}
    sector_concentration = {}
    asset_type_values = {}

    for h in holdings:
        val = h["quantity"] * h["current_price"]
        name = h.get("name", "")
        sector = h.get("sector", "Other")
        asset_type = h.get("asset_type", "other")

        # Extract fund house from mutual fund name
        if asset_type == "mutual_fund":
            fund_house = _extract_fund_house(name)
            fund_house_map.setdefault(fund_house, {"value": 0, "count": 0, "funds": []})
            fund_house_map[fund_house]["value"] += val
            fund_house_map[fund_house]["count"] += 1
            fund_house_map[fund_house]["funds"].append(name[:50])

        sector_concentration.setdefault(sector, {"value": 0, "count": 0, "holdings": []})
        sector_concentration[sector]["value"] += val
        sector_concentration[sector]["count"] += 1
        sector_concentration[sector]["holdings"].append(name[:40])

        asset_type_values[asset_type] = asset_type_values.get(asset_type, 0) + val

    # Build overexposure data
    fund_house_data = []
    for fh, data in sorted(fund_house_map.items(), key=lambda x: x[1]["value"], reverse=True):
        pct = (data["value"] / total_value * 100) if total_value > 0 else 0
        fund_house_data.append({
            "name": fh,
            "value": round(data["value"], 2),
            "pct": round(pct, 1),
            "count": data["count"],
            "funds": data["funds"][:5],
            "risk_level": "high" if pct > 40 else "medium" if pct > 25 else "low"
        })

    sector_data = []
    for sec, data in sorted(sector_concentration.items(), key=lambda x: x[1]["value"], reverse=True):
        pct = (data["value"] / total_value * 100) if total_value > 0 else 0
        sector_data.append({
            "name": sec,
            "value": round(data["value"], 2),
            "pct": round(pct, 1),
            "count": data["count"],
            "holdings": data["holdings"][:5],
            "risk_level": "high" if pct > 40 else "medium" if pct > 25 else "low"
        })

    # ── 2. Fund Overlap Matrix ──
    mf_holdings = [h for h in holdings if h.get("asset_type") == "mutual_fund"]
    overlap_matrix = []

    if len(mf_holdings) >= 2:
        # Group MFs by category/sector for overlap
        for i in range(len(mf_holdings)):
            for j in range(i + 1, len(mf_holdings)):
                f_a = mf_holdings[i]
                f_b = mf_holdings[j]
                overlap = _compute_fund_overlap(f_a, f_b)
                if overlap["overlap_pct"] > 0:
                    overlap_matrix.append(overlap)

        overlap_matrix.sort(key=lambda x: x["overlap_pct"], reverse=True)
        overlap_matrix = overlap_matrix[:15]  # Top 15 overlaps

    # ── 3. Performance Cards ──
    performance_cards = []
    for h in holdings:
        inv = h["quantity"] * h["buy_price"]
        cur = h["quantity"] * h["current_price"]
        abs_return = cur - inv
        pct_return = ((cur - inv) / inv * 100) if inv > 0 else 0
        weight = (cur / total_value * 100) if total_value > 0 else 0

        # Estimate CAGR if buy_date available
        cagr = None
        if h.get("buy_date") and inv > 0 and cur > 0:
            try:
                from dateutil.parser import parse as parse_date
                buy_dt = parse_date(h["buy_date"])
                now_dt = datetime.now(timezone.utc)
                years = max((now_dt - buy_dt.replace(tzinfo=timezone.utc)).days / 365.25, 0.1)
                cagr = round(((cur / inv) ** (1 / years) - 1) * 100, 1)
            except Exception:
                pass

        performance_cards.append({
            "name": h["name"][:50],
            "ticker": h.get("ticker", ""),
            "asset_type": h.get("asset_type", "other"),
            "sector": h.get("sector", "Other"),
            "quantity": h["quantity"],
            "buy_price": round(h["buy_price"], 2),
            "current_price": round(h["current_price"], 2),
            "invested": round(inv, 2),
            "current_value": round(cur, 2),
            "abs_return": round(abs_return, 2),
            "pct_return": round(pct_return, 1),
            "weight": round(weight, 1),
            "cagr": cagr,
            "nav_source": h.get("nav_source", ""),
            "nav_date": h.get("nav_date", ""),
        })

    performance_cards.sort(key=lambda x: x["pct_return"], reverse=True)

    return {
        "overexposure": {
            "fund_house": fund_house_data,
            "sector": sector_data[:15],
            "total_value": round(total_value, 2),
        },
        "overlap_matrix": overlap_matrix,
        "performance_cards": performance_cards,
    }


def _extract_fund_house(fund_name: str) -> str:
    """Extract AMC/fund house name from a mutual fund name."""
    known_houses = [
        "HDFC", "ICICI Prudential", "ICICI", "SBI", "Axis", "Kotak",
        "Aditya Birla Sun Life", "Aditya Birla", "Nippon India", "Nippon",
        "UTI", "DSP", "Mirae Asset", "Mirae", "Tata", "Canara Robeco",
        "HSBC", "Franklin Templeton", "Franklin", "Motilal Oswal", "Motilal",
        "Parag Parikh", "PPFAS", "Quant", "Bandhan", "Edelweiss",
        "Invesco", "Sundaram", "PGIM", "Baroda BNP", "Baroda",
        "JM Financial", "JM", "WhiteOak", "Navi", "Groww", "ITI",
        "360 ONE", "Bank of India", "BOI", "LIC", "Mahindra Manulife",
    ]
    name_lower = fund_name.lower()
    for house in known_houses:
        if house.lower() in name_lower:
            return house
    # Fallback: first word(s) before common keywords
    for kw in ["mutual fund", "fund", "flexi", "large", "mid", "small", "multi", "balanced", "liquid", "overnight", "debt", "index"]:
        idx = name_lower.find(kw)
        if idx > 2:
            return fund_name[:idx].strip().rstrip("-").strip()
    return fund_name.split(" ")[0] if fund_name else "Unknown"


def _compute_fund_overlap(fund_a: dict, fund_b: dict) -> dict:
    """Compute overlap between two mutual funds based on sector and category similarity."""
    name_a = fund_a.get("name", "")
    name_b = fund_b.get("name", "")
    sector_a = fund_a.get("sector", "Other").lower()
    sector_b = fund_b.get("sector", "Other").lower()

    overlap_score = 0
    reasons = []

    # Same sector = high overlap
    if sector_a == sector_b and sector_a != "other":
        overlap_score += 50
        reasons.append(f"Same category: {fund_a.get('sector', 'Other')}")

    # Extract category keywords
    categories = ["large cap", "mid cap", "small cap", "flexi cap", "multi cap",
                   "balanced", "hybrid", "debt", "liquid", "elss", "index",
                   "nifty", "sensex", "banking", "it", "pharma", "infrastructure"]

    cats_a = set(c for c in categories if c in name_a.lower())
    cats_b = set(c for c in categories if c in name_b.lower())

    shared_cats = cats_a & cats_b
    if shared_cats:
        overlap_score += min(len(shared_cats) * 25, 40)
        reasons.append(f"Shared mandate: {', '.join(shared_cats)}")

    # Same fund house = minor overlap
    house_a = _extract_fund_house(name_a)
    house_b = _extract_fund_house(name_b)
    if house_a == house_b:
        overlap_score += 10
        reasons.append(f"Same AMC: {house_a}")

    overlap_score = min(overlap_score, 95)

    return {
        "fund_a": name_a[:50],
        "fund_b": name_b[:50],
        "overlap_pct": overlap_score,
        "reasons": reasons,
        "sector_a": fund_a.get("sector", "Other"),
        "sector_b": fund_b.get("sector", "Other"),
    }


# ==================== AI CHAT ROUTES ====================

@api_router.get("/chat/sessions")
async def list_chat_sessions(request: Request):
    user = await get_current_user(request)
    sessions = await db.chat_sessions.find(
        {"user_id": user["user_id"]}, {"_id": 0}
    ).sort("updated_at", -1).to_list(50)
    return sessions

@api_router.post("/chat/sessions")
async def create_chat_session(request: Request):
    user = await get_current_user(request)
    session_doc = {
        "session_id": f"sess_{uuid.uuid4().hex[:12]}",
        "user_id": user["user_id"],
        "title": "New Conversation",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.chat_sessions.insert_one(session_doc)
    return {k: v for k, v in session_doc.items() if k != "_id"}

@api_router.delete("/chat/sessions/{session_id}")
async def delete_chat_session(request: Request, session_id: str):
    user = await get_current_user(request)
    await db.chat_sessions.delete_one({"session_id": session_id, "user_id": user["user_id"]})
    await db.chat_messages.delete_many({"session_id": session_id, "user_id": user["user_id"]})
    return {"message": "Session deleted"}

@api_router.get("/chat/messages")
async def get_chat_messages(request: Request, session_id: Optional[str] = None):
    user = await get_current_user(request)
    query = {"user_id": user["user_id"]}
    if session_id:
        query["session_id"] = session_id
    messages = await db.chat_messages.find(
        query, {"_id": 0}
    ).sort("created_at", 1).to_list(200)
    return messages

@api_router.post("/chat/send")
async def send_chat(request: Request, msg: ChatMessageInput):
    user = await get_current_user(request)
    user_id = user["user_id"]
    
    # Resolve or create session
    session_id = msg.session_id
    if not session_id:
        # Get or create a default session
        existing = await db.chat_sessions.find_one(
            {"user_id": user_id}, {"_id": 0}, sort=[("updated_at", -1)]
        )
        if existing:
            session_id = existing["session_id"]
        else:
            session_id = f"sess_{uuid.uuid4().hex[:12]}"
            await db.chat_sessions.insert_one({
                "session_id": session_id,
                "user_id": user_id,
                "title": "New Conversation",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
    
    # Save user message
    user_msg_doc = {
        "message_id": f"msg_{uuid.uuid4().hex[:12]}",
        "session_id": session_id,
        "user_id": user_id,
        "role": "user",
        "content": msg.message,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.chat_messages.insert_one(user_msg_doc)
    
    # Auto-title session from first user message
    session_msgs_count = await db.chat_messages.count_documents({"session_id": session_id, "role": "user"})
    if session_msgs_count == 1:
        title = msg.message[:50] + ("..." if len(msg.message) > 50 else "")
        await db.chat_sessions.update_one(
            {"session_id": session_id},
            {"$set": {"title": title}}
        )
    
    # Update session timestamp
    await db.chat_sessions.update_one(
        {"session_id": session_id},
        {"$set": {"updated_at": datetime.now(timezone.utc).isoformat()}}
    )
    
    # Gather portfolio context
    holdings = await db.holdings.find({"user_id": user_id}, {"_id": 0}).to_list(100)
    portfolio_context = ""
    if holdings:
        total_inv = sum(h["quantity"] * h["buy_price"] for h in holdings)
        total_cur = sum(h["quantity"] * h["current_price"] for h in holdings)
        portfolio_context = f"\n\nUser's Portfolio Summary:\n- Total Invested: ₹{total_inv:,.0f}\n- Current Value: ₹{total_cur:,.0f}\n- Returns: ₹{total_cur - total_inv:,.0f} ({((total_cur-total_inv)/total_inv*100) if total_inv > 0 else 0:.1f}%)\n- Holdings ({len(holdings)}):\n"
        for h in holdings:
            inv = h["quantity"] * h["buy_price"]
            cur = h["quantity"] * h["current_price"]
            ret = ((cur - inv) / inv * 100) if inv > 0 else 0
            portfolio_context += f"  - {h['name']} ({h['asset_type']}): {h['quantity']} units @ ₹{h['buy_price']} → ₹{h['current_price']} ({ret:.1f}%) | Sector: {h.get('sector','N/A')}\n"
    
    # Get user risk profile context
    risk_context = ""
    user_profile = await db.user_profiles.find_one({"user_id": user_id}, {"_id": 0})
    if user_profile and user_profile.get("risk_profile"):
        rp = user_profile["risk_profile"]
        risk_context = f"\n\nUser's Risk Profile: {rp.get('category', 'Unknown')} (Score: {rp.get('score', 'N/A')}/100)"
    
    system_message = f"""You are an expert AI Financial Advisor for Indian retail investors. You provide personalized, data-driven financial guidance.

Your capabilities:
- Portfolio analysis and optimization
- Risk assessment and management
- Investment recommendations (stocks, mutual funds, ETFs, bonds, gold)
- Tax planning and optimization (Indian tax laws)
- Goal-based financial planning (retirement, education, wealth growth)
- Market intelligence and trends

Formatting guidelines:
- Use **bold** for key terms and important numbers
- Use bullet points and numbered lists for recommendations
- Use tables (markdown) when comparing options
- Use headings (##) to organize long responses
- Keep responses well-structured and scannable

Content guidelines:
- Always use ₹ (INR) for currency
- Reference Indian markets (NSE/BSE), SEBI regulations
- Be specific with actionable recommendations
- Explain reasoning clearly
- Include disclaimers for investment advice
- Be conversational and friendly, not robotic
- Use data from the user's portfolio when available
{portfolio_context}{risk_context}

Disclaimer: This is AI-generated guidance for educational purposes. Always consult a SEBI-registered advisor before making investment decisions."""
    
    # Get recent chat history for this session
    recent_msgs = await db.chat_messages.find(
        {"user_id": user_id, "session_id": session_id}, {"_id": 0}
    ).sort("created_at", -1).to_list(20)
    recent_msgs.reverse()
    
    try:
        # Build conversation history for context
        history = []
        if len(recent_msgs) > 1:
            for m in recent_msgs[:-1]:
                history.append({"role": m["role"], "content": m["content"][:500]})

        ai_response = await ai_engine.chat(
            message=msg.message,
            portfolio_context=portfolio_context,
            history=history,
            session_id=f"wealth_{user_id}_{session_id}",
        )
        
    except Exception as e:
        logger.error(f"LLM error: {e}")
        ai_response = "I'm having trouble connecting to my AI engine right now. Please try again in a moment."
    
    # Save AI response
    ai_msg_doc = {
        "message_id": f"msg_{uuid.uuid4().hex[:12]}",
        "session_id": session_id,
        "user_id": user_id,
        "role": "assistant",
        "content": ai_response,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.chat_messages.insert_one(ai_msg_doc)
    
    return {
        "user_message": {k: v for k, v in user_msg_doc.items() if k != "_id"},
        "ai_message": {k: v for k, v in ai_msg_doc.items() if k != "_id"}
    }

@api_router.delete("/chat/clear")
async def clear_chat(request: Request, session_id: Optional[str] = None):
    user = await get_current_user(request)
    query = {"user_id": user["user_id"]}
    if session_id:
        query["session_id"] = session_id
    await db.chat_messages.delete_many(query)
    if session_id:
        await db.chat_sessions.delete_one({"session_id": session_id, "user_id": user["user_id"]})
    else:
        await db.chat_sessions.delete_many({"user_id": user["user_id"]})
    return {"message": "Chat cleared"}


# ==================== USER PROFILE / ONBOARDING ROUTES ====================

@api_router.get("/user/profile")
async def get_user_profile(request: Request):
    user = await get_current_user(request)
    profile = await db.user_profiles.find_one({"user_id": user["user_id"]}, {"_id": 0})
    holdings_count = await db.holdings.count_documents({"user_id": user["user_id"]})
    if not profile:
        return {"user_id": user["user_id"], "journey_type": None, "risk_profile": None, "onboarding_completed": False, "has_holdings": holdings_count > 0}
    profile["has_holdings"] = holdings_count > 0
    return profile

@api_router.post("/user/journey")
async def set_journey(request: Request, body: JourneyInput):
    user = await get_current_user(request)
    now = datetime.now(timezone.utc).isoformat()
    await db.user_profiles.update_one(
        {"user_id": user["user_id"]},
        {"$set": {
            "journey_type": body.journey_type,
            "updated_at": now,
        }, "$setOnInsert": {
            "user_id": user["user_id"],
            "risk_profile": None,
            "onboarding_completed": False,
            "created_at": now,
        }},
        upsert=True
    )
    profile = await db.user_profiles.find_one({"user_id": user["user_id"]}, {"_id": 0})
    return profile

@api_router.get("/user/risk-profile")
async def get_risk_profile(request: Request):
    user = await get_current_user(request)
    profile = await db.user_profiles.find_one({"user_id": user["user_id"]}, {"_id": 0})
    if not profile or not profile.get("risk_profile"):
        return {"risk_profile": None}
    return {"risk_profile": profile["risk_profile"]}

@api_router.post("/user/risk-profile")
async def save_risk_profile(request: Request, body: RiskProfileInput):
    user = await get_current_user(request)
    
    # Calculate risk score from answers
    score_map = {
        "market_drop": {"hold": 30, "buy_more": 10, "sell_some": 60, "sell_all": 90},
        "investment_horizon": {"less_1yr": 80, "1_3yr": 60, "3_5yr": 40, "5_10yr": 20, "10yr_plus": 10},
        "loss_tolerance": {"none": 90, "up_to_10": 60, "up_to_25": 35, "up_to_50": 15},
        "income_stability": {"very_stable": 15, "stable": 30, "moderate": 50, "unstable": 75},
        "investment_knowledge": {"beginner": 60, "intermediate": 40, "advanced": 20, "expert": 10},
        "goal_priority": {"safety": 80, "income": 55, "growth": 30, "aggressive_growth": 10},
    }
    
    total = 0
    count = 0
    answers_dict = {}
    for a in body.answers:
        answers_dict[a.question_id] = a.answer
        if a.question_id in score_map and a.answer in score_map[a.question_id]:
            total += score_map[a.question_id][a.answer]
            count += 1
    
    risk_score = round(total / count) if count > 0 else 50
    
    if risk_score <= 25:
        category = "Aggressive"
    elif risk_score <= 45:
        category = "Moderately Aggressive"
    elif risk_score <= 60:
        category = "Moderate"
    elif risk_score <= 75:
        category = "Moderately Conservative"
    else:
        category = "Conservative"
    
    risk_profile = {
        "score": risk_score,
        "category": category,
        "answers": answers_dict,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    
    now = datetime.now(timezone.utc).isoformat()
    await db.user_profiles.update_one(
        {"user_id": user["user_id"]},
        {"$set": {
            "risk_profile": risk_profile,
            "onboarding_completed": True,
            "updated_at": now,
        }, "$setOnInsert": {
            "user_id": user["user_id"],
            "journey_type": None,
            "created_at": now,
        }},
        upsert=True
    )
    
    return {"risk_profile": risk_profile}


def _generate_allocation(age: int, risk_appetite: str, horizon: str) -> dict:
    base = {
        "aggressive": {"equity": 80, "debt": 10, "gold": 5, "cash": 5},
        "moderate": {"equity": 60, "debt": 25, "gold": 10, "cash": 5},
        "conservative": {"equity": 30, "debt": 45, "gold": 15, "cash": 10},
    }
    alloc = dict(base.get(risk_appetite, base["moderate"]))
    if age > 30:
        shift = min((age - 30) * 0.5, 25)
        alloc["equity"] -= shift
        alloc["debt"] += shift * 0.7
        alloc["gold"] += shift * 0.2
        alloc["cash"] += shift * 0.1
    elif age < 25:
        boost = min((25 - age) * 1, 10)
        alloc["equity"] = min(alloc["equity"] + boost, 90)
        alloc["debt"] = max(alloc["debt"] - boost, 5)
    h_adj = {"short": -15, "medium": -5, "long": 5, "very_long": 10}
    adj = h_adj.get(horizon, 0)
    alloc["equity"] = max(min(alloc["equity"] + adj, 90), 10)
    alloc["debt"] = max(alloc["debt"] - adj * 0.6, 5)
    alloc["gold"] = max(alloc["gold"] - adj * 0.2, 2)
    alloc["cash"] = max(alloc["cash"] - adj * 0.2, 2)
    total = sum(alloc.values())
    alloc = {k: round(v / total * 100) for k, v in alloc.items()}
    diff = 100 - sum(alloc.values())
    alloc["equity"] += diff
    return alloc


def _generate_fund_recs(alloc: dict, risk_appetite: str) -> list:
    recs = []
    eq = alloc["equity"]
    if eq >= 50:
        recs.append({"category": "Nifty 50 Index Fund", "allocation_pct": round(eq * 0.4), "rationale": "Low-cost broad market exposure"})
        recs.append({"category": "Flexi Cap Fund", "allocation_pct": round(eq * 0.35), "rationale": "Diversified across market capitalizations"})
        recs.append({"category": "Mid Cap Fund", "allocation_pct": eq - round(eq * 0.4) - round(eq * 0.35), "rationale": "Higher growth potential"})
    elif eq >= 25:
        recs.append({"category": "Nifty 50 Index Fund", "allocation_pct": round(eq * 0.5), "rationale": "Stable large-cap exposure"})
        recs.append({"category": "Balanced Advantage Fund", "allocation_pct": eq - round(eq * 0.5), "rationale": "Dynamic equity-debt balance"})
    else:
        recs.append({"category": "Large Cap Index Fund", "allocation_pct": eq, "rationale": "Conservative equity allocation"})
    if alloc["debt"] > 5:
        recs.append({"category": "Short Duration Debt Fund", "allocation_pct": alloc["debt"], "rationale": "Stable returns with low volatility"})
    if alloc["gold"] > 3:
        recs.append({"category": "Sovereign Gold Bond / Gold ETF", "allocation_pct": alloc["gold"], "rationale": "Inflation hedge and portfolio diversifier"})
    if alloc["cash"] > 5:
        recs.append({"category": "Liquid Fund", "allocation_pct": alloc["cash"], "rationale": "High liquidity for emergencies"})
    return recs


@api_router.post("/user/quick-setup")
async def save_quick_setup(request: Request, body: QuickSetupInput):
    user = await get_current_user(request)
    alloc = _generate_allocation(body.age, body.risk_appetite, body.investment_horizon)
    fund_recs = _generate_fund_recs(alloc, body.risk_appetite)
    expected_return = (alloc["equity"] * 0.12 + alloc["debt"] * 0.07 + alloc["gold"] * 0.08 + alloc["cash"] * 0.04) / 100
    horizon_years = {"short": 3, "medium": 5, "long": 10, "very_long": 20}[body.investment_horizon]
    projection = None
    if body.monthly_investment and body.monthly_investment > 0:
        monthly_rate = expected_return / 12
        months = horizon_years * 12
        fv = body.monthly_investment * (((1 + monthly_rate) ** months - 1) / monthly_rate) * (1 + monthly_rate) if monthly_rate > 0 else body.monthly_investment * months
        projection = {
            "monthly_sip": body.monthly_investment,
            "years": horizon_years,
            "total_invested": round(body.monthly_investment * months),
            "projected_value": round(fv),
            "expected_annual_return": round(expected_return * 100, 1),
        }
    goal_labels = {"retirement": "retirement corpus", "house": "dream home", "education": "education fund", "travel": "travel goals", "wealth": "long-term wealth", "emergency": "emergency fund"}
    goal_label = goal_labels.get(body.goal, "financial goal")
    insights = []
    if body.risk_appetite == "aggressive":
        insights.append(f"Your aggressive risk profile allows higher equity allocation for maximum growth towards your {goal_label}.")
    elif body.risk_appetite == "moderate":
        insights.append(f"A balanced approach with steady growth towards your {goal_label}, mixing equity with stability instruments.")
    else:
        insights.append(f"Capital preservation with measured growth towards your {goal_label}, prioritizing safety.")
    if body.age < 30:
        insights.append("Your young age is your biggest advantage \u2014 time in the market beats timing the market.")
    elif body.age < 45:
        insights.append("At your age, a diversified approach balances growth with emerging responsibilities.")
    else:
        insights.append("Focus on capital preservation while maintaining some growth exposure to beat inflation.")
    if projection:
        insights.append(f"A monthly SIP of \u20b9{body.monthly_investment:,.0f} could grow to approximately \u20b9{projection['projected_value']:,.0f} in {horizon_years} years at ~{projection['expected_annual_return']}% p.a. returns.")
    quick_setup = {"age": body.age, "goal": body.goal, "risk_appetite": body.risk_appetite, "investment_horizon": body.investment_horizon, "monthly_investment": body.monthly_investment}
    starter_plan = {"allocation": alloc, "fund_recommendations": fund_recs, "projection": projection, "insights": insights, "expected_annual_return": round(expected_return * 100, 1), "horizon_years": horizon_years}
    now = datetime.now(timezone.utc).isoformat()
    await db.user_profiles.update_one(
        {"user_id": user["user_id"]},
        {"$set": {"quick_setup": quick_setup, "starter_plan": starter_plan, "updated_at": now},
         "$setOnInsert": {"user_id": user["user_id"], "created_at": now}},
        upsert=True
    )
    return {"quick_setup": quick_setup, "starter_plan": starter_plan}


@api_router.post("/user/complete-onboarding")
async def complete_onboarding(request: Request):
    user = await get_current_user(request)
    now = datetime.now(timezone.utc).isoformat()
    await db.user_profiles.update_one(
        {"user_id": user["user_id"]},
        {"$set": {"onboarding_completed": True, "updated_at": now}},
        upsert=True
    )
    return {"status": "ok", "onboarding_completed": True}



# ==================== OCR CORRECTION API (Admin) ====================

@api_router.post("/admin/ocr-correction/isin")
async def add_ocr_isin_correction(request: Request):
    """Admin endpoint: teach the OCR engine a garbled ISIN → correct ISIN mapping."""
    user = await get_current_user(request)
    whitelist = await db.whitelisted_users.find_one({"email": user["email"]}, {"_id": 0})
    if not whitelist or not whitelist.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    body = await request.json()
    garbled = body.get("garbled_isin", "").strip()
    correct = body.get("correct_isin", "").strip()
    context = body.get("context", "")
    if not garbled or not correct or len(correct) != 12:
        raise HTTPException(status_code=400, detail="Both garbled_isin and correct_isin (12 chars) required")
    from services.ocr_correction import add_isin_correction
    add_isin_correction(garbled, correct, context)
    return {"status": "ok", "message": f"Learned: {garbled} → {correct}"}


@api_router.post("/admin/ocr-correction/name")
async def add_ocr_name_correction(request: Request):
    """Admin endpoint: teach the OCR engine a garbled name → correct name + ISIN."""
    user = await get_current_user(request)
    whitelist = await db.whitelisted_users.find_one({"email": user["email"]}, {"_id": 0})
    if not whitelist or not whitelist.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    body = await request.json()
    garbled = body.get("garbled_name", "").strip()
    correct = body.get("correct_name", "").strip()
    isin = body.get("isin", "").strip()
    if not garbled or not correct:
        raise HTTPException(status_code=400, detail="Both garbled_name and correct_name required")
    from services.ocr_correction import add_name_correction
    add_name_correction(garbled, correct, isin)
    return {"status": "ok", "message": f"Learned: '{garbled}' → '{correct}'"}


@api_router.post("/admin/ocr-correction/holding")
async def correct_holding(request: Request):
    """Admin endpoint: correct a parsed holding's ISIN/name/qty/price. Feeds into ML engine."""
    user = await get_current_user(request)
    whitelist = await db.whitelisted_users.find_one({"email": user["email"]}, {"_id": 0})
    if not whitelist or not whitelist.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    body = await request.json()
    holding_id = body.get("holding_id", "")
    corrections = body.get("corrections", {})
    if not holding_id or not corrections:
        raise HTTPException(status_code=400, detail="holding_id and corrections required")
    # Get original holding
    holding = await db.holdings.find_one({"holding_id": holding_id}, {"_id": 0})
    if not holding:
        raise HTTPException(status_code=404, detail="Holding not found")
    # Apply corrections
    update_fields = {}
    if "isin" in corrections and corrections["isin"] != holding.get("ticker"):
        from services.ocr_correction import add_isin_correction
        add_isin_correction(holding.get("ticker", ""), corrections["isin"], f"Manual fix for {holding.get('name', '')}")
        update_fields["ticker"] = corrections["isin"]
    if "name" in corrections and corrections["name"] != holding.get("name"):
        from services.ocr_correction import add_name_correction
        add_name_correction(holding.get("name", ""), corrections["name"], corrections.get("isin", holding.get("ticker", "")))
        update_fields["name"] = corrections["name"]
    if "quantity" in corrections:
        update_fields["quantity"] = float(corrections["quantity"])
    if "buy_price" in corrections:
        update_fields["buy_price"] = float(corrections["buy_price"])
    if "current_price" in corrections:
        update_fields["current_price"] = float(corrections["current_price"])
    if update_fields:
        now = datetime.now(timezone.utc).isoformat()
        update_fields["corrected_at"] = now
        update_fields["corrected_by"] = user["user_id"]
        await db.holdings.update_one({"holding_id": holding_id}, {"$set": update_fields})
    return {"status": "ok", "updated_fields": list(update_fields.keys())}


@api_router.get("/admin/ocr-correction/stats")
async def get_ocr_correction_stats(request: Request):
    """Get OCR correction engine statistics."""
    user = await get_current_user(request)
    whitelist = await db.whitelisted_users.find_one({"email": user["email"]}, {"_id": 0})
    if not whitelist or not whitelist.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    from services.ocr_correction import get_correction_stats
    return get_correction_stats()


# ==================== AI INSIGHTS ROUTES ====================

@api_router.get("/insights")
async def get_insights(request: Request):
    user = await get_current_user(request)
    insights = await db.ai_insights.find(
        {"user_id": user["user_id"]}, {"_id": 0}
    ).sort("created_at", -1).to_list(20)
    return insights

@api_router.post("/insights/generate")
async def generate_insights(request: Request):
    user = await get_current_user(request)
    user_id = user["user_id"]
    
    holdings = await db.holdings.find({"user_id": user_id}, {"_id": 0}).to_list(500)
    if not holdings:
        return {"insights": [], "message": "Add holdings to generate insights"}
    
    total_inv = sum(h["quantity"] * h["buy_price"] for h in holdings)
    total_cur = sum(h["quantity"] * h["current_price"] for h in holdings)
    
    # Build portfolio summary for AI
    asset_map = {}
    sector_map = {}
    mf_names = []
    for h in holdings:
        cur = h["quantity"] * h["current_price"]
        at = h.get("asset_type", "other")
        asset_map[at] = asset_map.get(at, 0) + cur
        sec = h.get("sector", "Other")
        sector_map[sec] = sector_map.get(sec, 0) + cur
        if at == "mutual_fund":
            mf_names.append(h["name"])
    
    portfolio_text = f"Portfolio: ₹{total_inv:,.0f} invested, ₹{total_cur:,.0f} current ({((total_cur-total_inv)/total_inv*100) if total_inv > 0 else 0:.1f}% returns).\n"
    portfolio_text += f"Asset split: {', '.join(f'{k}={v/total_cur*100:.1f}%' for k,v in asset_map.items() if total_cur > 0)}\n"
    portfolio_text += f"Sectors: {', '.join(f'{k}={v/total_cur*100:.1f}%' for k,v in list(sector_map.items())[:10] if total_cur > 0)}\n"
    portfolio_text += f"Holdings ({len(holdings)}):\n"
    for h in holdings[:60]:
        ret_pct = ((h["current_price"] - h["buy_price"]) / h["buy_price"] * 100) if h["buy_price"] > 0 else 0
        portfolio_text += f"- {h['name']} ({h['asset_type']}, {h.get('sector','N/A')}): qty={h['quantity']}, ₹{h['buy_price']}→₹{h['current_price']} ({ret_pct:.1f}%)\n"
    
    try:
        analysis = await ai_engine.analyze_portfolio(
            portfolio_text,
            f"insights_{user_id}_{uuid.uuid4().hex[:6]}"
        )
        
    except Exception as e:
        logger.error(f"Insights generation error: {e}")
        analysis = {
            "insights": [{"title": "Analysis Error", "description": "Could not generate insights. Try again.", "type": "info", "impact": "medium", "effort": "low", "category": "info", "current_value": "", "target_value": "", "progress": 0}],
            "problem_distribution": [],
            "before_after": {"before": {"return_pct": 0, "risk_label": "N/A", "risk_score": 0, "expense_ratio": 0}, "after": {"return_pct": 0, "risk_label": "N/A", "risk_score": 0, "expense_ratio": 0}},
            "action_funnel": [],
            "overlap_pairs": [],
            "cost_leakage": {"annual_loss": 0, "total_invested": 0, "loss_pct": 0, "detail": ""},
            "risk_gauge": {"current": 0, "target": 0, "current_label": "N/A", "target_label": "N/A"}
        }
    
    # Save insights
    await db.ai_insights.delete_many({"user_id": user_id})
    saved_insights = []
    for insight in analysis.get("insights", []):
        doc = {
            "insight_id": f"ins_{uuid.uuid4().hex[:12]}",
            "user_id": user_id,
            "title": insight.get("title", ""),
            "description": insight.get("description", ""),
            "type": insight.get("type", "info"),
            "priority": insight.get("impact", "medium"),
            "impact": insight.get("impact", "medium"),
            "effort": insight.get("effort", "medium"),
            "category": insight.get("category", "info"),
            "current_value": insight.get("current_value", ""),
            "target_value": insight.get("target_value", ""),
            "progress": insight.get("progress", 0),
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        await db.ai_insights.insert_one(doc)
        saved_insights.append({k: v for k, v in doc.items() if k != "_id"})
    
    # Save full analysis
    analysis["insights"] = saved_insights
    await db.portfolio_analysis.delete_many({"user_id": user_id})
    await db.portfolio_analysis.insert_one({
        "user_id": user_id,
        "analysis": analysis,
        "created_at": datetime.now(timezone.utc).isoformat()
    })
    
    return analysis

@api_router.get("/insights/analysis")
async def get_analysis(request: Request):
    """Get the full portfolio analysis (insights + visualizations data)."""
    user = await get_current_user(request)
    doc = await db.portfolio_analysis.find_one({"user_id": user["user_id"]}, {"_id": 0})
    if doc and "analysis" in doc:
        return doc["analysis"]
    return None

# ==================== ROOT ====================

@api_router.get("/")
async def root():
    return {"message": "nivesh.ai API"}

# Include router and middleware
app.include_router(api_router)

app.add_middleware(RateLimitMiddleware)

_cors_env = os.environ.get('CORS_ORIGINS', '')
if _cors_env == '*':
    _cors_origins = ["https://autonomous-advisor.preview.emergentagent.com", "http://localhost:3000"]
else:
    _cors_origins = [o.strip() for o in _cors_env.split(',') if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup_seed():
    logger.info("Connected to MongoDB")
    await seed_admin_and_whitelist()


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
