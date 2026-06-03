"""Admin routes for User Management.

All endpoints require admin session. Safe-by-default — destructive actions
(delete, invalidate) are explicit and non-batched.
"""
import re
import uuid
from fastapi import APIRouter, HTTPException, Request
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone
import logging

from deps import db, require_admin
from core.logging_config import mask_email

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin")

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@router.get("/users")
async def list_users(request: Request, q: Optional[str] = None) -> Dict[str, Any]:
    """List all users with stats. Optional email-prefix search via `q`."""
    await require_admin(request)
    filter_q: Dict[str, Any] = {}
    if q and q.strip():
        filter_q = {"email": {"$regex": q.strip(), "$options": "i"}}
    users = await db.users.find(filter_q, {"_id": 0}).sort("created_at", -1).to_list(500)

    # Build per-user stats with parallel counts
    out: List[Dict[str, Any]] = []
    for u in users:
        uid = u.get("user_id")
        # Use count_documents sequentially — 100-200 users is fine
        holdings_cnt = await db.holdings.count_documents({"user_id": uid})
        mf_cnt = await db.holdings.count_documents(
            {"user_id": uid, "asset_type": {"$in": ["mutual_fund", "etf"]}}
        )
        plans_cnt = await db.action_plans.count_documents({"user_id": uid})
        active_plan = await db.action_plans.find_one(
            {"user_id": uid, "status": "active"}, {"_id": 0, "plan_id": 1, "portfolio_score": 1, "created_at": 1}
        )
        last_session = await db.user_sessions.find_one(
            {"user_id": uid}, {"_id": 0, "created_at": 1, "expires_at": 1},
            sort=[("created_at", -1)],
        )
        out.append({
            "user_id": uid,
            "email": u.get("email"),
            "name": u.get("name"),
            "picture": u.get("picture"),
            "is_admin": bool(u.get("is_admin")),
            "risk_profile": u.get("risk_profile"),
            "created_at": u.get("created_at"),
            "holdings_count": holdings_cnt,
            "mf_count": mf_cnt,
            "plans_count": plans_cnt,
            "active_plan": active_plan,
            "last_login_at": last_session.get("created_at") if last_session else None,
            "session_active": _session_alive(last_session),
        })
    return {"users": out, "total": len(out)}


def _session_alive(sess) -> bool:
    """True if the session's expires_at is in the future. Tolerates both
    timezone-aware and naive datetimes (older docs may be naive UTC)."""
    if not sess or not sess.get("expires_at"):
        return False
    raw = sess["expires_at"]
    try:
        if isinstance(raw, datetime):
            exp = raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
        else:
            exp = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return False
    return exp > datetime.now(timezone.utc)


@router.post("/users")
async def create_user(request: Request) -> Dict[str, Any]:
    """Admin-create a user. Whitelists the email (which is what gates
    Google sign-in) and pre-creates the `users` + `user_profiles` rows
    so the user appears in the admin directory immediately. They become
    fully active on first sign-in (Google OAuth fills picture/etc.).

    Body: {email: str, name?: str, is_admin?: bool}
    """
    admin = await require_admin(request)
    body = await request.json()
    email = (body.get("email") or "").strip().lower()
    name = (body.get("name") or "").strip() or None
    is_admin = bool(body.get("is_admin"))

    if not _EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="Invalid email address")

    # Reject duplicates explicitly so the admin sees a clear error rather
    # than a silent upsert collapsing two intents into one row.
    existing = await db.users.find_one({"email": email}, {"_id": 0, "user_id": 1})
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"User with email {email} already exists (user_id={existing['user_id']})",
        )

    now_iso = datetime.now(timezone.utc).isoformat()
    user_id = f"user_{uuid.uuid4().hex[:12]}"

    # Whitelist (gates Google OAuth on first login)
    await db.whitelisted_users.update_one(
        {"email": email},
        {"$set": {
            "email": email,
            "is_admin": is_admin,
            "status": "invited",
            "invited_at": now_iso,
            "invited_by": admin.get("email"),
        }},
        upsert=True,
    )

    # Pre-create users row so they show in the admin list before first login
    await db.users.insert_one({
        "user_id": user_id,
        "email": email,
        "name": name,
        "picture": None,
        "is_admin": is_admin,
        "created_at": now_iso,
        "created_by_admin": admin.get("email"),
        "invited": True,
    })

    # Minimal user_profiles row (onboarding flags = false so first login
    # walks the welcome flow normally).
    await db.user_profiles.update_one(
        {"user_id": user_id},
        {"$set": {
            "user_id": user_id,
            "email": email,
            "onboarding_completed": False,
            "created_at": now_iso,
            "updated_at": now_iso,
        }},
        upsert=True,
    )

    logger.info(
        "admin[%s] created user (user_id=%s, is_admin=%s)",
        mask_email(admin.get("email", "")), user_id, is_admin,
    )
    user_doc = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    return {"ok": True, "user": user_doc}


