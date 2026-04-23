"""DPDP Act 2023 compliance endpoints.

Exposes:
    GET    /api/compliance/consents            — purposes + user's current state
    POST   /api/compliance/consents/{purpose}  — grant
    DELETE /api/compliance/consents/{purpose}  — withdraw
    GET    /api/compliance/audit               — my audit trail (last 100)
    GET    /api/compliance/pan                 — masked readback of stored PAN
    PUT    /api/compliance/pan                 — encrypt + store PAN
    DELETE /api/compliance/pan                 — erase PAN ciphertext
    GET    /api/compliance/export              — data-subject-right export (JSON)
    DELETE /api/compliance/account             — right-to-erasure (soft delete)
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request

from deps import db
from routes.auth import get_current_user
from services import audit, consents, pii_security

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/compliance", tags=["compliance"])


def _ctx(request: Request) -> Dict[str, str]:
    return {
        "ip": request.client.host if request.client else "",
        "ua": request.headers.get("user-agent", ""),
    }


# ── Consent endpoints ────────────────────────────────────────────────────
@router.get("/consents")
async def list_consents(request: Request) -> Dict[str, Any]:
    """Return the consent catalogue + the user's current grant status per
    purpose. Used by the Privacy Center UI."""
    user = await get_current_user(request)
    state = await consents.current_for_user(user["user_id"])
    items = []
    for purpose, spec in consents.PURPOSES.items():
        row = state.get(purpose)
        items.append({
            "purpose": purpose,
            "title": spec["title"],
            "description": spec["description"],
            "required": spec["required"] == "true",
            "status": (row or {}).get("status", "pending"),
            "granted_at": (row or {}).get("granted_at"),
            "withdrawn_at": (row or {}).get("withdrawn_at"),
            "version": consents.CURRENT_VERSION,
        })
    return {"consents": items, "version": consents.CURRENT_VERSION}


@router.post("/consents/{purpose}")
async def grant_consent(purpose: str, request: Request):
    user = await get_current_user(request)
    try:
        entry = await consents.grant(
            user_id=user["user_id"], purpose=purpose, **_ctx(request),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return entry


@router.delete("/consents/{purpose}")
async def withdraw_consent(purpose: str, request: Request):
    user = await get_current_user(request)
    try:
        entry = await consents.withdraw(
            user_id=user["user_id"], purpose=purpose, **_ctx(request),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return entry


# ── Audit trail ──────────────────────────────────────────────────────────
@router.get("/audit")
async def my_audit_trail(request: Request, limit: int = 100):
    """User's own DPDP audit trail — last 100 actions on their account."""
    user = await get_current_user(request)
    rows = await audit.list_for_user(user["user_id"], limit=min(limit, 500))
    return {"rows": rows, "count": len(rows)}


# ── PAN encryption endpoints ─────────────────────────────────────────────
@router.get("/pan")
async def get_pan_masked(request: Request):
    """Return masked PAN ('XXXXX1234X') + set/unset status.
    Full plaintext is NEVER returned — stored encrypted at rest."""
    user = await get_current_user(request)
    row = await db.users.find_one(
        {"user_id": user["user_id"]}, {"_id": 0, "pan_encrypted": 1},
    )
    ct = (row or {}).get("pan_encrypted")
    if not ct:
        return {"has_pan": False, "masked": ""}
    plain = pii_security.decrypt(ct)
    ctx = _ctx(request)
    await audit.record(
        user_id=user["user_id"], action="pan_view",
        ip=ctx["ip"], ua=ctx["ua"], outcome="success",
    )
    return {"has_pan": True, "masked": pii_security.mask_pan(plain)}


