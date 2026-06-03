"""Admin routes: Whitelist management, stats, OCR corrections."""
from fastapi import APIRouter, HTTPException, Request
from datetime import datetime, timezone
from typing import Optional
import logging
import os

from deps import db, get_current_user, require_admin
from core.exceptions import (
    ValidationException, ResourceNotFoundException, AuthorizationException,
    BusinessException, SystemException,
)

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
        raise ValidationException("Valid email required", code="VAL-003")

    existing = await db.whitelisted_users.find_one({"email": email})
    if existing:
        raise BusinessException(f"{email} is already whitelisted", code="BIZ-002")

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
        raise ValidationException("No emails provided", code="VAL-002")

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
        raise BusinessException("Cannot remove yourself from the whitelist", code="BIZ-001")

    result = await db.whitelisted_users.delete_one({"email": email})
    if result.deleted_count == 0:
        raise ResourceNotFoundException("Email not found in whitelist", code="RES-001")

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
        raise ResourceNotFoundException("Email not found in whitelist", code="RES-001")

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
        raise AuthorizationException("Admin access required", code="AUTHZ-003")
    body = await request.json()
    garbled = body.get("garbled_isin", "").strip()
    correct = body.get("correct_isin", "").strip()
    context = body.get("context", "")
    if not garbled or not correct or len(correct) != 12:
        raise ValidationException("Both garbled_isin and correct_isin (12 chars) required", code="VAL-002")
    from services.ocr_correction import add_isin_correction
    add_isin_correction(garbled, correct, context)
    return {"status": "ok", "message": f"Learned: {garbled} -> {correct}"}


@router.post("/admin/ocr-correction/name")
async def add_ocr_name_correction(request: Request):
    """Admin: teach OCR engine garbled name -> correct name + ISIN."""
    user = await get_current_user(request)
    whitelist = await db.whitelisted_users.find_one({"email": user["email"]}, {"_id": 0})
    if not whitelist or not whitelist.get("is_admin"):
        raise AuthorizationException("Admin access required", code="AUTHZ-003")
    body = await request.json()
    garbled = body.get("garbled_name", "").strip()
    correct = body.get("correct_name", "").strip()
    isin = body.get("isin", "").strip()
    if not garbled or not correct:
        raise ValidationException("Both garbled_name and correct_name required", code="VAL-002")
    from services.ocr_correction import add_name_correction
    add_name_correction(garbled, correct, isin)
    return {"status": "ok", "message": f"Learned: '{garbled}' -> '{correct}'"}


@router.post("/admin/ocr-correction/holding")
async def correct_holding(request: Request):
    """Admin: correct a parsed holding's ISIN/name/qty/price."""
    user = await get_current_user(request)
    whitelist = await db.whitelisted_users.find_one({"email": user["email"]}, {"_id": 0})
    if not whitelist or not whitelist.get("is_admin"):
        raise AuthorizationException("Admin access required", code="AUTHZ-003")
    body = await request.json()
    holding_id = body.get("holding_id", "")
    corrections = body.get("corrections", {})
    if not holding_id or not corrections:
        raise ValidationException("holding_id and corrections required", code="VAL-002")
    holding = await db.holdings.find_one({"holding_id": holding_id}, {"_id": 0})
    if not holding:
        raise ResourceNotFoundException("Holding not found", code="RES-003")
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
        raise AuthorizationException("Admin access required", code="AUTHZ-003")
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
    """Persist the sandbox toggle.

    NOTE: CAS Parser API keys are no longer editable here — they live in
    Google Secret Manager only (secret: `casparser-api-keys-{env}`).
    Passing `prod_key` returns a 410 so callers know to retire that path.
    """
    user = await require_admin(request)
    body = await request.json()
    use_sandbox = body.get("use_sandbox")

    if body.get("prod_key") is not None:
        raise ValidationException(
            "CAS Parser API keys have moved to Google Secret Manager. "
            "Publish a new version with: "
            "`gcloud secrets versions add casparser-api-keys-<env> "
            "--data-file=- --project=niveshdataintelligence`, then "
            "POST /api/admin/cas-config/reload to pick it up.",
            code="VAL-001",
        )

    from services import cas_api_client

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


@router.post("/admin/cas-config/reload")
async def reload_cas_key_pool(request: Request):
    """Re-read the CAS key pool from Google Secret Manager. Use after
    `gcloud secrets versions add casparser-api-keys-<env> ...`."""
    await require_admin(request)
    from services import cas_api_client
    new_size = cas_api_client.reload_pool()
    return {"ok": True, "pool_size": new_size, "config": cas_api_client.get_effective_config()}


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