@router.get("/users/{user_id}")
async def get_user(user_id: str, request: Request) -> Dict[str, Any]:
    await require_admin(request)
    u = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    # Extra detail for drill-down
    recent_plans = await db.action_plans.find(
        {"user_id": user_id},
        {"_id": 0, "plan_id": 1, "status": 1, "portfolio_score": 1, "created_at": 1, "actions": 1},
    ).sort("created_at", -1).to_list(10)
    # Trim actions to counts only to keep payload lean
    for p in recent_plans:
        p["actions_count"] = len(p.pop("actions", []) or [])
    sessions = await db.user_sessions.find(
        {"user_id": user_id},
        {"_id": 0, "session_token": 0},
    ).sort("created_at", -1).to_list(10)
    return {"user": u, "recent_plans": recent_plans, "sessions": sessions}


@router.patch("/users/{user_id}")
async def update_user(user_id: str, request: Request) -> Dict[str, Any]:
    """Toggle is_admin (only editable field right now)."""
    admin = await require_admin(request)
    body = await request.json()
    updates: Dict[str, Any] = {}
    if "is_admin" in body:
        updates["is_admin"] = bool(body["is_admin"])
    if not updates:
        raise HTTPException(status_code=400, detail="No editable fields in request")

    # Prevent an admin from demoting themselves to zero-admin state
    if updates.get("is_admin") is False and admin.get("user_id") == user_id:
        remaining = await db.users.count_documents({"is_admin": True, "user_id": {"$ne": user_id}})
        if remaining == 0:
            raise HTTPException(status_code=400, detail="Cannot demote the last remaining admin")

    result = await db.users.update_one({"user_id": user_id}, {"$set": updates})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="User not found")

    # Mirror is_admin to whitelist so it survives re-login
    if "is_admin" in updates:
        u = await db.users.find_one({"user_id": user_id}, {"_id": 0, "email": 1})
        if u and u.get("email"):
            await db.whitelisted_users.update_one(
                {"email": u["email"]},
                {"$set": {"is_admin": updates["is_admin"]}},
                upsert=True,
            )
    logger.info("admin[%s] updated user %s: %s", mask_email(admin.get('email', '')), user_id, updates)
    return {"ok": True, "updates": updates}


@router.post("/users/{user_id}/invalidate-sessions")
async def invalidate_user_sessions(user_id: str, request: Request) -> Dict[str, Any]:
    """Force-logout a user from all devices by deleting their sessions."""
    admin = await require_admin(request)
    result = await db.user_sessions.delete_many({"user_id": user_id})
    logger.info("admin[%s] invalidated %s sessions for user %s", mask_email(admin.get('email', '')), result.deleted_count, user_id)
    return {"ok": True, "deleted_sessions": result.deleted_count}


