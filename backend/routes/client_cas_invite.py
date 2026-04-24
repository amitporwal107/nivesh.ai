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
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Request, BackgroundTasks
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from deps import db, get_current_user, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GMAIL_REDIRECT_URI
from services import mfd_workspace
from services.gmail_service import (
    get_authorization_url, exchange_code_for_tokens,
    get_gmail_credentials, build_gmail_service,
    scan_for_cas_emails, download_attachment,
)
from helpers.parsing import parse_cas_pdf, save_holdings

logger = logging.getLogger(__name__)

mfd_router = APIRouter(prefix="/api/mfd", tags=["cas-invite-mfd"])
public_router = APIRouter(prefix="/api/public/cas-invite", tags=["cas-invite-public"])

INVITE_TTL_HOURS = 24  # 24h expiry per PRD — short urgency window, MFD regenerates on demand


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
    `/api/oauth/gmail/callback` endpoint (which will dispatch to our
    invite handler when it sees an `invite_*` state prefix). This
    avoids needing to whitelist a new redirect URI in Google Console."""
    if GMAIL_REDIRECT_URI:
        return GMAIL_REDIRECT_URI
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
    # Fetch the MFD's own user record (not the impersonated client's)
    advisor = await db.users.find_one({"user_id": uid}, {"_id": 0, "name": 1, "email": 1, "full_name": 1, "mobile": 1, "phone": 1})
    advisor_name = (
        (advisor or {}).get("full_name")
        or (advisor or {}).get("name")
        or ws.get("firm_name")
        or "Your advisor"
    )
    advisor_email = (advisor or {}).get("email")
    advisor_mobile = (advisor or {}).get("mobile") or (advisor or {}).get("phone")
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
        # Pre-filled client contact info (optional). Client can edit on the
        # public page; these are hints the MFD captured at invite time.
        "client_name_prefill": payload.client_name,
        "client_mobile_prefill": payload.client_mobile,
        "client_email_prefill": payload.client_email,
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

        # Record as pending
        await db.client_cas_invites.update_one(
            {"invite_token": token},
            {"$push": {"processed_files": {
                "message_id": mid, "filename": fname, "status": "processing",
                "started_at": _now_iso(),
            }}},
        )
        background_tasks.add_task(
            _process_client_cas, token, shadow_uid, content, fname, password, mid,
        )
        queued.append({"message_id": mid, "filename": fname})

    return {"queued": queued, "count": len(queued)}


async def _process_client_cas(
    token: str, shadow_uid: str, content: bytes, filename: str, password: str, message_id: str,
):
    """Background: parse CAS PDF → save holdings under the profile's
    shadow_user_id → mark invite row as completed. Runs outside the
    request/response cycle so the client page can poll status."""
    count = 0
    status = "completed"
    err = None
    try:
        parsed = await parse_cas_pdf(content, password=password)
        if parsed:
            for h in parsed:
                h["source"] = "email"
                h["confidence"] = 0.95
            saved = await save_holdings(shadow_uid, parsed, "Client Gmail CAS")
            count = len(saved or [])
    except Exception as e:  # noqa: BLE001
        logger.error(f"client-invite parse failed: {e}")
        status = "error"
        err = str(e)[:200]

    # Update this file's row in processed_files
    await db.client_cas_invites.update_one(
        {"invite_token": token, "processed_files.message_id": message_id},
        {"$set": {
            "processed_files.$.status": status,
            "processed_files.$.holdings_count": count,
            "processed_files.$.completed_at": _now_iso(),
            "processed_files.$.error": err,
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


@public_router.get("/{token}/status")
async def client_invite_status(token: str):
    """Lightweight poll endpoint — returns processed_files + overall
    status so the public page can show progress."""
    inv = await _get_invite_or_404(token)
    return {
        "status": inv["status"],
        "processed_files": inv.get("processed_files", []),
        "completed_at": inv.get("completed_at"),
    }