@router.put("/pan")
async def set_pan(request: Request):
    """Accept a PAN (10-char) and store AES-256-GCM encrypted. Requires
    the `data_processing` consent to already be granted."""
    user = await get_current_user(request)
    body = await request.json()
    pan = (body.get("pan") or "").strip().upper()
    ok, reason = pii_security.validate_pan(pan)
    if not ok:
        ctx = _ctx(request)
        await audit.record(
            user_id=user["user_id"], action="pan_update",
            outcome="denied", ip=ctx["ip"], ua=ctx["ua"],
            details={"reason": reason},
        )
        raise HTTPException(status_code=400, detail=f"invalid_pan:{reason}")
    if not await consents.has_granted(user["user_id"], "data_processing"):
        raise HTTPException(status_code=403, detail="consent_required:data_processing")
    ct = pii_security.encrypt(pan)
    await db.users.update_one(
        {"user_id": user["user_id"]},
        {"$set": {"pan_encrypted": ct, "pan_last4": pan[5:9]}},
    )
    ctx = _ctx(request)
    await audit.record(
        user_id=user["user_id"], action="pan_update",
        ip=ctx["ip"], ua=ctx["ua"], outcome="success",
    )
    return {"ok": True, "masked": pii_security.mask_pan(pan)}


@router.delete("/pan")
async def delete_pan(request: Request):
    """Erase the encrypted PAN (right-to-rectification + minimisation)."""
    user = await get_current_user(request)
    await db.users.update_one(
        {"user_id": user["user_id"]},
        {"$unset": {"pan_encrypted": "", "pan_last4": ""}},
    )
    ctx = _ctx(request)
    await audit.record(
        user_id=user["user_id"], action="pan_delete",
        ip=ctx["ip"], ua=ctx["ua"],
    )
    return {"ok": True}


# ── Data subject rights (DPDP §13-17) ────────────────────────────────────
@router.get("/export")
async def data_export(request: Request) -> Dict[str, Any]:
    """Return a JSON blob of the user's data (DPDP right to access / portability).
    PAN is returned masked — plaintext is never exported."""
    user = await get_current_user(request)
    uid = user["user_id"]
    user_doc = await db.users.find_one({"user_id": uid}, {"_id": 0})
    holdings = await db.holdings.find({"user_id": uid}, {"_id": 0}).to_list(5000)
    action_plans = await db.action_plans.find({"user_id": uid}, {"_id": 0}).to_list(200)
    consent_rows = await db.consent_records.find(
        {"user_id": uid}, {"_id": 0},
    ).sort("granted_at", -1).to_list(200)
    # Mask PAN.
    if user_doc and user_doc.get("pan_encrypted"):
        user_doc["pan_masked"] = pii_security.mask_pan(
            pii_security.decrypt(user_doc["pan_encrypted"]) or "",
        )
        user_doc.pop("pan_encrypted", None)
    ctx = _ctx(request)
    await audit.record(
        user_id=uid, action="data_export",
        ip=ctx["ip"], ua=ctx["ua"],
        details={
            "holdings_count": len(holdings),
            "action_plans_count": len(action_plans),
        },
    )
    return {
        "user": user_doc,
        "holdings": holdings,
        "action_plans": action_plans,
        "consents": consent_rows,
    }


@router.delete("/account")
async def delete_account(request: Request):
    """Right to erasure — soft-delete the user + purge holdings / plans.
    Audit records are retained (7 years) per DPDP §8(6) record-keeping."""
    user = await get_current_user(request)
    uid = user["user_id"]
    # Hard-delete user-owned data.
    h_res = await db.holdings.delete_many({"user_id": uid})
    p_res = await db.action_plans.delete_many({"user_id": uid})
    # Soft-delete account — keep user row for audit linkage.
    from datetime import datetime, timezone
    await db.users.update_one(
        {"user_id": uid},
        {"$set": {
            "is_deleted": True,
            "deleted_at": datetime.now(timezone.utc).isoformat(),
        },
         "$unset": {"pan_encrypted": "", "pan_last4": ""}},
    )
    ctx = _ctx(request)
    await audit.record(
        user_id=uid, action="data_delete",
        ip=ctx["ip"], ua=ctx["ua"],
        details={
            "holdings_deleted": h_res.deleted_count,
            "plans_deleted": p_res.deleted_count,
        },
    )
    return {
        "ok": True,
        "holdings_deleted": h_res.deleted_count,
        "plans_deleted": p_res.deleted_count,
    }