# Collections wiped by reset_portfolio_data. Every entry must have a
# `user_id` field for per-user filtering. Order is largest first so the
# cumulative counters in the UI feel responsive.
_RESET_COLLECTIONS: List[str] = [
    "holdings",
    "portfolios",
    "portfolio_analysis",
    "portfolio_analysis_deep",
    "portfolio_snapshots",
    "ai_insights",
    "action_plans",
    "pending_actions",
    "cas_parsed_responses",
    "cas_transactions",
    "detected_sips",
    "saved_scenarios",
    "scenario_simulations",
    "upload_tasks",
    "chat_sessions",
    "chat_messages",
    "copilot_cache",
    "allocation_analysis_cache",
    "fund_performance_cache",
    "mfd_profile_signal_cache",
    "gmail_imports",
]

# Extra collections wiped only by /reset-full (mirrors scripts/reset_user_full.py).
_FULL_RESET_EXTRA_COLLECTIONS: List[str] = [
    "portfolio_holdings",
    "capital_gains_summary",
    "international_funds_cache",
    "fund_holdings_cache",
]

_REDIS_PATTERNS = [
    "snap:*:{uid}",
    "score:user:{uid}*",
    "v3:user:{uid}*",
    "actionplan:{uid}*",
    "copilot:{uid}*",
]


async def _wipe_user_mongo_and_redis(user_id: str, collections: List[str]):
    """Shared core for reset endpoints. Returns
    (deleted_per_collection, profile_modified, redis_cleared, now_iso).
    Does NOT touch NIDP Postgres — caller adds that if needed."""
    deleted: Dict[str, int] = {}
    for col in collections:
        try:
            res = await db[col].delete_many({"user_id": user_id})
            deleted[col] = res.deleted_count
        except Exception as e:  # noqa: BLE001
            logger.warning("reset: skip %s for %s: %s", col, user_id, e)
            deleted[col] = 0

    now_iso = datetime.now(timezone.utc).isoformat()
    profile_res = await db.user_profiles.update_one(
        {"user_id": user_id},
        {"$set": {**_RESET_PROFILE_FIELDS, "updated_at": now_iso}},
    )
    await db.users.update_one(
        {"user_id": user_id},
        {"$unset": {"cas_view_state": ""}},
    )

    redis_cleared = 0
    try:
        from services.redis_client import get_client as _get_redis
        rc = await _get_redis()
        if rc is not None:
            for pat_tmpl in _REDIS_PATTERNS:
                pat = pat_tmpl.format(uid=user_id)
                try:
                    cursor = 0
                    while True:
                        cursor, keys = await rc.scan(cursor=cursor, match=pat, count=200)
                        if keys:
                            await rc.delete(*keys)
                            redis_cleared += len(keys)
                        if cursor == 0:
                            break
                except Exception as e:  # noqa: BLE001
                    logger.info("redis scan/delete skipped for pattern %s: %s", pat, e)
    except Exception as e:  # noqa: BLE001
        logger.info("Redis client unavailable, skipping cache flush: %s", e)

    return deleted, bool(profile_res.modified_count), redis_cleared, now_iso


async def _wipe_user_nidp_pg(email: str) -> Dict[str, int]:
    """Per-user wipe on NIDP Postgres. Keyed by external_user_id which
    equals the user's email in this stack. Returns counts per table.
    Tables not present (per env) are silently skipped with count 0."""
    out: Dict[str, int] = {
        "portfolio.user_intelligence_snapshot": 0,
        "portfolio.user_holdings_snapshot": 0,
        "nidp.validation_findings": 0,
    }
    try:
        from nidp.shared.storage.pg import get_pool
    except Exception as e:  # noqa: BLE001
        logger.warning("NIDP pg unavailable; skipping pg wipe: %s", e)
        return out

    try:
        pool = await get_pool()
    except Exception as e:  # noqa: BLE001
        logger.warning("NIDP pg pool init failed; skipping pg wipe: %s", e)
        return out

    async with pool.acquire() as conn:
        for table in list(out.keys()):
            try:
                tag = await conn.execute(
                    f"DELETE FROM {table} WHERE external_user_id = $1",
                    email,
                )
                # asyncpg returns "DELETE <n>"
                try:
                    out[table] = int(tag.split()[-1])
                except (ValueError, IndexError):
                    out[table] = 0
            except Exception as e:  # noqa: BLE001
                logger.info("nidp wipe: skip %s (%s)", table, e)
    return out

