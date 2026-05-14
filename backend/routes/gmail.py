"""Gmail auto-fetch routes."""
from fastapi import APIRouter, HTTPException, Request, BackgroundTasks
from fastapi.responses import RedirectResponse
from datetime import datetime, timezone, timedelta
import hashlib
import os
import uuid
import logging

from deps import db, get_current_user, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GMAIL_REDIRECT_URI
from helpers.parsing import parse_cas_pdf, parse_cas_pdf_with_data, save_holdings
from services.gmail_service import (
    get_authorization_url, exchange_code_for_tokens,
    get_gmail_credentials, build_gmail_service,
    scan_for_cas_emails, download_attachment,
)
from services import cas_transactions as _cas_txns
from services.cas_snapshot_engine import create_cas_snapshot
from services.cas_period_detector import detect_statement_period, detect_period_from_filename

# Where Gmail-fetched CAS PDFs are persisted on disk so users can
# re-parse with a different password without re-downloading from Gmail.
GMAIL_CAS_PDF_DIR = "/app/data/gmail_cas"

# Test user — imported PDFs are automatically saved as named fixtures under
# tests/test_data/nsdl/ahaanporwal/ so they can be used as benchmark inputs.
TEST_USER_ID = "user_e56d1d46b024"
TEST_FIXTURE_DIR = os.path.join(
    os.path.dirname(__file__), "..", "tests", "test_data", "nsdl", "ahaanporwal"
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
        logger.error("Gmail OAuth error: %s", error)
        return RedirectResponse(url="/v2/dashboard?gmail_error=denied")

    if not code or not state:
        return RedirectResponse(url="/v2/dashboard?gmail_error=missing_params")

    state_doc = await db.gmail_oauth_states.find_one({"state": state}, {"_id": 0})
    if not state_doc:
        return RedirectResponse(url="/v2/dashboard?gmail_error=invalid_state")

    expires_at = state_doc["expires_at"]
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) > expires_at:
        return RedirectResponse(url="/v2/dashboard?gmail_error=state_expired")

    user_id = state_doc["user_id"]
    code_verifier = state_doc.get("code_verifier")
    await db.gmail_oauth_states.delete_one({"state": state})

    redirect_uri = _resolve_gmail_redirect_uri(request)

    try:
        tokens = exchange_code_for_tokens(GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, redirect_uri, code, code_verifier=code_verifier)
    except Exception as e:
        logger.error("Gmail token exchange failed: %s", e)
        return RedirectResponse(url="/v2/dashboard?gmail_error=token_exchange_failed")

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
    return RedirectResponse(url="/v2/dashboard?gmail=connected")


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
        logger.error("Gmail attachment download failed: %s", e)
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

    # Persist the raw PDF bytes before kicking off the background parse.
    # Doing it inline keeps the operation atomic with the import request —
    # if the disk write fails the user gets an immediate 500 rather than
    # a silent loss inside the background task.
    file_id, file_path, file_sha256 = _persist_gmail_pdf(
        user["user_id"], content, filename
    )
    await db.gmail_imports.update_one(
        {"user_id": user["user_id"], "message_id": message_id, "attachment_id": attachment_id},
        {"$set": {
            "file_id": file_id,
            "file_path": file_path,
            "file_sha256": file_sha256,
        }},
    )

    background_tasks.add_task(
        _process_gmail_cas_background,
        content, user["user_id"], task_id, portfolio_id, password,
        message_id, attachment_id, file_id, filename,
    )

    return {"task_id": task_id, "status": "processing", "message": f"Importing {filename} from Gmail..."}