# ─── CAS Parser status ────────────────────────────────────────────────
# Fully in-house: casparser library (fast path) → Docling (table extraction).
# No external API providers. This endpoint reports local parser availability.

@router.get("/admin/cas-parser-provider")
async def get_cas_parser_provider(request: Request):
    """Return CAS parser status. Admin only."""
    await require_admin(request)
    from services.docling_cas_parser import is_available as _docling_ok
    return {
        "provider": "local",
        "chain": ["casparser_lib", "docling"],
        "casparser_lib_available": True,
        "docling_available": _docling_ok(),
        "note": "CAS parsing is fully in-house — no data sent to external services.",
    }


@router.get("/cas-parser-provider/active")
async def get_active_cas_parser_provider(request: Request):
    """Public endpoint: returns active parser identifier."""
    from deps import get_current_user
    await get_current_user(request)
    return {"provider": "local"}


# ═══ Secrets Management (generic CRUD, environment-scoped) ══════════════
@router.get("/admin/secrets")
async def list_secrets(request: Request, env: str = ""):
    """List secrets (masked) for the given environment. Admin only.

    ?env=staging|production — defaults to the deploy's current env.
    The response also includes `current_env` so the UI can warn when the
    operator is editing the *other* environment's secrets.
    """
    await require_admin(request)
    from helpers import secrets as _secrets
    target_env = env.strip().lower() or _secrets.current_env()
    target_env = "production" if target_env == "production" else "staging"
    items = await _secrets.list_for_env(db, target_env)
    persisted = await db.system_config.find_one(
        {"key": f"secrets:{target_env}"}, {"_id": 0}
    ) or {}
    return {
        "secrets": items,
        "updated_at": persisted.get("updated_at"),
        "updated_by": persisted.get("updated_by"),
        "current_env": _secrets.current_env(),
        "viewing_env": target_env,
        "available_envs": ["staging", "production"],
    }


@router.put("/admin/secrets/{key}")
async def upsert_secret(key: str, request: Request, env: str = ""):
    """Set or update a secret value in the given environment. Admin only."""
    user = await require_admin(request)
    body = await request.json()
    value = body.get("value")
    if value is None:
        raise ValidationException("value is required", code="VAL-002")
    if not value or not value.strip():
        raise ValidationException("value must not be empty", code="VAL-001")
    from helpers import secrets as _secrets
    target_env = env.strip().lower() or _secrets.current_env()
    await _secrets.persist_to_db(
        db, key, value.strip(),
        updated_by=user.get("email", ""),
        env=target_env,
    )
    return {
        "status": "ok", "key": key,
        "masked_value": _secrets.mask(value.strip()),
        "env": "production" if target_env == "production" else "staging",
    }


@router.delete("/admin/secrets/{key}")
async def delete_secret(key: str, request: Request, env: str = ""):
    """Remove override for a secret in the given environment. Admin only."""
    user = await require_admin(request)
    from helpers import secrets as _secrets
    target_env = env.strip().lower() or _secrets.current_env()
    await _secrets.persist_to_db(
        db, key, None,
        updated_by=user.get("email", ""),
        env=target_env,
    )
    return {
        "status": "ok", "key": key, "deleted": True,
        "env": "production" if target_env == "production" else "staging",
    }