# Onboarding-flag fields cleared on `user_profiles` (mirrors the global
# `scripts/reset_portfolio_data.py` so the user re-runs onboarding on
# next login). `cas_view_state` is also cleared from the `users` doc so
# the dashboard doesn't pin to a stale CAS snapshot.
_RESET_PROFILE_FIELDS: Dict[str, Any] = {
    "onboarding_completed": False,
    "journey_type": None,
    "risk_profile": None,
    "playbook": None,
    "goals": [],
    "selected_sources": [],
}


@router.post("/users/{user_id}/reset-portfolio")
async def reset_user_portfolio(user_id: str, request: Request) -> Dict[str, Any]:
    """Wipe a single user's portfolio + insights data and reset their
    onboarding flags so they appear as a brand-new user. Used by
    admins to retest onboarding flows on a real account.

    Preserves: the `users` row itself, sessions, whitelist, gmail_tokens,
    workspaces, profiles (family members), consent_records, audit_log.
    Also preserves NIDP Postgres rows (see /reset-full for that).
    """
    admin = await require_admin(request)

    user = await db.users.find_one({"user_id": user_id}, {"_id": 0, "email": 1, "name": 1})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    deleted, profile_modified, redis_cleared, now_iso = await _wipe_user_mongo_and_redis(
        user_id, _RESET_COLLECTIONS
    )
    total_deleted = sum(deleted.values())

    audit_doc = {
        "kind": "admin.reset_portfolio",
        "actor_user_id": admin.get("user_id"),
        "actor_email": admin.get("email"),
        "target_user_id": user_id,
        "target_email": user.get("email"),
        "deleted_per_collection": deleted,
        "total_deleted": total_deleted,
        "profile_modified": int(profile_modified),
        "redis_keys_cleared": redis_cleared,
        "timestamp": now_iso,
    }
    try:
        await db.audit_log.insert_one(audit_doc)
    except Exception as e:  # noqa: BLE001
        logger.warning("audit log insert failed: %s", e)

    logger.info(
        "admin[%s] reset portfolio for user %s (%s): %d docs, %d redis keys",
        admin.get("email"), user_id, user.get("email"), total_deleted, redis_cleared,
    )

    return {
        "ok": True,
        "user_id": user_id,
        "user_email": user.get("email"),
        "deleted_per_collection": deleted,
        "total_deleted": total_deleted,
        "profile_reset": profile_modified,
        "redis_keys_cleared": redis_cleared,
    }


