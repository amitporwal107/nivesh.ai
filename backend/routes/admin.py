"""Admin routes: Whitelist management, stats, OCR corrections."""
from fastapi import APIRouter, HTTPException, Request
from datetime import datetime, timezone
import logging

from deps import db, get_current_user, require_admin

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


@router.get("/admin/whitelist")
async def list_whitelist(request: Request):
    """List all whitelisted users. Admin only."""
    await require_admin(request)
    entries = await db.whitelisted_users.find({}, {"_id": 0}).sort("invited_at", -1).to_list(1000)
    for entry in entries:
        user = await db.users.find_one({"email": entry["email"]}, {"_id": 0})
        entry["user_name"] = user.get("name", "") if user else ""
        entry["user_picture"] = user.get("picture", "") if user else ""
    return entries


@router.post("/admin/whitelist/add")
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


@router.post("/admin/whitelist/bulk-upload")
async def bulk_upload_whitelist(request: Request):
    """Bulk upload emails via CSV. Admin only."""
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


@router.delete("/admin/whitelist/{email}")
async def remove_from_whitelist(request: Request, email: str):
    """Remove an email from the whitelist. Admin only."""
    admin = await require_admin(request)
    email = email.strip().lower()

    if email == admin.get("email", "").lower():
        raise HTTPException(status_code=400, detail="Cannot remove yourself from the whitelist")

    result = await db.whitelisted_users.delete_one({"email": email})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Email not found in whitelist")

    user = await db.users.find_one({"email": email}, {"_id": 0})
    if user:
        await db.user_sessions.delete_many({"user_id": user["user_id"]})

    return {"message": f"{email} removed from whitelist"}


@router.patch("/admin/whitelist/{email}")
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
        if body["status"] == "blocked":
            user = await db.users.find_one({"email": email}, {"_id": 0})
            if user:
                await db.user_sessions.delete_many({"user_id": user["user_id"]})

    if update:
        await db.whitelisted_users.update_one({"email": email}, {"$set": update})
        if "is_admin" in update:
            await db.users.update_one({"email": email}, {"$set": {"is_admin": update["is_admin"]}})

    return {"message": f"Updated {email}", "updates": update}


@router.get("/admin/stats")
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


# ==================== OCR CORRECTION ADMIN ROUTES ====================

@router.post("/admin/ocr-correction/isin")
async def add_ocr_isin_correction(request: Request):
    """Admin: teach OCR engine garbled ISIN -> correct ISIN."""
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
    return {"status": "ok", "message": f"Learned: {garbled} -> {correct}"}


@router.post("/admin/ocr-correction/name")
async def add_ocr_name_correction(request: Request):
    """Admin: teach OCR engine garbled name -> correct name + ISIN."""
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
    return {"status": "ok", "message": f"Learned: '{garbled}' -> '{correct}'"}


@router.post("/admin/ocr-correction/holding")
async def correct_holding(request: Request):
    """Admin: correct a parsed holding's ISIN/name/qty/price."""
    user = await get_current_user(request)
    whitelist = await db.whitelisted_users.find_one({"email": user["email"]}, {"_id": 0})
    if not whitelist or not whitelist.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    body = await request.json()
    holding_id = body.get("holding_id", "")
    corrections = body.get("corrections", {})
    if not holding_id or not corrections:
        raise HTTPException(status_code=400, detail="holding_id and corrections required")
    holding = await db.holdings.find_one({"holding_id": holding_id}, {"_id": 0})
    if not holding:
        raise HTTPException(status_code=404, detail="Holding not found")
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


@router.get("/admin/ocr-correction/stats")
async def get_ocr_correction_stats(request: Request):
    """Get OCR correction engine statistics."""
    user = await get_current_user(request)
    whitelist = await db.whitelisted_users.find_one({"email": user["email"]}, {"_id": 0})
    if not whitelist or not whitelist.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    from services.ocr_correction import get_correction_stats
    return get_correction_stats()