def _persist_gmail_pdf(user_id: str, content: bytes, filename: str) -> tuple[str, str, str]:
    """Write the raw PDF to /app/data/gmail_cas/<user>/<file_id>.pdf and
    return (file_id, file_path, sha256). Re-parsing with a new password
    can read the same file off disk later.
    """
    file_id = uuid.uuid4().hex[:16]
    user_dir = os.path.join(GMAIL_CAS_PDF_DIR, user_id)
    os.makedirs(user_dir, exist_ok=True)
    file_path = os.path.join(user_dir, f"{file_id}.pdf")
    with open(file_path, "wb") as f:
        f.write(content)
    sha = hashlib.sha256(content).hexdigest()
    logger.info(
        "Gmail CAS persisted: user=%s file_id=%s size=%d filename=%s",
        user_id, file_id, len(content), filename[:80],
    )
    # Archive as a named test fixture for the test user
    if user_id == TEST_USER_ID:
        try:
            os.makedirs(TEST_FIXTURE_DIR, exist_ok=True)
            safe_name = filename.replace(" ", "_").replace("/", "_")
            fixture_path = os.path.join(TEST_FIXTURE_DIR, safe_name)
            with open(fixture_path, "wb") as fx:
                fx.write(content)
            logger.info("Test fixture archived: %s", fixture_path)
        except Exception as _fx_err:
            logger.warning("Fixture archive failed (non-fatal): %s", _fx_err)
    return file_id, file_path, sha