@router.post("/users/{user_id}/reset-full")
async def reset_user_full(user_id: str, request: Request) -> Dict[str, Any]:
    """Hard reset — everything /reset-portfolio does, PLUS:
      * extra Mongo caches (portfolio_holdings, capital_gains_summary,
        international_funds_cache, fund_holdings_cache)
      * NIDP TimescaleDB rows keyed by external_user_id = email:
        portfolio.user_intelligence_snapshot,
        portfolio.user_holdings_snapshot (cascades to holding_security_map),
        nidp.validation_findings.

    Equivalent to running scripts/reset_user_full.py from an admin shell.
    Preserves: the `users` row, sessions, whitelist, gmail_tokens,
    workspaces, family profiles, consent_records, audit_log.

    Use with care — NIDP wipe is unrecoverable without re-running the
    portfolio_intelligence_sync job.
    """
    admin = await require_admin(request)

    user = await db.users.find_one({"user_id": user_id}, {"_id": 0, "email": 1, "name": 1})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    email = user.get("email") or ""

    collections = _RESET_COLLECTIONS + _FULL_RESET_EXTRA_COLLECTIONS
    deleted, profile_modified, redis_cleared, now_iso = await _wipe_user_mongo_and_redis(
        user_id, collections
    )
    total_deleted = sum(deleted.values())

    pg_deleted = await _wipe_user_nidp_pg(email) if email else {}
    pg_total = sum(pg_deleted.values())

    audit_doc = {
        "kind": "admin.reset_full",
        "actor_user_id": admin.get("user_id"),
        "actor_email": admin.get("email"),
        "target_user_id": user_id,
        "target_email": email,
        "deleted_per_collection": deleted,
        "total_deleted": total_deleted,
        "pg_deleted_per_table": pg_deleted,
        "pg_total_deleted": pg_total,
        "profile_modified": int(profile_modified),
        "redis_keys_cleared": redis_cleared,
        "timestamp": now_iso,
    }
    try:
        await db.audit_log.insert_one(audit_doc)
    except Exception as e:  # noqa: BLE001
        logger.warning("audit log insert failed: %s", e)

    logger.info(
        "admin[%s] FULL reset for user %s (%s): %d mongo docs, %d pg rows, %d redis keys",
        admin.get("email"), user_id, email, total_deleted, pg_total, redis_cleared,
    )

    return {
        "ok": True,
        "scope": "full",
        "user_id": user_id,
        "user_email": email,
        "deleted_per_collection": deleted,
        "total_deleted": total_deleted,
        "pg_deleted_per_table": pg_deleted,
        "pg_total_deleted": pg_total,
        "profile_reset": profile_modified,
        "redis_keys_cleared": redis_cleared,
    }


@router.post("/users/{user_id}/restore-holdings")
async def restore_holdings_from_snapshot(user_id: str, request: Request) -> Dict[str, Any]:
    """Re-mount the latest CAS snapshot into db.holdings for a user whose
    holdings collection is empty despite a snapshot existing.

    Safe to call multiple times — it replaces (not appends) the holdings."""
    admin = await require_admin(request)
    user = await db.users.find_one({"user_id": user_id}, {"_id": 0, "email": 1})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    from services import cas_snapshot_engine as _eng
    latest_date = await _eng.get_latest_snapshot_date(user_id)
    if not latest_date:
        raise HTTPException(status_code=404, detail="No CAS snapshot with holdings found for this user")

    snap = await _eng.load_snapshot_into_holdings(user_id, latest_date)
    holdings_loaded = len(snap.get("holdings") or [])
    logger.info(
        "admin[%s] restored holdings for %s (%s) from snapshot %s: %d holdings",
        admin.get("email"), user_id, user.get("email"), latest_date, holdings_loaded,
    )
    return {
        "ok": True,
        "user_id": user_id,
        "user_email": user.get("email"),
        "snapshot_date": latest_date,
        "holdings_loaded": holdings_loaded,
    }


# ── Identity uniqueness ────────────────────────────────────────────────
@router.get("/identity/duplicates")
async def list_identity_duplicates(request: Request):
    """Scan all users + profiles and surface every email / mobile / PAN
    that maps to more than one record. Used by the admin UI to clean up
    ghost users created before the uniqueness gate was added."""
    await require_admin(request)
    from services import identity_uniqueness as _iu
    return await _iu.scan_existing_duplicates()


@router.post("/identity/check")
async def check_identity(request: Request):
    """Pre-flight check — given (email, mobile, pan), report whether any
    of them already exist on a user or client profile. The advisor's
    "Add client" form calls this on blur before submitting so the
    advisor sees the conflict inline instead of as a 409 on save."""
    await require_admin(request)
    from services import identity_uniqueness as _iu
    body = await request.json()
    chk = await _iu.check_identity_uniqueness(
        email=body.get("email"),
        mobile=body.get("mobile"),
        pan=body.get("pan"),
        exclude_profile_id=body.get("exclude_profile_id"),
        exclude_user_id=body.get("exclude_user_id"),
    )
    return chk.to_dict()


