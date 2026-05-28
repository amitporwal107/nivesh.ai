"""
Onboarding Gmail flow — fully server-wrapped, no third-party SDK widget.

Modelled on `client_cas_invite.py` (the advisor → client invite flow which
is already fully Nivesh-branded), but operates on the logged-in user's
own session instead of a public invite token. The OAuth handshake reuses
the existing `/api/gmail/connect` + `/api/oauth/gmail/callback` pair
(see `routes/gmail.py`) — those store the user's Gmail tokens in
`db.gmail_tokens` exactly the way the rest of the platform expects.

What this module adds:
  POST /api/onboarding/pan          — capture PAN on the pitch screen
                                       (used to unlock CAS PDFs later)
  POST /api/onboarding/gmail/auto-import
                                     — after OAuth callback returns the
                                       user to the onboarding page, this
                                       single call scans Gmail, downloads
                                       every matched CAS attachment,
                                       parses each via casparser.in REST
                                       API (server-side, no popup), and
                                       persists holdings.

Everything user-facing is Nivesh-branded — the casparser.in service is
only ever invoked server-to-server.
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from deps import db, get_current_user
from helpers.parsing import save_holdings
from helpers.upload_validation import validate_upload
from services import cas_api_client
from services.gmail_service import (
    SOURCE_PRIORITY,
    build_gmail_service,
    download_attachment,
    get_gmail_credentials,
    scan_for_cas_emails,
)

MAX_PDF_BYTES = 25 * 1024 * 1024  # 25 MB

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/onboarding", tags=["onboarding-gmail"])


PAN_REGEX = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class PanInput(BaseModel):
    pan: str = Field(..., min_length=10, max_length=10)


@router.post("/pan")
async def save_pan(payload: PanInput, request: Request) -> Dict[str, Any]:
    """Stash the user's PAN on their profile. The CAS PDFs CAMS/KFin
    deliver via Gmail are PAN-locked; the auto-import step needs this to
    unlock each statement. Stored in `user_profiles.cas_password` (same
    field the auto-import scheduler reads)."""
    pan = (payload.pan or "").strip().upper()
    if not PAN_REGEX.match(pan):
        raise HTTPException(400, "PAN format must be ABCDE1234F")

    user = await get_current_user(request)
    now = _now_iso()
    await db.user_profiles.update_one(
        {"user_id": user["user_id"]},
        {
            "$set": {"pan": pan, "cas_password": pan, "updated_at": now},
            "$setOnInsert": {"user_id": user["user_id"], "created_at": now},
        },
        upsert=True,
    )
    # Mirror on the gmail_tokens doc too so the auto-import scheduler
    # (services.gmail_auto_import) finds the password on its standard path.
    await db.gmail_tokens.update_one(
        {"user_id": user["user_id"]},
        {"$set": {"cas_password": pan, "pan_saved_at": now}},
        upsert=False,
    )
    return {"ok": True}


@router.post("/gmail/auto-import")
async def gmail_auto_import(request: Request) -> Dict[str, Any]:
    """Single-call orchestrator. Assumes:
      • user already completed Google OAuth (tokens are in db.gmail_tokens)
      • user already submitted their PAN via /api/onboarding/pan

    Steps:
      1. Build Gmail service from stored tokens.
      2. Scan inbox for CAS emails (CAMS, KFintech, NSDL templates).
      3. For each matched email + first PDF attachment:
            - download bytes via Gmail API
            - parse via casparser.in REST API (server-side, no widget)
            - collect holdings
      4. Persist via save_holdings(user_id, holdings, file_type="gmail_cas")
         — this replaces existing holdings (CAS is authoritative).
      5. Log per-attachment outcomes in `gmail_imports`.
      6. Mark onboarding complete on success.
    """
    user = await get_current_user(request)
    user_id = user["user_id"]

    token_doc = await db.gmail_tokens.find_one({"user_id": user_id}, {"_id": 0})
    if not token_doc:
        raise HTTPException(400, "Gmail not connected — complete the OAuth step first.")

    profile = await db.user_profiles.find_one({"user_id": user_id}, {"_id": 0}) or {}
    pan = (profile.get("pan") or profile.get("cas_password") or token_doc.get("cas_password") or "").upper()
    # PAN is the standard password for CAMS/KFin CAS PDFs. We let the
    # request proceed without one — the parser will simply fail per-file
    # and we'll surface a friendly "PAN needed" response.
    if not pan:
        raise HTTPException(400, "PAN missing — submit /api/onboarding/pan first.")

    # ── Step 1+2: build service, scan inbox ──────────────────────────
    try:
        creds = get_gmail_credentials(token_doc)
        service = build_gmail_service(creds)
        # Refresh persisted token if Google rotated it during build.
        if creds.token != token_doc.get("access_token"):
            await db.gmail_tokens.update_one(
                {"user_id": user_id},
                {"$set": {
                    "access_token": creds.token,
                    "expires_at": (
                        creds.expiry.replace(tzinfo=timezone.utc).isoformat()
                        if creds.expiry else None
                    ),
                }},
            )
        emails = scan_for_cas_emails(service, max_results=30)
    except Exception as e:  # noqa: BLE001
        logger.error("onboarding gmail scan failed for %s: %s", user_id, e)
        msg = str(e).lower()
        if "invalid_grant" in msg or "token" in msg:
            await db.gmail_tokens.delete_one({"user_id": user_id})
            raise HTTPException(401, "Gmail session expired — please reconnect.") from e
        raise HTTPException(500, f"Gmail scan failed: {e}") from e

    if not emails:
        return {
            "ok": True,
            "scanned": 0,
            "imported_files": 0,
            "imported_holdings": 0,
            "files": [],
            "message": "No CAS emails found in this Gmail account.",
        }

    # ── Step 3: pick the single best email (highest-priority source) ──
    # scan_for_cas_emails returns emails sorted by SOURCE_PRIORITY so the
    # first item is already the preferred source (NSDL > CDSL > CAMS > KFintech).
    best_email = emails[0]
    logger.info(
        "auto-import: using %s email — '%s' (%s); %d other source(s) found but skipped",
        best_email.get("source", "unknown"),
        best_email.get("subject", "")[:50],
        best_email.get("date", "")[:20],
        len(emails) - 1,
    )

    all_holdings: List[Dict[str, Any]] = []
    per_file: List[Dict[str, Any]] = []
    parse_errors = 0

    for email in [best_email]:
        msg_id = email.get("message_id")
        first_att = (email.get("attachments") or [{}])[0]
        att_id = email.get("attachment_id") or first_att.get("attachment_id")
        filename = (
            email.get("filename")
            or first_att.get("filename")
            or f"CAS-{email.get('date') or msg_id}.pdf"
        )
        if not msg_id or not att_id:
            per_file.append({
                "message_id": msg_id, "filename": filename,
                "status": "skipped", "reason": "no_attachment",
            })
            continue

        try:
            content = download_attachment(service, msg_id, att_id)
        except Exception as e:  # noqa: BLE001
            logger.warning("download_attachment failed for %s/%s: %s", msg_id, att_id, e)
            per_file.append({
                "message_id": msg_id, "filename": filename,
                "status": "error", "error": "download_failed",
            })
            continue

        # Server-side parse. parse_cas_via_api returns [] on any failure
        # (bad password, scanned PDF too large, API down, etc.).
        try:
            holdings, raw_data, _ = cas_api_client.parse_cas_via_api_with_data(content, password=pan)
        except Exception as e:  # noqa: BLE001
            logger.exception("parse_cas_via_api crashed for %s: %s", filename, e)
            holdings, raw_data = [], None

        if not holdings:
            parse_errors += 1
            per_file.append({
                "message_id": msg_id, "filename": filename,
                "status": "error", "error": "parse_failed",
                "holdings_count": 0,
            })
            continue

        statement_period = cas_api_client.extract_statement_period(raw_data) if raw_data else None
        all_holdings.extend(holdings)
        per_file.append({
            "message_id": msg_id, "filename": filename,
            "status": "completed", "holdings_count": len(holdings),
            "statement_period": statement_period,
        })

    # ── Step 4: persist ──────────────────────────────────────────────
    if all_holdings:
        task_id = f"onboard_gmail_{uuid.uuid4().hex[:10]}"
        await save_holdings(user_id, all_holdings, file_type="gmail_cas", task_id=task_id)

    # ── Step 5: log imports ──────────────────────────────────────────
    now = _now_iso()
    for f in per_file:
        if f["status"] != "completed":
            continue
        try:
            await db.gmail_imports.insert_one({
                "user_id": user_id,
                "message_id": f["message_id"],
                "filename": f["filename"],
                "count": f["holdings_count"],
                "status": "completed",
                "source": "onboarding_gmail",
                "imported_at": now,
            })
        except Exception as e:  # noqa: BLE001
            logger.warning("gmail_imports insert failed: %s", e)

    # ── Step 6: mark onboarding complete if anything imported ────────
    imported_files = sum(1 for f in per_file if f["status"] == "completed")
    statement_period = next(
        (f["statement_period"] for f in per_file if f.get("statement_period")), None
    )
    if imported_files > 0:
        profile_update: dict = {
            "onboarding_completed": True,
            "journey_type": "existing_investor",
            "updated_at": now,
        }
        if statement_period:
            profile_update["cas_statement_period"] = statement_period
        await db.user_profiles.update_one(
            {"user_id": user_id},
            {"$set": profile_update, "$setOnInsert": {"user_id": user_id, "created_at": now}},
            upsert=True,
        )

    # Flip auto_import_enabled on so the daily 06:30 IST sweep picks up
    # future CAS emails without the user lifting a finger.
    if imported_files > 0:
        await db.gmail_tokens.update_one(
            {"user_id": user_id},
            {"$set": {"auto_import_enabled": True, "last_auto_import_at": now}},
        )

    return {
        "ok": imported_files > 0,
        "scanned": len(emails),
        "source_used": best_email.get("source", "unknown"),
        "sources_available": [e.get("source") for e in emails],
        "imported_files": imported_files,
        "imported_holdings": len(all_holdings),
        "parse_errors": parse_errors,
        "files": per_file,
    }


@router.post("/upload-cas")
async def upload_cas_pdf(request: Request, file: UploadFile = File(...)) -> Dict[str, Any]:
    """Server-wrapped CAS PDF upload — same parsing engine as the Gmail
    auto-import path, but the bytes come from the user's file picker
    instead of Gmail. Returns the imported holdings summary.

    Reuses the PAN saved via /api/onboarding/pan as the unlock password.
    If parsing fails (wrong PAN, scanned PDF too large, etc.) returns 422
    so the UI can prompt the user to re-enter PAN or pick a different
    file — no third-party widget required.
    """
    user = await get_current_user(request)
    user_id = user["user_id"]
    filename = (file.filename or "cas.pdf").lower()
    if not filename.endswith(".pdf"):
        raise HTTPException(415, "Only CAS PDF files are supported on this endpoint.")

    content = file.file.read()
    validate_upload(content, filename)
    if len(content) > MAX_PDF_BYTES:
        raise HTTPException(413, "PDF too large — max 25 MB.")

    profile = await db.user_profiles.find_one({"user_id": user_id}, {"_id": 0}) or {}
    pan = (profile.get("pan") or profile.get("cas_password") or "").upper()
    if not pan:
        raise HTTPException(400, "PAN missing — submit /api/onboarding/pan first.")

    try:
        holdings, raw_data, _ = cas_api_client.parse_cas_via_api_with_data(content, password=pan)
    except Exception as e:  # noqa: BLE001
        logger.exception("upload_cas_pdf parse crashed: %s", e)
        holdings, raw_data = [], None

    if not holdings:
        raise HTTPException(
            422,
            "Couldn't parse this CAS PDF. Check that the PAN matches and the file "
            "is a recent CAMS / KFintech / NSDL / CDSL statement.",
        )

    statement_period = cas_api_client.extract_statement_period(raw_data) if raw_data else None
    task_id = f"onboard_upload_{uuid.uuid4().hex[:10]}"
    await save_holdings(user_id, holdings, file_type="cas_pdf", task_id=task_id)

    now = _now_iso()
    profile_update: dict = {
        "onboarding_completed": True,
        "journey_type": "existing_investor",
        "updated_at": now,
    }
    if statement_period:
        profile_update["cas_statement_period"] = statement_period
    await db.user_profiles.update_one(
        {"user_id": user_id},
        {"$set": profile_update, "$setOnInsert": {"user_id": user_id, "created_at": now}},
        upsert=True,
    )
    return {
        "ok": True,
        "imported_holdings": len(holdings),
        "statement_period": statement_period,
        "filename": filename,
    }


@router.get("/state")
async def onboarding_state(request: Request) -> Dict[str, Any]:
    """Lightweight bootstrap for the wrapped onboarding view. Tells the
    frontend which step to mount (capture PAN vs. resume after OAuth)."""
    user = await get_current_user(request)
    profile = await db.user_profiles.find_one({"user_id": user["user_id"]}, {"_id": 0}) or {}
    token_doc = await db.gmail_tokens.find_one({"user_id": user["user_id"]}, {"_id": 0})
    return {
        "onboarding_completed": bool(profile.get("onboarding_completed")),
        "pan_on_file": bool(profile.get("pan") or profile.get("cas_password")),
        "gmail_connected": bool(token_doc),
        "cas_statement_period": profile.get("cas_statement_period"),  # "Mar/2025" or null
    }
