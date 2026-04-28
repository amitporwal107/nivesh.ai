"""Client CAS Invite — public shareable link flow.

Use case: the MFD is at their desk; their client is on a different
machine. The MFD cannot touch the client's Gmail directly, so we
generate a per-profile invite token, the MFD WhatsApps/emails the link
to the client, the client opens it on their own device, signs in to
their Gmail, we scan the last 12 months of CAS emails, the client
picks which to import + confirms PAN+DOB to unlock the PDFs, and we
parse + attach holdings to that profile's shadow_user_id.

Two route groups:
  1. /api/mfd/profiles/{profile_id}/cas-invite(s)  — MFD-authenticated
  2. /api/public/cas-invite/{token}/...             — NO auth (client-facing)

DB collection: `client_cas_invites`
{
  invite_token        : str (uuid hex, 32 chars)
  workspace_id        : str
  profile_id          : str
  created_by_user_id  : str  # the MFD's user_id
  created_at          : iso
  expires_at          : iso  # 7 days
  status              : str  # PENDING | AUTHORIZED | COMPLETED | EXPIRED | REVOKED
  client_email        : str?  # captured after OAuth
  authorized_at       : iso?
  completed_at        : iso?
  oauth_tokens        : dict?  # stored scoped to THIS invite only
  processed_files     : [{message_id, filename, holdings_count, imported_at, status}]
}
"""
from __future__ import annotations
import hashlib
import asyncio
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Request, BackgroundTasks, UploadFile, File, Form
from fastapi.responses import RedirectResponse, FileResponse
from pydantic import BaseModel, Field

from deps import db, get_current_user, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GMAIL_REDIRECT_URI
from services import mfd_workspace
from services.gmail_service import (
    get_authorization_url, exchange_code_for_tokens,
    get_gmail_credentials, build_gmail_service,
    scan_for_cas_emails, download_attachment,
)
from helpers.parsing import parse_cas_pdf, parse_cas_pdf_with_data, save_holdings
from services.cas_period_detector import detect_statement_period, detect_period_from_filename
from services.cas_snapshot_engine import create_cas_snapshot
from services import cas_transactions as _cas_txns

logger = logging.getLogger(__name__)

mfd_router = APIRouter(prefix="/api/mfd", tags=["cas-invite-mfd"])
public_router = APIRouter(prefix="/api/public/cas-invite", tags=["cas-invite-public"])

INVITE_TTL_HOURS = 24  # 24h expiry per PRD — short urgency window, MFD regenerates on demand

# ── Raw CAS PDF storage ────────────────────────────────────────────────
# Persist client-uploaded CAS PDFs so the MFD can: (a) audit what the
# client shared, (b) re-parse a file with a custom password if the
# automated parse failed (NSDL password mismatches are common).
CAS_UPLOAD_ROOT = Path(os.environ.get("CAS_UPLOAD_DIR", "/app/data/cas_uploads"))
CAS_UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
MAX_CAS_PDF_BYTES = 25 * 1024 * 1024  # 25 MB hard cap


def _cas_storage_path(invite_token: str, file_id: str) -> Path:
    folder = CAS_UPLOAD_ROOT / invite_token
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{file_id}.pdf"


def _save_cas_bytes(invite_token: str, content: bytes) -> dict:
    """Persist raw CAS PDF bytes to disk. Returns metadata dict to
    embed in `processed_files`. Computes sha256 hash so dedupe is
    trivial in future."""
    file_id = uuid.uuid4().hex
    sha = hashlib.sha256(content).hexdigest()
    path = _cas_storage_path(invite_token, file_id)
    path.write_bytes(content)
    return {
        "file_id":    file_id,
        "file_path":  str(path),
        "file_size":  len(content),
        "file_sha256": sha,
        "stored_at":  _now_iso(),
    }


def _delete_cas_file(file_path: Optional[str]) -> bool:
    if not file_path:
        return False
    try:
        p = Path(file_path)
        if p.exists() and CAS_UPLOAD_ROOT in p.parents:
            p.unlink()
            return True
    except Exception as e:  # noqa: BLE001
        logger.warning(f"cas file delete failed: {e}")
    return False


# ── Helpers ────────────────────────────────────────────────────────────
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _expiry_iso(hours: int = INVITE_TTL_HOURS) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


async def _is_expired(invite: dict) -> bool:
    exp = invite.get("expires_at")
    if not exp:
        return False
    try:
        dt = datetime.fromisoformat(exp)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) > dt
    except Exception:  # noqa: BLE001
        return False


async def _get_invite_or_404(token: str) -> dict:
    inv = await db.client_cas_invites.find_one({"invite_token": token}, {"_id": 0})
    if not inv:
        raise HTTPException(404, "Invite not found or has been revoked")
    if inv.get("status") == "REVOKED" or inv.get("is_active") is False:
        raise HTTPException(410, {
            "detail": "Invite has been revoked by the advisor",
            "advisor_name": inv.get("advisor_name"),
            "advisor_mobile": inv.get("advisor_mobile"),
            "advisor_firm": inv.get("advisor_firm"),
            "reason": "revoked",
        })
    if await _is_expired(inv):
        if inv.get("status") != "EXPIRED":
            await db.client_cas_invites.update_one(
                {"invite_token": token}, {"$set": {"status": "EXPIRED", "is_active": False}},
            )
        raise HTTPException(410, {
            "detail": "Invite has expired — please request a new one from your advisor",
            "advisor_name": inv.get("advisor_name"),
            "advisor_mobile": inv.get("advisor_mobile"),
            "advisor_firm": inv.get("advisor_firm"),
            "reason": "expired",
        })
    return inv


def _resolve_redirect_uri(request: Request) -> str:
    """Client OAuth redirect URI. We REUSE the existing whitelisted
    `/api/oauth/gmail/callback` endpoint (which dispatches to our
    invite handler when it sees an `invite_*` state prefix).

    Priority mirrors `gmail._resolve_gmail_redirect_uri`:
      1. GMAIL_REDIRECT_URI env override
      2. X-Forwarded-Host (public hostname set by ingress)
      3. request.base_url (cluster-internal — works only in local dev)
    """
    if GMAIL_REDIRECT_URI:
        return GMAIL_REDIRECT_URI
    fwd_host = request.headers.get("x-forwarded-host") or request.headers.get("host")
    fwd_proto = request.headers.get("x-forwarded-proto", "https")
    if fwd_host:
        return f"{fwd_proto}://{fwd_host}/api/oauth/gmail/callback"
    base = str(request.base_url).rstrip("/")
    return f"{base}/api/oauth/gmail/callback"