@router.post("/identity/backfill")
async def backfill_identity_norms(request: Request):
    """Compute `email_norm` / `mobile_norm` / `pan_norm` on every existing
    row that's missing them, so the duplicate-scan + uniqueness check
    can find legacy data. Idempotent."""
    await require_admin(request)
    from services import identity_uniqueness as _iu
    from deps import db as _db
    updated_profiles = 0
    async for p in _db.profiles.find(
        {}, {"_id": 1, "email": 1, "mobile": 1, "pan": 1,
             "email_norm": 1, "mobile_norm": 1, "pan_norm": 1},
    ):
        ident = _iu.stamped_identity_fields(
            email=p.get("email"), mobile=p.get("mobile"), pan=p.get("pan"),
        )
        if not ident:
            continue
        # Only write the *_norm side; preserve any displayed value formatting.
        norm_only = {k: v for k, v in ident.items() if k.endswith("_norm")}
        if any(p.get(k) != v for k, v in norm_only.items()):
            await _db.profiles.update_one({"_id": p["_id"]}, {"$set": norm_only})
            updated_profiles += 1
    updated_users = 0
    async for u in _db.users.find(
        {}, {"_id": 1, "email": 1, "mobile": 1, "pan": 1,
             "email_norm": 1, "mobile_norm": 1, "pan_norm": 1},
    ):
        ident = _iu.stamped_identity_fields(
            email=u.get("email"), mobile=u.get("mobile"), pan=u.get("pan"),
        )
        if not ident:
            continue
        norm_only = {k: v for k, v in ident.items() if k.endswith("_norm")}
        if any(u.get(k) != v for k, v in norm_only.items()):
            await _db.users.update_one({"_id": u["_id"]}, {"$set": norm_only})
            updated_users += 1
    return {"profiles_updated": updated_profiles, "users_updated": updated_users}


# ── Datastore isolation audit ──────────────────────────────────────────
@router.get("/datastore-isolation")
async def datastore_isolation(request: Request):
    """Show whether staging and production point at distinct Postgres /
    Redis / Mongo datastores. Returns a per-key SHA-256 fingerprint
    matrix (no full URLs leaked) and an explicit `collisions` list.

    The operator should ensure all three keys differ between the two
    environments. To fix a collision, set a distinct value for the key
    on the production-scoped secrets doc via the existing secret-edit
    flow (PATCH /api/admin/secrets ... env=production)."""
    await require_admin(request)
    from helpers import datastore_isolation as _di
    return await _di.audit_isolation(db)


@router.post("/whitelist-repair")
async def whitelist_repair(request: Request) -> Dict[str, Any]:
    """Check and repair whitelist entry for a user by email.
    If the user exists in `users` but not in `whitelisted_users`, re-adds them.
    Protected by a static secret key (X-Admin-Key header).

    curl -X POST https://niveshcopilot.com/api/admin/whitelist-repair \
         -H 'Content-Type: application/json' \
         -H 'X-Admin-Key: niv3sh-reset-2026' \
         -d '{"email": "user@example.com"}'
    """
    key = request.headers.get("X-Admin-Key", "")
    if key != "niv3sh-reset-2026":
        raise HTTPException(status_code=403, detail="Invalid admin key")

    body = await request.json()
    email = (body.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="email required")

    user = await db.users.find_one({"email": email}, {"_id": 0, "user_id": 1, "is_admin": 1})
    wl = await db.whitelisted_users.find_one({"email": email}, {"_id": 0})

    action = "none"
    if not wl:
        now_iso = datetime.now(timezone.utc).isoformat()
        await db.whitelisted_users.update_one(
            {"email": email},
            {"$set": {
                "email": email,
                "is_admin": bool((user or {}).get("is_admin")),
                "status": "active",
                "invited_at": now_iso,
                "invited_by": "system/whitelist-repair",
            }},
            upsert=True,
        )
        action = "added"
    else:
        action = "already_present"

    return {
        "ok": True,
        "email": email,
        "user_exists": bool(user),
        "whitelist_action": action,
        "whitelist_status": wl.get("status") if wl else None,
    }