@router.get("/admin/secrets/{key}/reveal")
async def reveal_secret(key: str, request: Request, env: str = ""):
    """Return the FULL plaintext value of one secret for the given env.

    Admin-only. Every successful reveal is recorded to the audit log so
    we can see who looked at which credential and when. Use this for the
    "show / copy" buttons on the admin Secrets page.
    """
    user = await require_admin(request)
    from helpers import secrets as _secrets
    target_env = (env.strip().lower() or _secrets.current_env())
    target_env = "production" if target_env == "production" else "staging"

    # Read the value from the env-scoped doc; fall back to the legacy
    # shared doc; finally fall back to process env (current deploy only).
    value: Optional[str] = None
    source = "missing"
    scoped_doc = await db.system_config.find_one(
        {"key": f"secrets:{target_env}"}, {"_id": 0, "values": 1},
    )
    scoped_val = ((scoped_doc or {}).get("values") or {}).get(key)
    if isinstance(scoped_val, str) and scoped_val:
        value = scoped_val
        source = f"secrets:{target_env}"
    if value is None:
        legacy_doc = await db.system_config.find_one(
            {"key": "secrets"}, {"_id": 0, "values": 1},
        )
        legacy_val = ((legacy_doc or {}).get("values") or {}).get(key)
        if isinstance(legacy_val, str) and legacy_val:
            value = legacy_val
            source = "secrets (legacy shared)"
    if value is None and target_env == _secrets.current_env():
        env_val = os.environ.get(key)
        if env_val:
            value = env_val
            source = "process env"

    # Audit — who revealed which key for which env.
    try:
        from services import audit
        await audit.record(
            user_id=user.get("user_id", ""),
            action="secret_reveal",
            metadata={
                "secret_key": key,
                "env": target_env,
                "source": source,
                "actor_email": user.get("email"),
            },
        )
    except Exception:  # noqa: BLE001
        logger.warning("secret reveal audit log failed", exc_info=True)

    return {
        "key": key,
        "env": target_env,
        "source": source,
        "configured": value is not None,
        "value": value,
        "masked_value": _secrets.mask(value) if value else "",
    }


@router.post("/admin/secrets/promote")
async def promote_secrets(request: Request):
    """Copy secrets from one environment to another. Admin only.

    Body: {source: "staging"|"production", target: "staging"|"production",
           keys: ["KEY1","KEY2",...] or null for "all"}
    """
    user = await require_admin(request)
    body = await request.json()
    src = (body.get("source") or "").strip().lower()
    tgt = (body.get("target") or "").strip().lower()
    if src not in ("staging", "production") or tgt not in ("staging", "production"):
        raise ValidationException("source and target must be staging|production", code="VAL-003")
    if src == tgt:
        raise ValidationException("source and target must differ", code="VAL-001")
    keys_filter = body.get("keys")  # None → all

    src_doc = await db.system_config.find_one({"key": f"secrets:{src}"}, {"_id": 0}) or {}
    src_vals = src_doc.get("values") or {}

    from helpers import secrets as _secrets
    copied = []
    for k, v in src_vals.items():
        if keys_filter and k not in keys_filter:
            continue
        if not isinstance(v, str) or not v:
            continue
        await _secrets.persist_to_db(
            db, k, v,
            updated_by=f"{user.get('email','')} [promote {src}→{tgt}]",
            env=tgt,
        )
        copied.append(k)
    return {"status": "ok", "source": src, "target": tgt, "copied": copied, "count": len(copied)}


@router.post("/admin/secrets/{key}/test")
async def test_secret(key: str, request: Request):
    """Invoke the registered test handler for a known secret. Admin only."""
    await require_admin(request)
    from helpers import secrets as _secrets
    meta = _secrets.KNOWN_SECRETS.get(key)
    if not meta or not meta.get("test_fn"):
        raise ValidationException("No test available for this secret", code="VAL-001")
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

    if test_fn == "postgres":
        from services import pg_client
        # Force pool rebuild against latest URL
        await pg_client.close_pool()
        res = await pg_client.ping()
        if res.get("ok"):
            return {"ok": True, "detail": f"Connected — {res.get('version', '')[:60]}"}
        return {"ok": False, "error": res.get("reason", "unknown")}

    if test_fn == "redis":
        from services import redis_client
        await redis_client.close_client()
        res = await redis_client.ping()
        if res.get("ok"):
            return {"ok": True, "detail": f"Connected — redis {res.get('version', '')}"}
        return {"ok": False, "error": res.get("reason", "unknown")}

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
        raise ValidationException(str(e), code="VAL-001")
    await feature_flags.persist_to_db(db, updated_by=user.get("email", ""))
    return {"status": "ok", "flag": flag}


@router.post("/admin/feature-flags/{flag}/users")
async def add_feature_user(flag: str, request: Request):
    """Add an email to a flag's allowlist. Admin only."""
    user = await require_admin(request)
    body = await request.json()
    email = (body.get("email") or "").strip()
    if not email:
        raise ValidationException("email is required", code="VAL-002")
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