# ── MFD-authenticated routes ───────────────────────────────────────────
class InviteCreateRequest(BaseModel):
    ttl_hours: Optional[int] = Field(default=INVITE_TTL_HOURS, ge=1, le=168)
    client_name: Optional[str] = Field(default=None, max_length=120)
    client_mobile: Optional[str] = Field(default=None, max_length=20)
    client_email: Optional[str] = Field(default=None, max_length=255)
    regenerate: bool = Field(default=False, description="If True, deactivate any existing active invite for this profile before issuing a new one.")


@mfd_router.post("/profiles/{profile_id}/cas-invite")
async def create_invite(profile_id: str, payload: InviteCreateRequest, request: Request):
    """Generate a new client CAS invite link. Returns the full URL the
    MFD can copy + share. If `regenerate=True`, any prior active invite
    on this profile is deactivated atomically."""
    user = await get_current_user(request)
    uid = user.get("_session_user_id") or user["user_id"]
    prof = await db.profiles.find_one({"profile_id": profile_id}, {"_id": 0})
    if not prof:
        raise HTTPException(404, "Profile not found")
    # Ownership check — the profile must belong to a workspace owned by the MFD
    ws = await db.workspaces.find_one(
        {"workspace_id": prof["workspace_id"], "owner_user_id": uid}, {"_id": 0},
    )
    if not ws:
        raise HTTPException(403, "You don't own this profile's workspace")

    # ── Regenerate semantics: deactivate ANY currently-active invite on
    # this profile before issuing a new one. Matches the PRD rule:
    # "Old invite → inactive, New invite → fresh 24h expiry".
    if payload.regenerate:
        await db.client_cas_invites.update_many(
            {"profile_id": profile_id, "is_active": True},
            {"$set": {"is_active": False, "status": "REVOKED", "oauth_tokens": None}},
        )

    token = uuid.uuid4().hex
    ttl = payload.ttl_hours or INVITE_TTL_HOURS
    # Advisor identity — prefer the onboarding-captured fields on the
    # workspace; fall back to the user doc, then fall back to firm_name.
    advisor = await db.users.find_one({"user_id": uid}, {"_id": 0, "name": 1, "email": 1, "full_name": 1, "mobile": 1, "phone": 1})
    advisor_name = (
        ws.get("advisor_name")
        or (advisor or {}).get("full_name")
        or (advisor or {}).get("name")
        or ws.get("firm_name")
        or "Your advisor"
    )
    advisor_email = (
        ws.get("advisor_email")
        or (advisor or {}).get("email")
    )
    advisor_mobile = (
        ws.get("advisor_mobile")
        or (advisor or {}).get("mobile")
        or (advisor or {}).get("phone")
    )
    doc = {
        "invite_token": token,
        "workspace_id": prof["workspace_id"],
        "profile_id": profile_id,
        "profile_name": payload.client_name or prof.get("name"),
        "advisor_name": advisor_name,
        "advisor_email": advisor_email,
        "advisor_mobile": advisor_mobile,
        "advisor_firm": ws.get("firm_name"),
        "created_by_user_id": uid,
        "created_at": _now_iso(),
        "expires_at": _expiry_iso(ttl),
        "is_active": True,
        "status": "PENDING",
        # Pre-filled client contact info. Explicit payload wins; else
        # fall back to whatever was stored on the profile (captured at
        # AddClient time).
        "client_name_prefill":   payload.client_name   or prof.get("name"),
        "client_mobile_prefill": payload.client_mobile or prof.get("mobile"),
        "client_email_prefill":  payload.client_email  or prof.get("email"),
        "processed_files": [],
    }
    await db.client_cas_invites.insert_one(doc)

    # Public invite URL must be externally reachable by the client.
    # Prefer the request's Origin (set by the browser when the MFD
    # triggered this from the frontend) over `base_url` (which may
    # be the cluster-internal hostname behind the ingress).
    base = (
        request.headers.get("origin")
        or request.headers.get("referer", "").split("/cas-connect")[0].rstrip("/")
        or str(request.base_url).rstrip("/")
    )
    # If referer got us a URL with /dashboard etc, strip path
    if base and "//" in base:
        scheme_host = base.split("/", 3)
        base = "/".join(scheme_host[:3])
    invite_url = f"{base}/cas-connect/{token}"
    # Also expose advisor_firm if present
    return {
        "invite_token": token,
        "invite_url": invite_url,
        "expires_at": doc["expires_at"],
        "status": "PENDING",
        "advisor_name": advisor_name,
        "advisor_firm": ws.get("firm_name"),
    }


@mfd_router.get("/profiles/{profile_id}/cas-invites")
async def list_invites(profile_id: str, request: Request):
    user = await get_current_user(request)
    uid = user.get("_session_user_id") or user["user_id"]
    prof = await db.profiles.find_one({"profile_id": profile_id}, {"_id": 0})
    if not prof:
        raise HTTPException(404, "Profile not found")
    ws = await db.workspaces.find_one(
        {"workspace_id": prof["workspace_id"], "owner_user_id": uid}, {"_id": 0},
    )
    if not ws:
        raise HTTPException(403)
    invites = await db.client_cas_invites.find(
        {"profile_id": profile_id},
        {"_id": 0, "oauth_tokens": 0},  # never leak tokens back to MFD
    ).sort("created_at", -1).to_list(50)

    base = (
        request.headers.get("origin")
        or request.headers.get("referer", "").split("/cas-connect")[0].rstrip("/")
        or str(request.base_url).rstrip("/")
    )
    if base and "//" in base:
        base = "/".join(base.split("/", 3)[:3])
    for inv in invites:
        inv["invite_url"] = f"{base}/cas-connect/{inv['invite_token']}"
        # Soft-expire in-response so stale rows show correctly
        if inv.get("status") in ("PENDING", "AUTHORIZED") and await _is_expired(inv):
            inv["status"] = "EXPIRED"
    return {"invites": invites}


