"""MFD Workspace & Profile layer — multi-client orchestration on top of the
existing retail engine (per the User → Workspace → Profile architecture).

Key idea:
    An MFD doesn't "become" a client. They create **client profiles**, each
    of which owns its own `shadow user_id`. When the MFD activates a profile,
    the session records `active_profile_id`; downstream auth resolution swaps
    in the profile's shadow user_id so the existing engine runs UNCHANGED
    against that profile's data.

Mongo collections (created on demand, no migration needed):
    - `workspaces`     : {workspace_id, owner_user_id, type, mode_selected_at}
    - `profiles`       : {profile_id, workspace_id, type, shadow_user_id,
                          name, aum_rs, tags, notes, last_reviewed_at, ...}
    - `users`          : shadow users created per CLIENT profile so the
                         existing engine (which keys on user_id) works as-is.
"""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from deps import db


WORKSPACE_INDIVIDUAL = "INDIVIDUAL"
WORKSPACE_ADVISORY = "ADVISORY"
PROFILE_SELF = "SELF"
PROFILE_CLIENT = "CLIENT"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Workspace ───────────────────────────────────────────────────────────
async def get_or_create_workspace(
    owner_user_id: str, *, default_type: str = WORKSPACE_INDIVIDUAL,
) -> Dict[str, Any]:
    """Every user has exactly one workspace (MVP: single-workspace model).
    If none exists we lazily create an INDIVIDUAL workspace and a SELF profile
    pointing at the user themselves. This keeps the retail flow backward-
    compatible: the engine continues to run against the user's own data."""
    ws = await db.workspaces.find_one({"owner_user_id": owner_user_id}, {"_id": 0})
    if ws:
        return ws

    ws = {
        "workspace_id": str(uuid.uuid4()),
        "owner_user_id": owner_user_id,
        "type": default_type,
        "created_at": _now_iso(),
        "mode_selected_at": None,
    }
    await db.workspaces.insert_one(ws)
    # Seed SELF profile so the retail engine keeps working unchanged.
    await _create_self_profile(ws["workspace_id"], owner_user_id)
    return {k: v for k, v in ws.items() if k != "_id"}


async def set_workspace_mode(owner_user_id: str, mode: str) -> Dict[str, Any]:
    """Switch between INDIVIDUAL and ADVISORY. Idempotent.

    When switching INTO ADVISORY for the first time, we also initialise
    `mfd_onboarding_completed=False` so the Dashboard knows to mount
    `MfdOnboardingWizard` (which strict-equals-checks the flag)."""
    if mode not in (WORKSPACE_INDIVIDUAL, WORKSPACE_ADVISORY):
        raise ValueError(f"Invalid workspace mode: {mode}")
    ws = await get_or_create_workspace(owner_user_id)
    if ws["type"] == mode:
        # Even on idempotent calls, ensure the wizard flag is set when
        # switching INTO ADVISORY (in case a legacy workspace exists).
        if mode == WORKSPACE_ADVISORY and "mfd_onboarding_completed" not in ws:
            await db.workspaces.update_one(
                {"workspace_id": ws["workspace_id"]},
                {"$set": {"mfd_onboarding_completed": False}},
            )
            ws["mfd_onboarding_completed"] = False
        return ws
    update: Dict[str, Any] = {"type": mode, "mode_selected_at": _now_iso()}
    if mode == WORKSPACE_ADVISORY and "mfd_onboarding_completed" not in ws:
        update["mfd_onboarding_completed"] = False
    await db.workspaces.update_one(
        {"workspace_id": ws["workspace_id"]}, {"$set": update},
    )
    ws["type"] = mode
    ws["mode_selected_at"] = update["mode_selected_at"]
    if "mfd_onboarding_completed" in update:
        ws["mfd_onboarding_completed"] = False
    return ws