async def _process_gmail_cas_background(
    content: bytes, user_id: str, task_id: str, portfolio_id: str, password: str,
    message_id: str, attachment_id: str, file_id: str = "", filename: str = "cas.pdf"
):
    """Background task for Gmail CAS import.

    Persists each CAS PDF as its own date-stamped portfolio snapshot via
    `create_cas_snapshot` (the same engine Client 360 uses). The snapshot
    engine auto-mirrors the latest snapshot's holdings into the live
    `holdings` table, so importing 12 monthly statements yields 12
    snapshots + the most-recent month showing as live holdings — instead
    of the previous flat-overwrite behaviour where every import wiped
    out the prior one.
    """
    try:
        await db.upload_tasks.update_one(
            {"task_id": task_id},
            {"$set": {"status": "processing", "message": "Parsing CAS PDF from Gmail with AI..."}}
        )
        holdings, raw_cas_data, raw_payload, parser_source = await parse_cas_pdf_with_data(
            content, password=password,
        )
        if not holdings:
            await db.upload_tasks.update_one(
                {"task_id": task_id},
                {"$set": {"status": "completed", "message": "No holdings found in CAS email", "count": 0}}
            )
            await db.gmail_imports.update_one(
                {"user_id": user_id, "message_id": message_id, "attachment_id": attachment_id},
                {"$set": {"status": "completed", "count": 0, "parser_source": parser_source}}
            )
            return

        for h in holdings:
            h["source"] = "email"
            h["confidence"] = 0.95

        # Period detection — read PDF text headers first, fall back to filename
        # (e.g. NSDLe-CAS_106904998_DEC_2025.PDF → 2025-12-01..2025-12-31).
        period_start, period_end = detect_statement_period(content)
        if not period_end:
            period_start, period_end = detect_period_from_filename(filename)
        logger.info(
            "Gmail CAS period detected: %s → %s for file %s (user %s)",
            period_start, period_end, filename, user_id,
        )

        # Transactions + SIPs (best-effort; a failure here must not break the snapshot)
        transactions: list = []
        sips_detected: list = []
        if raw_cas_data:
            try:
                transactions = _cas_txns.extract_transactions(raw_cas_data)
                sips_detected = _cas_txns.detect_sip_patterns(transactions)
                logger.info(
                    "Gmail CAS: %d txns / %d SIP patterns from %s",
                    len(transactions), len(sips_detected), filename,
                )
            except Exception as txn_err:  # noqa: BLE001
                logger.warning("Gmail CAS: transaction extraction failed: %s", txn_err)

        # Mirror the raw parsed payload so a re-parse never has to call
        # the parser again (saves Document AI / Claude budget).
        if raw_payload is not None and file_id:
            try:
                await db.cas_parsed_responses.update_one(
                    {"file_id": file_id},
                    {"$set": {
                        "file_id": file_id,
                        "user_id": user_id,
                        "source": "gmail",
                        "filename": filename,
                        "parser_source": parser_source,
                        "holdings_count": len(holdings),
                        "transactions_count": len(transactions),
                        "sips_count": len(sips_detected),
                        "period_start": period_start,
                        "period_end": period_end,
                        "raw_payload": raw_payload,
                        "normalized_for_txns": raw_cas_data,
                        "stored_at": datetime.now(timezone.utc).isoformat(),
                    }},
                    upsert=True,
                )
            except Exception as p_err:  # noqa: BLE001
                logger.warning("Gmail CAS: persist parsed response failed: %s", p_err)

        # Persist as a date-stamped snapshot. The engine itself mirrors
        # the holdings into the live `holdings` table when this is the
        # latest snapshot.
        snap = await create_cas_snapshot(
            user_id=user_id,
            holdings=holdings,
            transactions=transactions,
            sips_detected=sips_detected,
            period_start=period_start,
            period_end=period_end,
            cas_file_id=file_id,
            cas_filename=filename,
        )
        count = snap.get("holdings_count", len(holdings))
        snap_date = snap.get("snapshot_date")

        # Persist transactions + SIPs to their canonical collections so
        # /api/portfolio/transactions and /api/portfolio/sips keep working.
        if raw_cas_data and transactions:
            try:
                txn_result = await _cas_txns.persist_transactions_and_sips(
                    db, user_id, raw_cas_data, source="CAS_PDF",
                )
                logger.info("Gmail CAS: persisted txns/SIPs: %s", txn_result)
            except Exception as txn_err:  # noqa: BLE001
                logger.warning("Gmail CAS: txn persistence failed: %s", txn_err)

        # Bust the fund-performance cache so the dashboard recomputes
        await db.fund_performance_cache.delete_many({"user_id": user_id})

        # Save the password that worked so the daily auto-import job can
        # decrypt future monthly statements without re-prompting the user.
        # TODO: encrypt at rest (Fernet + SECRETS_ENCRYPTION_KEY).
        if password:
            await db.gmail_tokens.update_one(
                {"user_id": user_id},
                {"$set": {
                    "cas_password": password,
                    "cas_password_saved_at": datetime.now(timezone.utc).isoformat(),
                    "auto_import_enabled": True,
                }},
            )

        msg = f"{count} holdings imported from {filename} (snapshot {snap_date})"
        await db.upload_tasks.update_one(
            {"task_id": task_id},
            {"$set": {
                "status": "completed",
                "message": msg,
                "count": count,
                "snapshot_date": snap_date,
            }},
        )
        await db.gmail_imports.update_one(
            {"user_id": user_id, "message_id": message_id, "attachment_id": attachment_id},
            {"$set": {
                "status": "completed",
                "count": count,
                "transactions_count": len(transactions),
                "parser_source": parser_source,
                "snapshot_date": snap_date,
            }},
        )
    except HTTPException as he:
        error_msg = he.detail if hasattr(he, 'detail') else str(he)
        await db.upload_tasks.update_one(
            {"task_id": task_id},
            {"$set": {"status": "error", "message": error_msg}}
        )
        await db.gmail_imports.update_one(
            {"user_id": user_id, "message_id": message_id, "attachment_id": attachment_id},
            {"$set": {"status": "error", "error": error_msg}}
        )
    except Exception as e:
        error_msg = str(e)
        # Surface budget exhaustion as its own clear message — by class
        # name so we don't have to import BudgetExceededError just to
        # check it (and so this works even if it's defined in a different
        # provider module across versions).
        if e.__class__.__name__ == "BudgetExceededError" or "budget" in error_msg.lower():
            error_msg = "AI parsing budget exhausted — please retry tomorrow or contact support."
        elif "password" in error_msg.lower() or "decrypt" in error_msg.lower():
            error_msg = "PDF is password-protected. Please provide the password."
        logger.warning("Gmail CAS background task failed: %s", e)
        await db.upload_tasks.update_one(
            {"task_id": task_id},
            {"$set": {"status": "error", "message": error_msg}}
        )
        await db.gmail_imports.update_one(
            {"user_id": user_id, "message_id": message_id, "attachment_id": attachment_id},
            {"$set": {"status": "error", "error": error_msg}}
        )


async def _save_holdings_with_dedup(user_id: str, parsed: list, source_label: str, task_id: str, portfolio_id: str):
    """Save holdings from Gmail CAS — replaces all existing holdings."""
    delete_query = {"user_id": user_id}
    if portfolio_id:
        delete_query["portfolio_id"] = portfolio_id
    old_count = await db.holdings.count_documents(delete_query)
    await db.holdings.delete_many(delete_query)
    logger.info("Gmail CAS import: cleared %s old holdings for user %s", old_count, user_id)

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