@mfd_router.post("/profiles/{profile_id}/cas-invite/{token}/revoke")
async def revoke_invite(profile_id: str, token: str, request: Request):
    user = await get_current_user(request)
    uid = user.get("_session_user_id") or user["user_id"]
    inv = await db.client_cas_invites.find_one({"invite_token": token}, {"_id": 0})
    if not inv or inv.get("profile_id") != profile_id or inv.get("created_by_user_id") != uid:
        raise HTTPException(404)
    await db.client_cas_invites.update_one(
        {"invite_token": token},
        {"$set": {"status": "REVOKED", "is_active": False, "oauth_tokens": None}},
    )
    return {"status": "REVOKED"}


@mfd_router.post("/profiles/{profile_id}/cas-invite/regenerate")
async def regenerate_invite(profile_id: str, payload: InviteCreateRequest, request: Request):
    """Convenience wrapper — deactivates any existing active invite
    and issues a fresh one. Equivalent to POST .../cas-invite with
    `regenerate=True`."""
    payload.regenerate = True
    return await create_invite(profile_id, payload, request)


# ── Public client-facing routes (NO auth) ──────────────────────────────
@public_router.get("/{token}")
async def get_invite_details(token: str):
    """Returns the details the public page needs to render — advisor
    name, client profile name, expiry, status, pre-fill hints. Never
    leaks OAuth tokens or PAN."""
    inv = await _get_invite_or_404(token)
    return {
        "status": inv["status"],
        "advisor_name": inv.get("advisor_name"),
        "advisor_firm": inv.get("advisor_firm"),
        "advisor_mobile": inv.get("advisor_mobile"),
        "advisor_email": inv.get("advisor_email"),
        "profile_name": inv.get("profile_name"),
        "expires_at": inv.get("expires_at"),
        "client_email": inv.get("client_email"),
        "has_client_details": bool(inv.get("client_pan")),
        "prefill": {
            "name":   inv.get("client_name_prefill"),
            "mobile": inv.get("client_mobile_prefill"),
            "email":  inv.get("client_email_prefill"),
        },
        "consents": inv.get("consents") or {},
        "processed_count": len([f for f in inv.get("processed_files", []) if f.get("status") == "completed"]),
    }


class ClientDetailsRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=120)
    mobile: str = Field(..., min_length=7, max_length=20)
    email: str = Field(..., min_length=5, max_length=255)
    pan: str = Field(..., min_length=10, max_length=10)
    consent_cas_access: bool = Field(..., description="Client consents to sharing CAS holdings")
    consent_gmail_access: bool = Field(default=False, description="Client consents to read-only Gmail scan for CAS emails")
    consent_advisor_access: bool = Field(..., description="Client consents to advisor viewing + managing their data")


@public_router.post("/{token}/client-details")
async def submit_client_details(token: str, payload: ClientDetailsRequest):
    """Step 1.5 of the public wizard — client submits their name,
    mobile, email, PAN, and 3 explicit consents before Gmail connect /
    CAS upload. PAN is stored (encrypted in future; plaintext MVP) so
    the scan step can auto-use it as the CAS PDF password without the
    client retyping it.
    """
    inv = await _get_invite_or_404(token)

    # Basic validation — PAN is 5 letters + 4 digits + 1 letter, uppercase
    pan = payload.pan.strip().upper()
    if not (
        len(pan) == 10 and pan[:5].isalpha() and pan[5:9].isdigit() and pan[9].isalpha()
    ):
        raise HTTPException(400, "PAN format invalid (expected ABCDE1234F)")
    mobile = "".join(ch for ch in payload.mobile if ch.isdigit())
    if len(mobile) < 10:
        raise HTTPException(400, "Mobile number must be at least 10 digits")
    email = payload.email.strip().lower()
    if "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(400, "Email format invalid")

    if not payload.consent_cas_access or not payload.consent_advisor_access:
        raise HTTPException(400, "CAS access and Advisor access consents are required")

    consents = {
        "cas_access":      {"approved": payload.consent_cas_access, "at": _now_iso()},
        "gmail_access":    {"approved": payload.consent_gmail_access, "at": _now_iso()},
        "advisor_access":  {"approved": payload.consent_advisor_access, "at": _now_iso()},
    }

    await db.client_cas_invites.update_one(
        {"invite_token": token},
        {"$set": {
            "client_name":   payload.name.strip(),
            "client_mobile": mobile,
            "client_email":  email,
            "client_pan":    pan,
            "consents":      consents,
            "details_submitted_at": _now_iso(),
            "status": inv.get("status") if inv.get("status") in ("AUTHORIZED", "COMPLETED") else "DETAILS_CAPTURED",
        }},
    )
    return {
        "status": "DETAILS_CAPTURED",
        "next": "gmail_connect" if payload.consent_gmail_access else "cas_upload",
    }


@public_router.get("/{token}/gmail/connect")
async def client_gmail_connect(token: str, request: Request):
    """Start Gmail OAuth for the client. Returns {auth_url}."""
    await _get_invite_or_404(token)  # validates token + expiry
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        raise HTTPException(500, "Google OAuth not configured on server")
    redirect_uri = _resolve_redirect_uri(request)
    # state encodes the invite token so we can recover it in the callback
    state = f"invite_{token}_{uuid.uuid4().hex[:8]}"
    url, code_verifier = get_authorization_url(
        GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, redirect_uri, state,
    )
    await db.gmail_oauth_states.insert_one({
        "state": state,
        "invite_token": token,
        "code_verifier": code_verifier,
        "created_at": _now_iso(),
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
    })
    return {"auth_url": url}


@public_router.get("/oauth/callback")
async def client_gmail_callback_shim(request: Request, code: str = "", state: str = "", error: str = ""):
    """Legacy dispatcher kept for any callers using the old URL.
    Production flow reuses `/api/oauth/gmail/callback` which handles
    `invite_*` states natively. This shim delegates to the same logic."""
    return await _handle_invite_oauth_callback(request, code, state, error)