@router.post("/reset-onboarding")
async def reset_onboarding_by_email(request: Request) -> Dict[str, Any]:
    """Reset onboarding flags for a user by email.
    Protected by a static secret key (X-Admin-Key header).
    curl -X POST https://niveshcopilot.com/api/admin/reset-onboarding \
         -H 'Content-Type: application/json' \
         -H 'X-Admin-Key: niv3sh-reset-2026' \
         -d '{"email": "user@example.com"}'
    """
    key = request.headers.get("X-Admin-Key", "")
    if key != "niv3sh-reset-2026":
        raise HTTPException(status_code=403, detail="Invalid admin key")

    body = await request.json()
    email = (body.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="email required")

    user = await db.users.find_one({"email": email}, {"_id": 0, "user_id": 1})
    if not user:
        raise HTTPException(status_code=404, detail=f"User not found: {email}")

    user_id = user["user_id"]
    await db.users.update_one(
        {"user_id": user_id},
        {"$set": {"onboarding_completed": False}},
    )
    await db.user_profiles.update_one(
        {"user_id": user_id},
        {"$set": {"onboarding_completed": False, "journey_type": None}},
    )
    return {"ok": True, "user_id": user_id, "email": email}


@router.post("/mark-onboarded")
async def mark_onboarded_by_email(request: Request) -> Dict[str, Any]:
    """Flip onboarding_completed=True for a user by email — the inverse of
    /reset-onboarding. Used to repair accounts whose CAS import landed
    before the import-connect endpoint was fixed to set the flag.

    curl -X POST https://niveshcopilot.com/api/admin/mark-onboarded \\
         -H 'Content-Type: application/json' \\
         -H 'X-Admin-Key: niv3sh-reset-2026' \\
         -d '{"email": "user@example.com"}'
    """
    key = request.headers.get("X-Admin-Key", "")
    if key != "niv3sh-reset-2026":
        raise HTTPException(status_code=403, detail="Invalid admin key")

    body = await request.json()
    email = (body.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="email required")

    user = await db.users.find_one({"email": email}, {"_id": 0, "user_id": 1})
    if not user:
        raise HTTPException(status_code=404, detail=f"User not found: {email}")

    user_id = user["user_id"]
    now = datetime.now(timezone.utc)
    await db.user_profiles.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "onboarding_completed": True,
                "journey_type": "existing_investor",
                "updated_at": now,
            },
            "$setOnInsert": {"user_id": user_id, "created_at": now},
        },
        upsert=True,
    )
    return {"ok": True, "user_id": user_id, "email": email}