async def update_workspace_meta(
    owner_user_id: str, *,
    firm_name: Optional[str] = None,
    client_count_range: Optional[str] = None,
    mfd_onboarding_completed: Optional[bool] = None,
    advisor_name: Optional[str] = None,
    advisor_mobile: Optional[str] = None,
    advisor_email: Optional[str] = None,
    arn_or_ria: Optional[str] = None,
) -> Dict[str, Any]:
    """Patch MFD-specific workspace fields captured during the onboarding
    wizard. All fields optional — unspecified keys are untouched.
    Advisor contact fields are required for the Client CAS invite flow
    (so the 'Notify Advisor on WhatsApp' CTA can deep-link)."""
    ws = await get_or_create_workspace(owner_user_id)
    updates: Dict[str, Any] = {}
    if firm_name is not None:
        updates["firm_name"] = firm_name.strip() or None
    if client_count_range is not None:
        updates["client_count_range"] = client_count_range
    if mfd_onboarding_completed is not None:
        updates["mfd_onboarding_completed"] = bool(mfd_onboarding_completed)
        if mfd_onboarding_completed:
            updates["mfd_onboarding_completed_at"] = _now_iso()
    if advisor_name is not None:
        updates["advisor_name"] = advisor_name.strip() or None
    if advisor_mobile is not None:
        digits = "".join(ch for ch in advisor_mobile if ch.isdigit())
        updates["advisor_mobile"] = digits or None
    if advisor_email is not None:
        updates["advisor_email"] = advisor_email.strip().lower() or None
    if arn_or_ria is not None:
        updates["arn_or_ria"] = arn_or_ria.strip().upper() or None
    if not updates:
        return ws
    await db.workspaces.update_one(
        {"workspace_id": ws["workspace_id"]}, {"$set": updates},
    )
    return {**ws, **updates}