async def _handle_invite_oauth_callback(request: Request, code: str, state: str, error: str):
    """Shared invite-callback logic. Called from:
      - /api/oauth/gmail/callback  (via dispatch when state starts with 'invite_')
      - /api/public/cas-invite/oauth/callback  (legacy)
    """
    if error:
        return RedirectResponse(url="/cas-connect/error?reason=denied")
    if not code or not state or not state.startswith("invite_"):
        return RedirectResponse(url="/cas-connect/error?reason=bad_state")

    state_doc = await db.gmail_oauth_states.find_one({"state": state}, {"_id": 0})
    if not state_doc:
        return RedirectResponse(url="/cas-connect/error?reason=state_missing")
    token = state_doc.get("invite_token")
    code_verifier = state_doc.get("code_verifier")
    await db.gmail_oauth_states.delete_one({"state": state})

    inv = await db.client_cas_invites.find_one({"invite_token": token}, {"_id": 0})
    if not inv:
        return RedirectResponse(url="/cas-connect/error?reason=invite_gone")

    redirect_uri = _resolve_redirect_uri(request)
    try:
        tokens = exchange_code_for_tokens(
            GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, redirect_uri, code, code_verifier=code_verifier,
        )
    except Exception as e:  # noqa: BLE001
        logger.error(f"client-invite token exchange failed: {e}")
        return RedirectResponse(url=f"/cas-connect/{token}?error=token_exchange")

    # Capture the client's email (fallback only — client-details step
    # already captured the preferred email, so don't overwrite it)
    client_email = None
    try:
        creds = get_gmail_credentials(tokens)
        svc = build_gmail_service(creds)
        prof = svc.users().getProfile(userId="me").execute()
        client_email = prof.get("emailAddress")
    except Exception:  # noqa: BLE001
        pass

    update_set = {
        "status": "AUTHORIZED",
        "authorized_at": _now_iso(),
        "oauth_tokens": tokens,
    }
    # Only set client_email if the details page didn't already capture one
    existing_email = inv.get("client_email")
    if client_email and not existing_email:
        update_set["client_email"] = client_email
    # Always stash the Google account email separately for audit
    if client_email:
        update_set["gmail_account_email"] = client_email

    await db.client_cas_invites.update_one(
        {"invite_token": token},
        {"$set": update_set},
    )
    return RedirectResponse(url=f"/cas-connect/{token}?authorized=1")


@public_router.post("/{token}/scan")
async def client_scan_emails(token: str):
    """After OAuth, list matched CAS emails from last 12 months."""
    inv = await _get_invite_or_404(token)
    tokens = inv.get("oauth_tokens")
    if not tokens or inv.get("status") not in ("AUTHORIZED", "COMPLETED"):
        raise HTTPException(400, "Gmail not connected yet — please sign in first.")

    creds = get_gmail_credentials(tokens)
    service = build_gmail_service(creds)
    try:
        emails = scan_for_cas_emails(service, max_results=30)
    except Exception as e:  # noqa: BLE001
        logger.error(f"client-invite scan failed: {e}")
        raise HTTPException(500, f"Gmail scan failed: {e}") from e

    # Refresh tokens if rotated
    if creds.token != tokens.get("access_token"):
        await db.client_cas_invites.update_one(
            {"invite_token": token},
            {"$set": {
                "oauth_tokens.access_token": creds.token,
                "oauth_tokens.expires_at": (
                    creds.expiry.replace(tzinfo=timezone.utc).isoformat() if creds.expiry else None
                ),
            }},
        )
    # Mark already-processed rows
    processed_ids = {f["message_id"] for f in inv.get("processed_files", []) if f.get("status") == "completed"}
    for e in emails:
        e["already_imported"] = e["message_id"] in processed_ids
    return {"emails": emails, "total": len(emails)}


class ImportRequest(BaseModel):
    selections: List[dict] = Field(..., description="list of {message_id, attachment_id, filename}")
    password: Optional[str] = Field(default=None, max_length=40, description="Optional override — defaults to the PAN captured in client-details")


@public_router.post("/{token}/import")
async def client_import_selected(
    token: str, payload: ImportRequest, request: Request, background_tasks: BackgroundTasks,
):
    """Client picks which CAS emails to import. We download + parse
    (background) + attach holdings to the profile's shadow_user_id.
    Password defaults to the PAN captured in the client-details step,
    so the client doesn't have to retype it."""
    inv = await _get_invite_or_404(token)
    if not payload.selections:
        raise HTTPException(400, "No emails selected")
    tokens = inv.get("oauth_tokens")
    if not tokens:
        raise HTTPException(400, "Gmail not connected")

    # Use stored PAN as default password; caller can override if CAS
    # uses a non-standard password scheme (rare in MVP).
    password = (payload.password or inv.get("client_pan") or "").strip()
    if not password:
        raise HTTPException(400, "CAS password required — submit client details first or provide an override")

    # Resolve the profile → shadow_user_id (that's where holdings land)
    prof = await db.profiles.find_one({"profile_id": inv["profile_id"]}, {"_id": 0})
    if not prof:
        raise HTTPException(410, "Client profile no longer exists")
    shadow_uid = prof.get("shadow_user_id")
    if not shadow_uid:
        raise HTTPException(500, "Profile has no shadow user — contact your advisor")

    creds = get_gmail_credentials(tokens)
    service = build_gmail_service(creds)

    # Kick off each selection as a background task so the client page
    # can poll for progress without waiting on a slow multi-CAS parse.
    queued = []
    for sel in payload.selections:
        mid = sel.get("message_id")
        aid = sel.get("attachment_id")
        fname = sel.get("filename") or "cas.pdf"
        if not mid or not aid:
            continue
        try:
            content = download_attachment(service, mid, aid)
        except Exception as e:  # noqa: BLE001
            logger.error(f"client-invite download failed: {e}")
            continue

        # Persist the raw PDF before kicking off the parse so the MFD
        # can recover from parse failures (e.g. NSDL password mismatch)
        # by re-parsing with a custom password from the dashboard.
        meta = _save_cas_bytes(token, content)
        file_id = meta["file_id"]

        # Record as pending — keyed by file_id (unique per upload)
        await db.client_cas_invites.update_one(
            {"invite_token": token},
            {"$push": {"processed_files": {
                "file_id":     file_id,
                "file_path":   meta["file_path"],
                "file_size":   meta["file_size"],
                "file_sha256": meta["file_sha256"],
                "source":      "gmail",
                "message_id":  mid,
                "filename":    fname,
                "status":      "processing",
                "started_at":  _now_iso(),
                "stored_at":   meta["stored_at"],
            }}},
        )
        background_tasks.add_task(
            _process_client_cas, token, shadow_uid, content, fname, password, file_id,
        )
        queued.append({"message_id": mid, "filename": fname, "file_id": file_id})

    return {"queued": queued, "count": len(queued)}


