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



# ─── CAS Parser API key management (legacy — kept for backward compat) ──
@router.get("/admin/cas-config")
async def get_cas_config(request: Request):
    """Return current CAS Parser config (prod key masked). Admin only."""
    await require_admin(request)
    from services import cas_api_client
    cfg = cas_api_client.get_effective_config()
    persisted = await db.system_config.find_one({"key": "secrets"}, {"_id": 0}) or {}
    cfg["persisted_at"] = persisted.get("updated_at")
    cfg["persisted_by"] = persisted.get("updated_by")
    return cfg


@router.put("/admin/cas-config")
async def update_cas_config(request: Request):
    """Persist CAS Parser key + sandbox toggle (routes through unified secrets)."""
    user = await require_admin(request)
    body = await request.json()
    prod_key = body.get("prod_key")
    use_sandbox = body.get("use_sandbox")

    from services import cas_api_client
    from helpers import secrets as _secrets

    if prod_key is not None:
        await _secrets.persist_to_db(db, "CASPARSER_API_KEY", prod_key.strip() or None, updated_by=user.get("email", ""))
    if use_sandbox is not None:
        cas_api_client.set_override(use_sandbox=bool(use_sandbox))
        # also track sandbox toggle in system_config.cas so it survives restart
        from datetime import datetime, timezone
        await db.system_config.update_one(
            {"key": "cas_parser"},
            {"$set": {"use_sandbox": bool(use_sandbox), "updated_at": datetime.now(timezone.utc).isoformat(), "updated_by": user.get("email", "")},
             "$setOnInsert": {"key": "cas_parser"}},
            upsert=True,
        )
    return {"status": "ok", "config": cas_api_client.get_effective_config()}


@router.post("/admin/cas-config/test")
async def test_cas_connection(request: Request):
    """Attempt to mint an access token to verify the key works. Admin only."""
    await require_admin(request)
    from services import cas_api_client
    token_res = cas_api_client.generate_access_token(expiry_minutes=5)
    if not token_res:
        return {"ok": False, "error": "Token mint failed — key may be invalid or API unreachable"}
    tok = token_res.get("access_token", "")
    return {
        "ok": True,
        "token_prefix": tok[:8] + "…" if tok else "",
        "expires_in": token_res.get("expires_in"),
        "mode": "sandbox" if tok.startswith("sandbox-") else "production",
    }


# ═══ Secrets Management (generic CRUD) ═══════════════════════════════════
@router.get("/admin/secrets")
async def list_secrets(request: Request):
    """List all known + custom secrets with masked values. Admin only."""
    await require_admin(request)
    from helpers import secrets as _secrets
    persisted = await db.system_config.find_one({"key": "secrets"}, {"_id": 0}) or {}
    return {
        "secrets": _secrets.list_all(),
        "updated_at": persisted.get("updated_at"),
        "updated_by": persisted.get("updated_by"),
    }


@router.put("/admin/secrets/{key}")
async def upsert_secret(key: str, request: Request):
    """Set or update a secret value. Admin only."""
    user = await require_admin(request)
    body = await request.json()
    value = body.get("value")
    if value is None:
        raise HTTPException(status_code=400, detail="value is required")
    if not value or not value.strip():
        raise HTTPException(status_code=400, detail="value must not be empty")
    from helpers import secrets as _secrets
    await _secrets.persist_to_db(db, key, value.strip(), updated_by=user.get("email", ""))
    return {"status": "ok", "key": key, "masked_value": _secrets.mask(value.strip())}


@router.delete("/admin/secrets/{key}")
async def delete_secret(key: str, request: Request):
    """Remove DB override for a secret. Falls back to env. Admin only."""
    user = await require_admin(request)
    from helpers import secrets as _secrets
    await _secrets.persist_to_db(db, key, None, updated_by=user.get("email", ""))
    return {"status": "ok", "key": key, "deleted": True}


@router.post("/admin/secrets/{key}/test")
async def test_secret(key: str, request: Request):
    """Invoke the registered test handler for a known secret. Admin only."""
    await require_admin(request)
    from helpers import secrets as _secrets
    meta = _secrets.KNOWN_SECRETS.get(key)
    if not meta or not meta.get("test_fn"):
        raise HTTPException(status_code=400, detail="No test available for this secret")
    test_fn = meta["test_fn"]

    if test_fn == "cas_parser":
        from services import cas_api_client
        res = cas_api_client.generate_access_token(expiry_minutes=5)
        if not res:
            return {"ok": False, "error": "Token mint failed"}
        tok = res.get("access_token", "")
        return {
            "ok": True,
            "detail": f"{'sandbox' if tok.startswith('sandbox-') else 'production'} mode — token expires in {res.get('expires_in')}s",
        }

    if test_fn in ("llm", "openai"):
        # Lightweight ping — 1-token completion
        try:
            from openai import OpenAI
            k = _secrets.get("OPENAI_API_KEY") if test_fn == "openai" else _secrets.get("EMERGENT_LLM_KEY")
            if not k:
                return {"ok": False, "error": "Key not configured"}
            base_url = "https://integrations.emergentagent.com/openai" if test_fn == "llm" else None
            client = OpenAI(api_key=k, base_url=base_url) if base_url else OpenAI(api_key=k)
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1,
                temperature=0,
            )
            return {"ok": True, "detail": f"Response received (model: {resp.model})"}
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:120]}"}

    return {"ok": False, "error": f"Unknown test_fn: {test_fn}"}


# ═══ Feature Flags Management ════════════════════════════════════════════
@router.get("/admin/feature-flags")
async def list_feature_flags(request: Request):
    """List all feature flags with modes + allowlists. Admin only."""
    await require_admin(request)
    import feature_flags
    persisted = await db.system_config.find_one({"key": "feature_flags"}, {"_id": 0}) or {}
    return {
        "flags": feature_flags.list_all(),
        "updated_at": persisted.get("updated_at"),
        "updated_by": persisted.get("updated_by"),
    }


@router.put("/admin/feature-flags/{flag}")
async def update_feature_flag(flag: str, request: Request):
    """Update mode and/or allowlist for a flag. Admin only."""
    user = await require_admin(request)
    body = await request.json()
    mode = body.get("mode")
    allowlist = body.get("allowlist")
    import feature_flags
    try:
        feature_flags.set_flag(flag, mode=mode, allowlist=allowlist)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await feature_flags.persist_to_db(db, updated_by=user.get("email", ""))
    return {"status": "ok", "flag": flag}


@router.post("/admin/feature-flags/{flag}/users")
async def add_feature_user(flag: str, request: Request):
    """Add an email to a flag's allowlist. Admin only."""
    user = await require_admin(request)
    body = await request.json()
    email = (body.get("email") or "").strip()
    if not email:
        raise HTTPException(status_code=400, detail="email is required")
    import feature_flags
    feature_flags.add_user(flag, email)
    await feature_flags.persist_to_db(db, updated_by=user.get("email", ""))
    return {"status": "ok", "flag": flag, "email": email}


@router.delete("/admin/feature-flags/{flag}/users/{email}")
async def remove_feature_user(flag: str, email: str, request: Request):
    """Remove an email from a flag's allowlist. Admin only."""
    user = await require_admin(request)
    import feature_flags
    feature_flags.remove_user(flag, email)
    await feature_flags.persist_to_db(db, updated_by=user.get("email", ""))
    return {"status": "ok", "flag": flag, "email": email}