# ── Profile ─────────────────────────────────────────────────────────────
async def _create_self_profile(workspace_id: str, user_id: str) -> Dict[str, Any]:
    """SELF profile points to the owner's real user_id — no shadow needed."""
    user = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    display_name = (user or {}).get("name") or (user or {}).get("email") or "My Portfolio"
    prof = {
        "profile_id": str(uuid.uuid4()),
        "workspace_id": workspace_id,
        "type": PROFILE_SELF,
        "shadow_user_id": user_id,     # SELF reuses the real user_id
        "name": display_name,
        "aum_rs": None,
        "tags": [],
        "notes": None,
        "last_reviewed_at": None,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    await db.profiles.insert_one(prof)
    return {k: v for k, v in prof.items() if k != "_id"}


async def create_client_profile(
    workspace_id: str, *, name: str, aum_rs: Optional[float] = None,
    tags: Optional[List[str]] = None, notes: Optional[str] = None,
    owner_user_id: Optional[str] = None,
    email: Optional[str] = None, mobile: Optional[str] = None,
) -> Dict[str, Any]:
    """Client profile gets its own **shadow user_id** so the existing
    engine (portfolio/insights/goals/V3) runs against it unchanged.

    We materialize a minimal user row so any code that joins on
    `users.user_id` (session lookups, audit, etc.) keeps working.

    `email` + `mobile` are stored both on the shadow user (so the
    invite flow can read them) and on the profile (so the MFD list
    surfaces them).
    """
    shadow_user_id = str(uuid.uuid4())
    clean_email = (email or "").strip().lower() or None
    clean_mobile = "".join(ch for ch in (mobile or "") if ch.isdigit()) or None
    shadow_user = {
        "user_id": shadow_user_id,
        "name": name,
        "email": clean_email,
        "mobile": clean_mobile,
        "is_shadow": True,              # flag so we never expose shadow users in auth flows
        "shadow_of_workspace": workspace_id,
        "shadow_owner_user_id": owner_user_id,
        "created_at": _now_iso(),
    }
    await db.users.insert_one(shadow_user)

    prof = {
        "profile_id": str(uuid.uuid4()),
        "workspace_id": workspace_id,
        "type": PROFILE_CLIENT,
        "shadow_user_id": shadow_user_id,
        "name": name,
        "aum_rs": aum_rs,
        "tags": tags or [],
        "notes": notes,
        "email": clean_email,
        "mobile": clean_mobile,
        "last_reviewed_at": None,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    await db.profiles.insert_one(prof)
    return {k: v for k, v in prof.items() if k != "_id"}


async def list_profiles(
    workspace_id: str, *, include_self: bool = True,
) -> List[Dict[str, Any]]:
    q = {"workspace_id": workspace_id}
    if not include_self:
        q["type"] = PROFILE_CLIENT
    cur = db.profiles.find(q, {"_id": 0}).sort("created_at", -1)
    return await cur.to_list(length=500)


async def get_profile(profile_id: str) -> Optional[Dict[str, Any]]:
    return await db.profiles.find_one({"profile_id": profile_id}, {"_id": 0})


async def update_profile(
    profile_id: str, *, name: Optional[str] = None, aum_rs: Optional[float] = None,
    tags: Optional[List[str]] = None, notes: Optional[str] = None,
    email: Optional[str] = None, mobile: Optional[str] = None,
    last_reviewed_at: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    updates: Dict[str, Any] = {"updated_at": _now_iso()}
    shadow_updates: Dict[str, Any] = {}
    if name is not None:
        updates["name"] = name
        shadow_updates["name"] = name
    if aum_rs is not None:
        updates["aum_rs"] = aum_rs
    if tags is not None:
        updates["tags"] = tags
    if notes is not None:
        updates["notes"] = notes
    if email is not None:
        clean_email = email.strip().lower() or None
        updates["email"] = clean_email
        shadow_updates["email"] = clean_email
    if mobile is not None:
        clean_mobile = "".join(ch for ch in mobile if ch.isdigit()) or None
        updates["mobile"] = clean_mobile
        shadow_updates["mobile"] = clean_mobile
    if last_reviewed_at is not None:
        updates["last_reviewed_at"] = last_reviewed_at
    await db.profiles.update_one({"profile_id": profile_id}, {"$set": updates})
    # Mirror contact updates to the shadow user doc so downstream code
    # (CAS invite flow, audit, etc.) sees consistent values.
    if shadow_updates:
        prof = await get_profile(profile_id)
        if prof and prof.get("shadow_user_id"):
            await db.users.update_one(
                {"user_id": prof["shadow_user_id"]}, {"$set": shadow_updates},
            )
    return await get_profile(profile_id)


async def delete_profile(profile_id: str) -> bool:
    """Hard-delete a client profile + its shadow user. SELF profiles cannot
    be deleted (they mirror the user's own account)."""
    prof = await get_profile(profile_id)
    if not prof or prof["type"] == PROFILE_SELF:
        return False
    shadow_uid = prof["shadow_user_id"]
    await db.profiles.delete_one({"profile_id": profile_id})
    await db.users.delete_one({"user_id": shadow_uid, "is_shadow": True})
    # Clear any sessions still impersonating this (now-deleted) profile so
    # the UI doesn't show a dangling "Viewing X" banner after delete.
    await db.user_sessions.update_many(
        {"active_profile_id": profile_id},
        {"$set": {"active_profile_id": None}},
    )
    # Best-effort: purge the shadow user's portfolio/holdings/goals too.
    for coll in ("portfolios", "holdings", "user_goals", "insights_cache"):
        try:
            await db[coll].delete_many({"user_id": shadow_uid})
        except Exception:  # noqa: BLE001
            pass
    return True


# ── Session impersonation (the magic bit) ───────────────────────────────
async def set_active_profile(session_token: str, profile_id: Optional[str]) -> None:
    """Record `active_profile_id` on the user's session. When downstream
    auth resolves `get_current_user`, we swap in the profile's shadow user_id
    so every engine route works against the client profile unchanged.
    Pass `profile_id=None` to clear (returns MFD to their own SELF profile).
    """
    await db.user_sessions.update_one(
        {"session_token": session_token},
        {"$set": {"active_profile_id": profile_id,
                  "active_profile_set_at": _now_iso()}},
    )


async def resolve_effective_user(session_doc: Dict[str, Any]) -> Optional[str]:
    """Given a session doc, return the user_id that the engine should act
    on. Defaults to the session owner; overridden by `active_profile_id`
    when set AND the profile is owned by this session's workspace."""
    raw_user_id = session_doc.get("user_id")
    active_profile_id = session_doc.get("active_profile_id")
    if not active_profile_id:
        return raw_user_id
    prof = await get_profile(active_profile_id)
    if not prof:
        return raw_user_id
    # Authorization: the profile must live in a workspace this user owns.
    ws = await db.workspaces.find_one(
        {"workspace_id": prof["workspace_id"]}, {"_id": 0},
    )
    if not ws or ws.get("owner_user_id") != raw_user_id:
        # Session was tampered with or workspace changed — fall back safely.
        return raw_user_id
    return prof["shadow_user_id"]
