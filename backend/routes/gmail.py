"""Gmail auto-fetch routes."""
from fastapi import APIRouter, HTTPException, Request, BackgroundTasks
from fastapi.responses import RedirectResponse
from datetime import datetime, timezone, timedelta
import uuid
import logging

from deps import db, get_current_user, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GMAIL_REDIRECT_URI
from helpers.parsing import parse_cas_pdf, save_holdings
from services.gmail_service import (
    get_authorization_url, exchange_code_for_tokens,
    get_gmail_credentials, build_gmail_service,
    scan_for_cas_emails, download_attachment,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


def _resolve_gmail_redirect_uri(request: Request) -> str:
    """Build the OAuth redirect URI.

    Priority:
      1. `GMAIL_REDIRECT_URI` env/secret override (explicit production value)
      2. Dynamic construction from the incoming request's base URL
         → works across preview, custom domains, and production without
         requiring a per-environment override.
    """
    if GMAIL_REDIRECT_URI:
        return GMAIL_REDIRECT_URI
    # `request.base_url` includes trailing slash; rstrip to normalise
    base = str(request.base_url).rstrip("/")
    return f"{base}/api/oauth/gmail/callback"


@router.get("/gmail/connect")
async def gmail_connect(request: Request):
    """Start Gmail OAuth flow."""
    user = await get_current_user(request)

    redirect_uri = _resolve_gmail_redirect_uri(request)

    state = f"{user['user_id']}_{uuid.uuid4().hex[:8]}"
    await db.gmail_oauth_states.insert_one({
        "state": state,
        "user_id": user["user_id"],
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

    if error:
        logger.error(f"Gmail OAuth error: {error}")
        return RedirectResponse(url="/dashboard?gmail_error=denied")

    if not code or not state:
        return RedirectResponse(url="/dashboard?gmail_error=missing_params")

    state_doc = await db.gmail_oauth_states.find_one({"state": state}, {"_id": 0})
    if not state_doc:
        return RedirectResponse(url="/dashboard?gmail_error=invalid_state")

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

    redirect_uri = _resolve_gmail_redirect_uri(request)

    try:
        tokens = exchange_code_for_tokens(GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, redirect_uri, code, code_verifier=code_verifier)
    except Exception as e:
        logger.error(f"Gmail token exchange failed: {e}")
        return RedirectResponse(url="/dashboard?gmail_error=token_exchange_failed")

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
        logger.error(f"Gmail scan failed: {e}")
        if "invalid_grant" in str(e).lower() or "token" in str(e).lower():
            await db.gmail_tokens.delete_one({"user_id": user["user_id"]})
            raise HTTPException(status_code=401, detail="Gmail session expired. Please reconnect Gmail.")
        raise HTTPException(status_code=500, detail=f"Gmail scan failed: {str(e)}")


@router.post("/gmail/import")
async def gmail_import(request: Request, background_tasks: BackgroundTasks):
    """Import a specific CAS email attachment."""
    user = await get_current_user(request)
    body = await request.json()
    message_id = body.get("message_id")
    attachment_id = body.get("attachment_id")
    filename = body.get("filename", "cas.pdf")
    password = body.get("password", "")
    portfolio_id = body.get("portfolio_id", "")

    if not message_id or not attachment_id:
        raise HTTPException(status_code=400, detail="message_id and attachment_id required")

    existing = await db.gmail_imports.find_one({
        "user_id": user["user_id"],
        "message_id": message_id,
        "attachment_id": attachment_id,
    })
    if existing and existing.get("status") == "completed":
        holdings_exist = await db.holdings.count_documents({"user_id": user["user_id"]})
        if holdings_exist > 0:
            raise HTTPException(status_code=409, detail="This attachment has already been imported")
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

        for h in parsed:
            h["source"] = "email"
            h["confidence"] = 0.95

        await _save_holdings_with_dedup(user_id, parsed, "Gmail CAS", task_id, portfolio_id)

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
    """Save holdings from Gmail CAS — replaces all existing holdings."""
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

    await db.fund_performance_cache.delete_many({"user_id": user_id})

    # Background enrichment: Groww stock scraper + MF queue seed
    import asyncio as _asyncio
    from helpers.parsing import _enrich_after_upload as _enrich
    _asyncio.create_task(_enrich(user_id, [
        {"asset_type": h.get("asset_type")} for h in saved_holdings
    ]))