async def _cascade_reparse_failed_files(
    token: str, shadow_uid: str, password: str, exclude_file_id: str,
):
    """Auto-retry all error-status CAS PDFs in the same invite using the
    password that just worked. Runs sequentially (one PDF at a time) to
    avoid a CPU/memory spike from concurrent OCR jobs. Files that still
    fail are simply left with status='error' — no infinite loop.

    Guard: only retries files with reparse_count < 3 to prevent thrashing.
    """
    inv = await db.client_cas_invites.find_one({"invite_token": token}, {"_id": 0})
    if not inv:
        return
    for f in inv.get("processed_files") or []:
        fid = f.get("file_id")
        if fid == exclude_file_id:
            continue
        if f.get("status") not in ("error", "failed"):
            continue
        if (f.get("reparse_count") or 0) >= 3:
            continue
        fp = f.get("file_path")
        if not fp or not Path(fp).exists():
            continue

        fname = f.get("filename") or "cas.pdf"
        logger.info(f"Cascade re-parse: queuing {fname} ({fid[:8]}) with same password")
        await db.client_cas_invites.update_one(
            {"invite_token": token, "processed_files.file_id": fid},
            {"$set": {
                "processed_files.$.status":       "processing",
                "processed_files.$.started_at":   _now_iso(),
                "processed_files.$.error":        None,
                "processed_files.$.reparse_count": (f.get("reparse_count") or 0) + 1,
            }},
        )
        content = Path(fp).read_bytes()
        await _process_client_cas(token, shadow_uid, content, fname, password, fid)


