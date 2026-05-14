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
    """
    admin = await require_admin(request)

    user = await db.users.find_one({"user_id": user_id}, {"_id": 0, "email": 1, "name": 1})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    deleted: Dict[str, int] = {}
    for col in _RESET_COLLECTIONS:
        try:
            res = await db[col].delete_many({"user_id": user_id})
            deleted[col] = res.deleted_count
        except Exception as e:  # noqa: BLE001
            logger.warning("reset_portfolio: skip %s for %s: %s", col, user_id, e)
            deleted[col] = 0

    # Reset onboarding flags on user_profiles
    now_iso = datetime.now(timezone.utc).isoformat()
    profile_update = {"$set": {**_RESET_PROFILE_FIELDS, "updated_at": now_iso}}
    profile_res = await db.user_profiles.update_one(
        {"user_id": user_id}, profile_update
    )

    # Clear the cas_view_state pin on the users doc so the dashboard
    # doesn't keep referencing a deleted snapshot.
    await db.users.update_one(
        {"user_id": user_id},
        {"$unset": {"cas_view_state": ""}},
    )

    # Best-effort Redis cache invalidation (snapshot scoring, V3 caches).
    redis_cleared = 0
    try:
        from services.redis_client import get_client as _get_redis
        rc = await _get_redis()
        if rc is not None:
            patterns = [
                f"snap:*:{user_id}",
                f"score:user:{user_id}*",
                f"v3:user:{user_id}*",
                f"actionplan:{user_id}*",
                f"copilot:{user_id}*",
            ]
            for pat in patterns:
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

    # Audit
    total_deleted = sum(deleted.values())
    audit_doc = {
        "kind": "admin.reset_portfolio",
        "actor_user_id": admin.get("user_id"),
        "actor_email": admin.get("email"),
        "target_user_id": user_id,
        "target_email": user.get("email"),
        "deleted_per_collection": deleted,
        "total_deleted": total_deleted,
        "profile_modified": profile_res.modified_count,
        "redis_keys_cleared": redis_cleared,
        "timestamp": now_iso,
    }
    try:
        await db.audit_log.insert_one(audit_doc)
    except Exception as e:  # noqa: BLE001
        logger.warning("audit log insert failed: %s", e)

    logger.info(
        f"admin[{admin.get('email')}] reset portfolio for user {user_id} "
        f"({user.get('email')}): {total_deleted} docs, {redis_cleared} redis keys"
    )

    return {
        "ok": True,
        "user_id": user_id,
        "user_email": user.get("email"),
        "deleted_per_collection": deleted,
        "total_deleted": total_deleted,
        "profile_reset": bool(profile_res.modified_count),
        "redis_keys_cleared": redis_cleared,
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
    """Show whether preview and production point at distinct Postgres /
    Redis / Mongo datastores. Returns a per-key SHA-256 fingerprint
    matrix (no full URLs leaked) and an explicit `collisions` list.

    The operator should ensure all three keys differ between the two
    environments. To fix a collision, set a distinct value for the key
    on the production-scoped secrets doc via the existing secret-edit
    flow (PATCH /api/admin/secrets ... env=production)."""
    await require_admin(request)
    from helpers import datastore_isolation as _di
    return await _di.audit_isolation(db)