@router.post("/admin/nidp/export-portfolio")
async def trigger_portfolio_gcs_export(request: Request):
    """Export Nivesh portfolio holdings to GCS landing zone for NIDP consumption.

    Optional body: {"date": "YYYY-MM-DD"} to export a specific snapshot date.
    Default: latest snapshot per client.
    """
    await require_admin(request)
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    target_date = None
    if body.get("date"):
        from datetime import date as _date
        try:
            target_date = _date.fromisoformat(body["date"])
        except ValueError:
            raise ValidationException("Invalid date format, use YYYY-MM-DD", code="VAL-003")

    from services.portfolio_gcs_export import export_portfolio_to_gcs

    try:
        result = await export_portfolio_to_gcs(db, target_date=target_date)
        logger.info("portfolio GCS export triggered by admin: %s", result)
        return {"status": "ok", **result}
    except Exception as exc:
        logger.error("portfolio GCS export failed: %s", exc, exc_info=True)
        raise SystemException(str(exc), code="SYS-001", cause=exc)


@router.post("/admin/nidp/full-portfolio-sync")
async def trigger_full_portfolio_sync(request: Request):
    """Run the full Nivesh → GCS → NIDP portfolio sync chain.

    Stage 1 — Nivesh → GCS exporters (Mongo + PG → JSONL):
      * portfolio_gcs_export.export_portfolio_to_gcs       (holdings)
      * portfolio_gcs_export.export_cas_transactions_to_gcs (CAS txns)
      * portfolio_gcs_export.export_user_goals_to_gcs       (goals)

    Stage 2 — NIDP-side ingesters (GCS → TimescaleDB), via NIDP Query API:
      * portfolio_holdings_sync
      * portfolio_transactions_sync
      * portfolio_goals_sync
      * portfolio_intelligence_sync (joins all three + computes analytics)

    Stage 2 is skipped (with a warning) if NIDP_QUERY_API_URL/TOKEN aren't
    configured — useful when smoke-testing just the export side.

    Optional body: {"date": "YYYY-MM-DD"} for the snapshot date label.
    Admin only.
    """
    await require_admin(request)
    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        pass

    target_date = None
    if body.get("date"):
        from datetime import date as _date
        try:
            target_date = _date.fromisoformat(body["date"])
        except ValueError:
            raise ValidationException("Invalid date format, use YYYY-MM-DD", code="VAL-003")

    from services.portfolio_gcs_export import (
        export_portfolio_to_gcs,
        export_cas_transactions_to_gcs,
        export_user_goals_to_gcs,
    )
    from services import nidp_query_client as _nq

    result: dict = {"status": "ok", "date": target_date.isoformat() if target_date else None,
                    "gcs_exports": {}, "nidp_feeds": {}, "errors": []}

    # ── Stage 1: Nivesh → GCS ─────────────────────────────────────────
    for name, fn in (
        ("holdings",     export_portfolio_to_gcs),
        ("transactions", export_cas_transactions_to_gcs),
        ("goals",        export_user_goals_to_gcs),
    ):
        try:
            res = await fn(db, target_date=target_date)
            result["gcs_exports"][name] = res
            logger.info("full-portfolio-sync: %s export → %s", name, res)
        except Exception as exc:  # noqa: BLE001
            logger.error("full-portfolio-sync: %s export failed: %s", name, exc, exc_info=True)
            result["gcs_exports"][name] = {"error": str(exc)}
            result["errors"].append(f"export:{name}: {exc}")

    # ── Stage 2: GCS → NIDP TimescaleDB (only if Query API wired) ────
    if not _nq.is_configured():
        result["nidp_feeds"]["skipped_reason"] = (
            "NIDP_QUERY_API_URL/TOKEN not configured — Stage 2 skipped"
        )
        logger.warning("full-portfolio-sync: NIDP Query API not configured, skipping NIDP-side triggers")
    else:
        date_param = target_date.isoformat() if target_date else None
        # Order is load-bearing — intelligence sync joins the other three.
        for ingester in (
            "portfolio_holdings_sync",
            "portfolio_transactions_sync",
            "portfolio_goals_sync",
            "portfolio_intelligence_sync",
        ):
            try:
                resp = await _nq.execute_feed(ingester, target_date=date_param)
                result["nidp_feeds"][ingester] = {"ok": True, **resp}
                logger.info("full-portfolio-sync: spawned %s on VM (date=%s)", ingester, date_param or "default")
            except _nq.NidpQueryClientError as exc:
                logger.error("full-portfolio-sync: %s execute failed: %s", ingester, exc.detail)
                result["nidp_feeds"][ingester] = {"ok": False, "error": exc.detail, "status": exc.status}
                result["errors"].append(f"feed:{ingester}: {exc.detail}")

    if result["errors"]:
        result["status"] = "partial"
    return result