async def _process_client_cas(
    token: str, shadow_uid: str, content: bytes, filename: str, password: str, file_id: str,
):
    """Background: parse CAS PDF → create a date-stamped portfolio snapshot
    (instead of overwriting live holdings) → mark invite row as completed.

    The snapshot engine automatically mirrors the holdings into the live
    `holdings` table if this is the most recent snapshot, so Client 360
    shows the freshest data by default. All historical snapshots are
    preserved so the MFD can "time-travel" to any past month.
    """
    count = 0
    status = "completed"
    err = None
    snap_date = None
    try:
        # Parse PDF + capture raw casparser/API dict for transaction extraction
        # AND the raw payload for persistence (so we never re-parse).
        holdings, raw_cas_data, raw_payload, parser_source = await parse_cas_pdf_with_data(
            content, password=password
        )
        if holdings:
            for h in holdings:
                h["source"] = "email"
                h["confidence"] = 0.95

            # Detect the CAS statement period (e.g. 2026-01-01 → 2026-01-31)
            # 1st: try reading from PDF text headers
            period_start, period_end = detect_statement_period(content)
            # 2nd: fall back to filename (e.g. NSDLe-CAS_106904998_DEC_2025.PDF)
            if not period_end:
                period_start, period_end = detect_period_from_filename(filename)
            logger.info(
                f"CAS period detected: {period_start} → {period_end} "
                f"for file {filename} (token {token[:8]})"
            )

            # Extract transactions + SIPs if structured data is available
            transactions: list = []
            sips_detected: list = []
            if raw_cas_data:
                try:
                    transactions = _cas_txns.extract_transactions(raw_cas_data)
                    sips_detected = _cas_txns.detect_sip_patterns(transactions)
                    logger.info(
                        f"Extracted {len(transactions)} transactions, "
                        f"{len(sips_detected)} SIP patterns from {filename}"
                    )
                except Exception as txn_err:  # noqa: BLE001
                    logger.warning(f"Transaction extraction failed: {txn_err}")

            # Persist raw parsed payload so the MFD can view it later
            # without re-parsing the PDF, AND so we have an audit trail.
            if raw_payload is not None:
                try:
                    await db.cas_parsed_responses.update_one(
                        {"file_id": file_id},
                        {"$set": {
                            "file_id":         file_id,
                            "user_id":         shadow_uid,
                            "invite_token":    token,
                            "filename":        filename,
                            "parser_source":   parser_source,
                            "holdings_count":  len(holdings),
                            "transactions_count": len(transactions),
                            "sips_count":      len(sips_detected),
                            "period_start":    period_start,
                            "period_end":      period_end,
                            "raw_payload":     raw_payload,
                            "normalized_for_txns": raw_cas_data,
                            "stored_at":       _now_iso(),
                        }},
                        upsert=True,
                    )
                    logger.info(
                        f"Persisted parsed CAS response for file {file_id[:8]} "
                        f"({parser_source}, {len(transactions)} txns)"
                    )
                except Exception as p_err:  # noqa: BLE001
                    logger.warning(f"Failed to persist parsed CAS response: {p_err}")

            # Persist as a date-stamped snapshot (not a flat holdings overwrite)
            snap = await create_cas_snapshot(
                user_id=shadow_uid,
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

            # Also persist transactions + SIPs to their own collections so
            # /api/portfolio/transactions and /api/portfolio/sips keep working.
            if raw_cas_data and transactions:
                try:
                    txn_result = await _cas_txns.persist_transactions_and_sips(
                        db, shadow_uid, raw_cas_data, source="CAS_PDF"
                    )
                    logger.info(f"Persisted transactions: {txn_result}")
                except Exception as txn_err:  # noqa: BLE001
                    logger.warning(f"Transaction persistence failed: {txn_err}")
        else:
            status = "error"
            err = "Parser returned no holdings"
    except Exception as e:  # noqa: BLE001
        logger.error(f"client-invite parse failed: {e}")
        status = "error"
        # Friendlier error for the common "budget exhausted" case.
        emsg = str(e)
        if "budget" in emsg.lower() or "Budget has been exceeded" in emsg:
            err = "AI budget exhausted — admin needs to top up the Emergent LLM key (Profile → Universal Key → Add Balance) to keep using Claude Vision."
        else:
            err = emsg[:200]

    # Update this file's row in processed_files (keyed by file_id)
    await db.client_cas_invites.update_one(
        {"invite_token": token, "processed_files.file_id": file_id},
        {"$set": {
            "processed_files.$.status":          status,
            "processed_files.$.holdings_count":  count,
            "processed_files.$.completed_at":    _now_iso(),
            "processed_files.$.error":           err,
            "processed_files.$.snapshot_date":   snap_date,
            "processed_files.$.last_password_hint": (password[:2] + "***" + password[-1:]) if password else None,
        }},
    )
    # If all processed_files are done + at least one succeeded → COMPLETED
    inv = await db.client_cas_invites.find_one({"invite_token": token}, {"_id": 0})
    if inv:
        files = inv.get("processed_files") or []
        done = all(f.get("status") in ("completed", "error") for f in files)
        any_ok = any(f.get("status") == "completed" and (f.get("holdings_count") or 0) > 0 for f in files)
        if done and any_ok:
            await db.client_cas_invites.update_one(
                {"invite_token": token},
                {"$set": {
                    "status": "COMPLETED",
                    "completed_at": _now_iso(),
                    # Discard the tokens now that we're done — privacy.
                    "oauth_tokens": None,
                }},
            )

    # ── Cascade re-parse ────────────────────────────────────────────────
    # If this file parsed OK, auto-retry all other error-status files in
    # the same invite using the same password. This means that once the MFD
    # provides the correct password for one file, all other uploaded CAS
    # PDFs (e.g., JAN, FEB, MAR) are automatically processed in the background.
    if status == "completed" and password:
        try:
            await _cascade_reparse_failed_files(token, shadow_uid, password, exclude_file_id=file_id)
        except Exception as ce:  # noqa: BLE001
            logger.warning(f"Cascade re-parse error: {ce}")


@public_router.get("/{token}/status")
async def client_invite_status(token: str):
    """Lightweight poll endpoint — returns processed_files + overall
    status so the public page can show progress."""
    inv = await _get_invite_or_404(token)
    # Strip large/internal fields before returning to the public page
    files = []
    for f in inv.get("processed_files", []):
        files.append({k: v for k, v in f.items() if k not in ("file_path", "file_sha256")})
    return {
        "status": inv["status"],
        "processed_files": files,
        "completed_at": inv.get("completed_at"),
    }


# ── Public: direct PDF upload (Gmail-less fallback) ────────────────────
@public_router.post("/{token}/upload-pdf")
async def client_upload_pdf(
    token: str,
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    password: Optional[str] = Form(default=None),
):
    """Client uploads a CAS PDF directly (used when they decline Gmail
    consent or their broker emailed the CAS to a different address).
    The raw bytes are persisted, and a parse is queued in the background.
    Password defaults to the PAN captured in client-details so the client
    doesn't have to retype it.
    """
    inv = await _get_invite_or_404(token)
    if not inv.get("client_pan") and not password:
        raise HTTPException(400, "Submit your details (PAN) first — required to unlock the CAS PDF")

    # Read & validate the upload (single-shot for MVP — CAS PDFs <25MB)
    content = await file.read()
    if not content:
        raise HTTPException(400, "Empty file")
    if len(content) > MAX_CAS_PDF_BYTES:
        raise HTTPException(413, f"File too large — limit is {MAX_CAS_PDF_BYTES // (1024*1024)} MB")
    if not content[:4].startswith(b"%PDF"):
        raise HTTPException(400, "Only PDF files are supported")

    # Resolve profile → shadow_user_id
    prof = await db.profiles.find_one({"profile_id": inv["profile_id"]}, {"_id": 0})
    if not prof:
        raise HTTPException(410, "Client profile no longer exists")
    shadow_uid = prof.get("shadow_user_id")
    if not shadow_uid:
        raise HTTPException(500, "Profile has no shadow user — contact your advisor")

    pwd = (password or inv.get("client_pan") or "").strip()
    fname = file.filename or "cas.pdf"
    meta = _save_cas_bytes(token, content)
    file_id = meta["file_id"]

    await db.client_cas_invites.update_one(
        {"invite_token": token},
        {"$push": {"processed_files": {
            "file_id":     file_id,
            "file_path":   meta["file_path"],
            "file_size":   meta["file_size"],
            "file_sha256": meta["file_sha256"],
            "source":      "upload",
            "filename":    fname,
            "status":      "processing",
            "started_at":  _now_iso(),
            "stored_at":   meta["stored_at"],
        }},
         "$set": {
            "status": "DETAILS_CAPTURED" if inv.get("status") == "PENDING" else inv.get("status", "PENDING"),
        }},
    )
    background_tasks.add_task(
        _process_client_cas, token, shadow_uid, content, fname, pwd, file_id,
    )
    return {"queued": True, "file_id": file_id, "filename": fname}


# ── MFD-side: stored CAS files visibility & selective re-parse ─────────
async def _assert_mfd_owns_invite_or_profile(uid: str, invite: Optional[dict] = None,
                                             profile_id: Optional[str] = None) -> dict:
    """Returns the profile dict (with workspace_id) after verifying the
    MFD owns the workspace this invite/profile belongs to."""
    pid = profile_id or (invite or {}).get("profile_id")
    if not pid:
        raise HTTPException(404, "Profile not found")
    prof = await db.profiles.find_one({"profile_id": pid}, {"_id": 0})
    if not prof:
        raise HTTPException(404, "Profile not found")
    ws = await db.workspaces.find_one(
        {"workspace_id": prof["workspace_id"], "owner_user_id": uid}, {"_id": 0},
    )
    if not ws:
        raise HTTPException(403, "You don't own this profile's workspace")
    return prof


def _public_file_view(invite: dict, f: dict) -> dict:
    """Trim the processed_files row for the MFD list response —
    excludes raw file_path (server-side only) but keeps everything
    needed to render the row + trigger reparse."""
    return {
        "file_id":         f.get("file_id"),
        "filename":        f.get("filename"),
        "file_size":       f.get("file_size"),
        "file_sha256":     f.get("file_sha256"),
        "source":          f.get("source") or ("gmail" if f.get("message_id") else "upload"),
        "status":          f.get("status"),
        "holdings_count":  f.get("holdings_count") or 0,
        "error":           f.get("error"),
        "stored_at":       f.get("stored_at"),
        "started_at":      f.get("started_at"),
        "completed_at":    f.get("completed_at"),
        "last_password_hint": f.get("last_password_hint"),
        "reparse_count":   f.get("reparse_count") or 0,
        "reparsed_by_mfd": bool(f.get("reparsed_by_mfd")),
        "invite_token":    invite.get("invite_token"),
        "profile_id":      invite.get("profile_id"),
        "client_name":     invite.get("client_name") or invite.get("profile_name"),
        "client_email":    invite.get("client_email"),
        "client_pan":      invite.get("client_pan"),  # advisor needs it for re-parse
        "is_downloadable": bool(f.get("file_path")),
    }


@mfd_router.get("/profiles/{profile_id}/cas-uploads")
async def list_cas_uploads_for_profile(profile_id: str, request: Request):
    """Return every raw CAS PDF the client uploaded for this profile
    (across all invites). MFD uses this to audit shares + selectively
    re-parse failures."""
    user = await get_current_user(request)
    uid = user.get("_session_user_id") or user["user_id"]
    await _assert_mfd_owns_invite_or_profile(uid, profile_id=profile_id)

    invites = await db.client_cas_invites.find(
        {"profile_id": profile_id},
        {"_id": 0, "oauth_tokens": 0},
    ).sort("created_at", -1).to_list(50)

    files: List[dict] = []
    for inv in invites:
        for f in inv.get("processed_files", []) or []:
            if not f.get("file_id"):
                continue  # legacy rows with no persisted file
            files.append(_public_file_view(inv, f))
    files.sort(key=lambda x: x.get("stored_at") or "", reverse=True)
    return {"files": files, "count": len(files)}


@mfd_router.get("/cas-uploads")
async def list_all_cas_uploads(request: Request, limit: int = 200):
    """Workspace-wide audit list — every CAS PDF a client has ever
    shared with this MFD across all profiles. Useful for the global
    'Shared CAS Files' view."""
    user = await get_current_user(request)
    uid = user.get("_session_user_id") or user["user_id"]
    workspaces = await db.workspaces.find(
        {"owner_user_id": uid}, {"_id": 0, "workspace_id": 1},
    ).to_list(20)
    ws_ids = [w["workspace_id"] for w in workspaces if w.get("workspace_id")]
    if not ws_ids:
        return {"files": [], "count": 0}

    invites = await db.client_cas_invites.find(
        {"workspace_id": {"$in": ws_ids}},
        {"_id": 0, "oauth_tokens": 0},
    ).sort("created_at", -1).to_list(500)

    files: List[dict] = []
    for inv in invites:
        for f in inv.get("processed_files", []) or []:
            if not f.get("file_id"):
                continue
            files.append(_public_file_view(inv, f))
    files.sort(key=lambda x: x.get("stored_at") or "", reverse=True)
    return {"files": files[:limit], "count": len(files)}


async def _find_file_by_id(uid: str, file_id: str) -> tuple[dict, dict]:
    """Look up the invite + processed_file by file_id, asserting that
    the calling MFD owns the corresponding workspace."""
    workspaces = await db.workspaces.find(
        {"owner_user_id": uid}, {"_id": 0, "workspace_id": 1},
    ).to_list(20)
    ws_ids = [w["workspace_id"] for w in workspaces if w.get("workspace_id")]
    if not ws_ids:
        raise HTTPException(404, "File not found")
    inv = await db.client_cas_invites.find_one(
        {"workspace_id": {"$in": ws_ids}, "processed_files.file_id": file_id},
        {"_id": 0, "oauth_tokens": 0},
    )
    if not inv:
        raise HTTPException(404, "File not found")
    file_row = next((f for f in inv.get("processed_files", []) if f.get("file_id") == file_id), None)
    if not file_row:
        raise HTTPException(404, "File not found")
    return inv, file_row


@mfd_router.get("/cas-uploads/{file_id}/download")
async def download_cas_upload(file_id: str, request: Request):
    """Serve the original PDF inline so the MFD can review what the
    client actually shared. Workspace-scoped — only the owning MFD
    can download."""
    user = await get_current_user(request)
    uid = user.get("_session_user_id") or user["user_id"]
    inv, f = await _find_file_by_id(uid, file_id)
    fp = f.get("file_path")
    if not fp or not Path(fp).exists():
        raise HTTPException(410, "File no longer on disk")
    return FileResponse(
        path=fp,
        media_type="application/pdf",
        filename=f.get("filename") or "cas.pdf",
    )


class ReparseRequest(BaseModel):
    password: Optional[str] = Field(default=None, max_length=40)


@mfd_router.post("/cas-uploads/{file_id}/reparse")
async def reparse_cas_upload(file_id: str, payload: ReparseRequest, request: Request,
                             background_tasks: BackgroundTasks):
    """Selectively re-parse a stored CAS PDF with an optional custom
    password (e.g., when the auto-parse failed because the client's CAS
    used a non-PAN password). Re-uses the original `_process_client_cas`
    worker so the same status updates flow through."""
    user = await get_current_user(request)
    uid = user.get("_session_user_id") or user["user_id"]
    inv, f = await _find_file_by_id(uid, file_id)
    fp = f.get("file_path")
    if not fp or not Path(fp).exists():
        raise HTTPException(410, "File no longer on disk — please ask the client to re-upload")

    prof = await db.profiles.find_one({"profile_id": inv["profile_id"]}, {"_id": 0})
    if not prof:
        raise HTTPException(410, "Client profile no longer exists")
    shadow_uid = prof.get("shadow_user_id")
    if not shadow_uid:
        raise HTTPException(500, "Profile has no shadow user")

    pwd = (payload.password or inv.get("client_pan") or "").strip()
    if not pwd:
        raise HTTPException(400, "Provide a password — auto-fallback (PAN) is unavailable")

    content = Path(fp).read_bytes()
    # Mark this row as re-processing so the UI flips back to "processing"
    await db.client_cas_invites.update_one(
        {"invite_token": inv["invite_token"], "processed_files.file_id": file_id},
        {"$set": {
            "processed_files.$.status":     "processing",
            "processed_files.$.started_at": _now_iso(),
            "processed_files.$.error":      None,
            "processed_files.$.reparse_count": (f.get("reparse_count") or 0) + 1,
            "processed_files.$.reparsed_by_mfd": True,
        }},
    )
    background_tasks.add_task(
        _process_client_cas, inv["invite_token"], shadow_uid, content,
        f.get("filename") or "cas.pdf", pwd, file_id,
    )
    return {"status": "queued", "file_id": file_id}


@mfd_router.delete("/cas-uploads/{file_id}")
async def delete_cas_upload(file_id: str, request: Request):
    """Remove the stored PDF + the processed_files row. Does NOT
    touch any holdings already imported from this file (those live
    on the profile's shadow_user_id and survive deletion of the
    source PDF)."""
    user = await get_current_user(request)
    uid = user.get("_session_user_id") or user["user_id"]
    inv, f = await _find_file_by_id(uid, file_id)
    _delete_cas_file(f.get("file_path"))
    await db.client_cas_invites.update_one(
        {"invite_token": inv["invite_token"]},
        {"$pull": {"processed_files": {"file_id": file_id}}},
    )
    # Also drop the cached parsed response — re-uploads will re-parse.
    try:
        await db.cas_parsed_responses.delete_one({"file_id": file_id})
    except Exception:  # noqa: BLE001
        pass
    return {"status": "deleted", "file_id": file_id}


# ── Parsed CAS JSON viewer ──────────────────────────────────────────────
@mfd_router.get("/cas-uploads/{file_id}/parsed-response")
async def get_parsed_cas_response(file_id: str, request: Request):
    """Return the cached parsed CAS JSON for a stored file. Used by the
    MFD UI to show "View Parsed Statement" without re-running the
    expensive parser. 404 when the parser path didn't yield structured
    data (e.g. OCR/AI fallback) or when the file was uploaded before
    persistence was enabled.
    """
    user = await get_current_user(request)
    uid = user.get("_session_user_id") or user["user_id"]
    # Ownership check piggy-backs on `_find_file_by_id` — only the MFD
    # whose workspace owns this invite can see the parsed JSON.
    inv, f = await _find_file_by_id(uid, file_id)
    doc = await db.cas_parsed_responses.find_one({"file_id": file_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "No parsed response cached for this file. Re-parse the PDF to refresh.")
    return {
        "file_id":        doc.get("file_id"),
        "filename":       doc.get("filename") or f.get("filename"),
        "parser_source":  doc.get("parser_source"),
        "stored_at":      doc.get("stored_at"),
        "period_start":   doc.get("period_start"),
        "period_end":     doc.get("period_end"),
        "holdings_count": doc.get("holdings_count"),
        "transactions_count": doc.get("transactions_count"),
        "sips_count":     doc.get("sips_count"),
        "raw_payload":    doc.get("raw_payload"),
        "client_name":    inv.get("client_name") or inv.get("profile_name"),
    }


@mfd_router.get("/cas-snapshots/{snapshot_date}/parsed-response")
async def get_parsed_response_for_snapshot(
    snapshot_date: str, request: Request, profile_id: Optional[str] = None,
):
    """Convenience: fetch the parsed CAS JSON behind a particular
    snapshot date. Looks up the snapshot's `cas_file_id` and delegates
    to the file-scoped endpoint above. Used by the Time-Machine UI's
    "View Parsed Statement" link.
    """
    user = await get_current_user(request)
    uid = user.get("_session_user_id") or user["user_id"]

    # Resolve the right shadow_user_id when the MFD targets a profile.
    target_uid = uid
    if profile_id:
        prof = await db.profiles.find_one({"profile_id": profile_id}, {"_id": 0, "shadow_user_id": 1, "workspace_id": 1})
        if not prof or not prof.get("shadow_user_id"):
            raise HTTPException(404, "Profile not found")
        # Verify MFD owns the workspace
        ws = await db.workspaces.find_one(
            {"workspace_id": prof["workspace_id"], "owner_user_id": uid}, {"_id": 0, "workspace_id": 1},
        )
        if not ws:
            raise HTTPException(403, "You don't own this profile's workspace")
        target_uid = prof["shadow_user_id"]

    snap = await db.portfolio_snapshots.find_one(
        {"user_id": target_uid, "snapshot_date": snapshot_date},
        {"_id": 0, "cas_file_id": 1, "cas_filename": 1, "snapshot_date": 1},
    )
    if not snap or not snap.get("cas_file_id"):
        raise HTTPException(404, "Snapshot has no associated parsed CAS response")
    file_id = snap["cas_file_id"]
    doc = await db.cas_parsed_responses.find_one({"file_id": file_id}, {"_id": 0})
    if not doc:
        raise HTTPException(
            404,
            "Parsed response not yet cached — this snapshot was created before "
            "JSON persistence was enabled. Re-parse the original CAS PDF to refresh.",
        )
    return {
        "file_id":        doc.get("file_id"),
        "filename":       doc.get("filename") or snap.get("cas_filename"),
        "snapshot_date":  snapshot_date,
        "parser_source":  doc.get("parser_source"),
        "stored_at":      doc.get("stored_at"),
        "period_start":   doc.get("period_start"),
        "period_end":     doc.get("period_end"),
        "holdings_count": doc.get("holdings_count"),
        "transactions_count": doc.get("transactions_count"),
        "sips_count":     doc.get("sips_count"),
        "raw_payload":    doc.get("raw_payload"),
    }
