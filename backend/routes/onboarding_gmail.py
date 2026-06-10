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


def _extract_vision_summary(pdf_bytes: bytes, password: str = "") -> Optional[dict]:
    """Call Vision API to extract monthly portfolio value table from CAS PDF."""
    try:
        from services.cas_summary_vision import extract_portfolio_summary
        return extract_portfolio_summary(pdf_bytes, password=password)
    except Exception as e:
        logger.warning("Vision summary extraction failed: %s", e)
        return None


def _extract_portfolio_value(raw_data: Optional[dict]) -> Optional[float]:
    """Extract total portfolio value (rupees) from casparser SDK response summary."""
    if not raw_data:
        return None
    summary = raw_data.get("summary") or {}
    total = summary.get("total_value")
    if total is not None:
        return float(total)
    # Fallback: sum across account types
    accounts = summary.get("accounts") or {}
    parts = [v.get("total_value", 0) for v in accounts.values() if isinstance(v, dict)]
    return float(sum(parts)) if parts else None


def _extract_statement_date(raw_data: Optional[dict]) -> Optional[str]:
    """Extract statement end date (ISO YYYY-MM-DD) from casparser SDK response."""
    if not raw_data:
        return None
    meta = raw_data.get("meta") or {}
    period = meta.get("statement_period") or {}
    return period.get("to") or None


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

    # ── Step 3: try each source in priority order until one parses ───
    # scan_for_cas_emails sorts by SOURCE_PRIORITY (NSDL > CDSL > CAMS >
    # KFintech). Attempt the best source first and fall back to the next when
    # a parse fails — e.g. the casparser plan may not include a given source
    # (NSDL/CDSL are add-on features) or a particular statement is unreadable.
    # Stop at the first source that yields holdings.
    logger.info(
        "auto-import: %d source(s) found (%s) — trying in priority order for %s",
        len(emails), ",".join(e.get("source", "?") for e in emails), user_id,
    )

    all_holdings: List[Dict[str, Any]] = []
    per_file: List[Dict[str, Any]] = []
    parse_errors = 0
    used_email: Optional[Dict[str, Any]] = None

    for email in emails:
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

        # Parse: prefer the OFFLINE casparser library (no subscription gate,
        # no OCR — the real CAS parser). Fall back to the hosted casparser.in
        # API only if the offline parser can't read the statement (and it's
        # not a wrong-PAN case, which neither parser can fix).
        offline_used = False
        try:
            holdings, raw_data, parse_err = cas_api_client.parse_cas_offline(content, password=pan)
            offline_used = bool(holdings)
        except Exception as e:  # noqa: BLE001
            logger.exception("parse_cas_offline crashed for %s: %s", filename, e)
            holdings, raw_data, parse_err = [], None, {
                "kind": "service", "message": "The CAS parser hit an error — try again.", "detail": str(e)[:200],
            }

        if not holdings and (parse_err or {}).get("kind") != "password":
            try:
                h2, raw2, _n2, err2 = cas_api_client.parse_cas_via_sdk_flow_with_error(content, password=pan)
            except Exception as e:  # noqa: BLE001
                logger.exception("parse_cas_via_sdk_flow crashed for %s: %s", filename, e)
                h2, raw2, err2 = [], None, {
                    "kind": "service", "message": "The CAS parser hit an error — try again.", "detail": str(e)[:200],
                }
            if h2:
                holdings, raw_data, parse_err, offline_used = h2, raw2, None, False
            elif err2:
                # Keep BOTH reasons so we can see whether the offline parser
                # failed because the lib is missing vs the format is unsupported.
                offline_detail = (parse_err or {}).get("detail", "")
                parse_err = {
                    "kind": err2.get("kind", "parse"),
                    "message": err2.get("message", "The CAS statement couldn't be read."),
                    "detail": f"offline=[{offline_detail}] api=[{err2.get('detail', '')}]"[:1500],
                }

        if not holdings:
            parse_errors += 1
            logger.warning(
                "auto-import: parse failed for %s (%s) — kind=%s detail=%s",
                filename, user_id, (parse_err or {}).get("kind"), (parse_err or {}).get("detail"),
            )
            per_file.append({
                "message_id": msg_id, "filename": filename,
                "status": "error", "error": "parse_failed",
                "error_kind": (parse_err or {}).get("kind", "parse"),
                "error_message": (parse_err or {}).get("message", "The CAS statement couldn't be read."),
                "error_detail": str((parse_err or {}).get("detail", ""))[:1500],
                "holdings_count": 0,
            })
            continue

        if offline_used:
            # Offline parser: value comes straight from the parsed holdings
            # (quantity × NAV) — accurate, no OCR. Period from the casparser dict.
            statement_period   = cas_api_client.offline_statement_period(raw_data)
            cas_total_value    = round(sum(
                (h.get("quantity") or 0) * (h.get("current_price") or 0) for h in holdings
            ), 2) or None
            cas_statement_date = None
            vision = None
        else:
            statement_period   = cas_api_client.extract_statement_period(raw_data) if raw_data else None
            cas_total_value    = _extract_portfolio_value(raw_data)
            cas_statement_date = _extract_statement_date(raw_data)
            # Vision API: extract monthly portfolio values from the CAS Summary page
            # Pass PAN as PDF password (NSDL/CAMS CAS PDFs are PAN-locked)
            vision = _extract_vision_summary(content, password=pan)
            if vision:
                if vision.get("current_value_rs"):
                    cas_total_value = float(vision["current_value_rs"])
                if vision.get("statement_date"):
                    cas_statement_date = vision["statement_date"]
        all_holdings.extend(holdings)
        used_email = email
        logger.info(
            "auto-import: parsed %s holdings from %s eCAS for %s",
            len(holdings), email.get("source", "?"), user_id,
        )
        per_file.append({
            "message_id": msg_id, "filename": filename,
            "status": "completed", "holdings_count": len(holdings),
            "source": email.get("source"),
            "statement_period": statement_period,
            "portfolio_value_rs": cas_total_value,
            "statement_date": cas_statement_date,
            "monthly_values": vision.get("monthly_values") if vision else None,
        })
        break  # first source that parses wins — don't burn the others

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
    best_file = next((f for f in per_file if f.get("status") == "completed"), None)
    statement_period    = best_file.get("statement_period") if best_file else None
    cas_portfolio_value = best_file.get("portfolio_value_rs") if best_file else None
    cas_statement_date  = best_file.get("statement_date") if best_file else None
    monthly_values      = best_file.get("monthly_values") if best_file else None
    if imported_files > 0:
        profile_update: dict = {
            "onboarding_completed": True,
            "journey_type": "existing_investor",
            "updated_at": now,
        }
        if statement_period:
            profile_update["cas_statement_period"] = statement_period
        if cas_portfolio_value is not None:
            profile_update["cas_portfolio_value_rs"] = cas_portfolio_value
        if cas_statement_date:
            profile_update["cas_statement_date"] = cas_statement_date
        if monthly_values:
            profile_update["cas_monthly_values"] = monthly_values
            logger.info(
                "gmail-import: persisting %d monthly portfolio values to MongoDB for user=%s",
                len(monthly_values), user_id,
            )
        else:
            logger.warning(
                "gmail-import: cas_monthly_values is empty/null — Vision API "
                "did not extract monthly values for user=%s (check cas_summary_vision logs)",
                user_id,
            )
        await db.user_profiles.update_one(
            {"user_id": user_id},
            {"$set": profile_update, "$setOnInsert": {"user_id": user_id, "created_at": now}},
            upsert=True,
        )
        logger.info(
            "gmail-import: profile updated for user=%s — period=%s, value=₹%s, "
            "statement_date=%s, monthly_values_count=%d",
            user_id, statement_period, cas_portfolio_value, cas_statement_date,
            len(monthly_values) if monthly_values else 0,
        )

    # Flip auto_import_enabled on so the daily 06:30 IST sweep picks up
    # future CAS emails without the user lifting a finger.
    if imported_files > 0:
        await db.gmail_tokens.update_one(
            {"user_id": user_id},
            {"$set": {"auto_import_enabled": True, "last_auto_import_at": now}},
        )

    # Auto-generate action plan after successful import so dashboard
    # action matrix is immediately populated without user having to navigate
    # to /recommendations first.
    # refresh_plan() fetches holdings + intelligence internally and saves
    # directly as status="active" (unlike generate_plan which needs args
    # and creates a preview that must be manually activated).
    if imported_files > 0:
        try:
            from services.action_plan_manager import ActionPlanManager
            plan = await ActionPlanManager().refresh_plan(user_id)
            logger.info(
                "auto-import: action plan generated for user=%s plan_id=%s actions=%d",
                user_id, plan.get("plan_id"), len(plan.get("actions") or []),
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("auto-import: plan generation failed for user=%s: %s", user_id, e)

        # Kick off NIDP sync + PRA so the Risk screen populates without manual admin action.
        import asyncio as _aio
        from routes.upload import _trigger_nidp_pipeline_background
        _aio.create_task(_trigger_nidp_pipeline_background(user_id))

    # Surface the first parse failure at the top level so the UI can react
    # (e.g. re-prompt for PAN on a "password" error) without digging into files.
    first_err = next((f for f in per_file if f.get("status") == "error"), None)
    parse_error = None
    if imported_files == 0 and first_err:
        parse_error = {
            "kind": first_err.get("error_kind", "parse"),
            "message": first_err.get("error_message", "The CAS statement couldn't be read."),
            "detail": first_err.get("error_detail", ""),
        }

    return {
        "ok": imported_files > 0,
        "scanned": len(emails),
        "source_used": (used_email or emails[0]).get("source", "unknown"),
        "sources_available": [e.get("source") for e in emails],
        "imported_files": imported_files,
        "imported_holdings": len(all_holdings),
        "parse_errors": parse_errors,
        "parse_error": parse_error,
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
        holdings, raw_data, _ = cas_api_client.parse_cas_via_sdk_flow_with_data(content, password=pan)
    except Exception as e:  # noqa: BLE001
        logger.exception("upload_cas_pdf parse crashed: %s", e)
        holdings, raw_data = [], None

    if not holdings:
        raise HTTPException(
            422,
            "Couldn't parse this CAS PDF. Check that the PAN matches and the file "
            "is a recent CAMS / KFintech / NSDL / CDSL statement.",
        )

    statement_period    = cas_api_client.extract_statement_period(raw_data) if raw_data else None
    cas_portfolio_value = _extract_portfolio_value(raw_data)
    cas_statement_date  = _extract_statement_date(raw_data)
    vision              = _extract_vision_summary(content, password=pan)
    if vision:
        if vision.get("current_value_rs"):
            cas_portfolio_value = float(vision["current_value_rs"])
        if vision.get("statement_date"):
            cas_statement_date = vision["statement_date"]
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
    if cas_portfolio_value is not None:
        profile_update["cas_portfolio_value_rs"] = cas_portfolio_value
    if cas_statement_date:
        profile_update["cas_statement_date"] = cas_statement_date
    if vision and vision.get("monthly_values"):
        profile_update["cas_monthly_values"] = vision["monthly_values"]
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
        "cas_statement_period": profile.get("cas_statement_period"),       # "Mar/2025" or null
        "cas_portfolio_value_rs": profile.get("cas_portfolio_value_rs"),   # current value in ₹ or null
        "cas_statement_date": profile.get("cas_statement_date"),           # "DD-MMM-YYYY" or null
        "cas_monthly_values": profile.get("cas_monthly_values"),           # [{month, value_rs}] or null
        # persona is stored as a dict {"persona": slug, "confidence": int, "label": str, ...}
        # — unpack so the frontend always receives plain scalar values.
        "persona":             _persona_slug(profile.get("persona")),
        "persona_confidence":  _persona_confidence(profile.get("persona")),
        "persona_label":       _persona_label(profile.get("persona")),
        "has_risk_profile":    bool(profile.get("risk_profile")),
    }


def _persona_slug(raw) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        return raw
    if isinstance(raw, dict):
        return raw.get("persona") or raw.get("slug") or raw.get("name")
    return None


def _persona_confidence(raw) -> int | None:
    if isinstance(raw, dict):
        v = raw.get("confidence")
        return int(v) if v is not None else None
    return None


def _persona_label(raw) -> str | None:
    if isinstance(raw, dict):
        return raw.get("label")
    return None