@router.post("/gmail-scan")
async def admin_gmail_scan(request: Request) -> Dict[str, Any]:
    """Scan Gmail for CAS emails using stored tokens for a user.
    Protected by X-Admin-Key header. Bypasses OAuth UI for testing.

    curl -X POST https://niveshcopilot.com/api/admin/gmail-scan \\
         -H 'X-Admin-Key: niv3sh-reset-2026' \\
         -H 'Content-Type: application/json' \\
         -d '{"email": "user@example.com"}'
    """
    key = request.headers.get("X-Admin-Key", "")
    if key != "niv3sh-reset-2026":
        raise HTTPException(status_code=403, detail="Invalid admin key")

    body = await request.json()
    email = (body.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="email required")

    user = await db.users.find_one({"email": email}, {"_id": 0, "user_id": 1})
    if not user:
        raise HTTPException(status_code=404, detail=f"User not found: {email}")
    user_id = user["user_id"]

    token_doc = await db.gmail_tokens.find_one({"user_id": user_id}, {"_id": 0})
    if not token_doc:
        raise HTTPException(status_code=400, detail="No Gmail tokens found — user must connect Gmail first via OAuth")

    from services.gmail_service import get_gmail_credentials, build_gmail_service, scan_for_cas_emails
    creds = get_gmail_credentials(token_doc)
    service = build_gmail_service(creds)

    # Refresh token if needed
    if creds.token != token_doc.get("access_token"):
        await db.gmail_tokens.update_one(
            {"user_id": user_id},
            {"$set": {
                "access_token": creds.token,
                "expires_at": creds.expiry.isoformat() if creds.expiry else None,
            }}
        )

    emails = scan_for_cas_emails(service, max_results=20)

    imported_ids = set()
    existing = await db.gmail_imports.find(
        {"user_id": user_id, "status": "completed"},
        {"_id": 0, "message_id": 1}
    ).to_list(500)
    imported_ids = {e["message_id"] for e in existing}

    for e in emails:
        e["already_imported"] = e["message_id"] in imported_ids

    return {
        "user_id": user_id,
        "gmail_connected": True,
        "emails_found": len(emails),
        "emails": emails,
    }


@router.post("/gmail-import")
async def admin_gmail_import(request: Request) -> Dict[str, Any]:
    """Import a specific CAS email for a user using stored Gmail tokens.
    Protected by X-Admin-Key header.

    curl -X POST https://niveshcopilot.com/api/admin/gmail-import \\
         -H 'X-Admin-Key: niv3sh-reset-2026' \\
         -H 'Content-Type: application/json' \\
         -d '{"email": "user@example.com", "message_id": "...", "attachment_id": "...", "filename": "CAS.pdf", "password": "PANXXXX"}'
    """
    from fastapi import BackgroundTasks
    key = request.headers.get("X-Admin-Key", "")
    if key != "niv3sh-reset-2026":
        raise HTTPException(status_code=403, detail="Invalid admin key")

    body = await request.json()
    email = (body.get("email") or "").strip().lower()
    message_id = body.get("message_id", "")
    attachment_id = body.get("attachment_id", "")
    filename = body.get("filename", "cas.pdf")
    password = body.get("password", "")

    if not email or not message_id or not attachment_id:
        raise HTTPException(status_code=400, detail="email, message_id, attachment_id required")

    user = await db.users.find_one({"email": email}, {"_id": 0, "user_id": 1})
    if not user:
        raise HTTPException(status_code=404, detail=f"User not found: {email}")
    user_id = user["user_id"]

    token_doc = await db.gmail_tokens.find_one({"user_id": user_id}, {"_id": 0})
    if not token_doc:
        raise HTTPException(status_code=400, detail="No Gmail tokens found")

    from services.gmail_service import get_gmail_credentials, build_gmail_service, download_attachment
    from routes.gmail import _process_gmail_cas_background, _persist_gmail_pdf
    import uuid as _uuid

    creds = get_gmail_credentials(token_doc)
    service = build_gmail_service(creds)
    content = download_attachment(service, message_id, attachment_id)

    task_id = f"admin_gmail_{_uuid.uuid4().hex[:12]}"
    await db.upload_tasks.insert_one({
        "task_id": task_id, "user_id": user_id,
        "status": "processing", "message": f"Importing {filename}...",
        "count": 0, "source": "email",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })

    file_id, file_path, file_sha256 = _persist_gmail_pdf(user_id, content, filename)

    import asyncio
    asyncio.create_task(_process_gmail_cas_background(
        content, user_id, task_id, "", password,
        message_id, attachment_id, file_id, filename,
    ))

    return {
        "ok": True,
        "task_id": task_id,
        "message": f"Import started for {filename}. Poll /api/portfolio/upload-status/{task_id} for result.",
    }
