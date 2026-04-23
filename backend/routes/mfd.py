"""MFD routes — multi-client orchestration on top of the retail engine.

Endpoints:

    GET    /api/mfd/workspace                  current workspace + mode
    PATCH  /api/mfd/workspace                  switch INDIVIDUAL ↔ ADVISORY
    GET    /api/mfd/profiles                   list profiles (with priority)
    POST   /api/mfd/profiles                   create a client profile
    GET    /api/mfd/profiles/{id}              profile detail + priority
    PATCH  /api/mfd/profiles/{id}              update name/aum/tags/notes
    DELETE /api/mfd/profiles/{id}              delete a client profile
    POST   /api/mfd/profiles/{id}/activate     impersonate this profile
    POST   /api/mfd/profiles/deactivate        back to the MFD's own view

Critical invariant: every non-trivial mutation requires that the target
profile lives in a workspace owned by the session user. See `_owned_or_404`.
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from deps import db, get_current_user
from services import mfd_workspace, priority_engine

router = APIRouter(prefix="/api/mfd", tags=["mfd"])


# ── Schemas ─────────────────────────────────────────────────────────────
class WorkspaceModeUpdate(BaseModel):
    mode: Optional[str] = Field(None, description="INDIVIDUAL | ADVISORY")
    firm_name: Optional[str] = Field(None, max_length=120)
    client_count_range: Optional[str] = Field(None, description="<100 | 100-500 | 500+")
    mfd_onboarding_completed: Optional[bool] = None


class ProfileCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    aum_rs: Optional[float] = None
    tags: Optional[List[str]] = None
    notes: Optional[str] = None


class ProfileUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=120)
    aum_rs: Optional[float] = None
    tags: Optional[List[str]] = None
    notes: Optional[str] = None
    last_reviewed_at: Optional[str] = None   # ISO string


# ── Internals ───────────────────────────────────────────────────────────
def _session_user_id(user: Dict[str, Any]) -> str:
    """Real (logged-in) user_id. Note: `get_current_user` may have already
    impersonated a profile and returned the shadow user_doc, but we stashed
    `_session_user_id` for exactly this purpose."""
    return user.get("_session_user_id") or user["user_id"]


async def _owned_or_404(profile_id: str, session_user_id: str) -> Dict[str, Any]:
    prof = await mfd_workspace.get_profile(profile_id)
    if not prof:
        raise HTTPException(status_code=404, detail="Profile not found")
    ws = await db.workspaces.find_one(
        {"workspace_id": prof["workspace_id"]}, {"_id": 0},
    )
    if not ws or ws.get("owner_user_id") != session_user_id:
        raise HTTPException(status_code=403, detail="Profile not in your workspace")
    return prof


async def _latest_portfolio_signals(user_id: str) -> Dict[str, Any]:
    """Pull the latest V3 snapshot + recommendations for a given user_id so
    the priority engine has something to chew on. Tolerant of missing data."""
    out: Dict[str, Any] = {
        "portfolio_score": None,
        "risk_score": None,
        "recommendations": [],
    }
    # Portfolio score / risk score — cached by the insights layer.
    cached = await db.insights_cache.find_one(
        {"user_id": user_id}, {"_id": 0},
        sort=[("created_at", -1)],
    )
    if cached:
        out["portfolio_score"] = (
            cached.get("portfolio_score")
            or cached.get("health_score")
            or cached.get("quality_score")
        )
        out["risk_score"] = cached.get("risk_score")
        out["recommendations"] = cached.get("recommendations") or []
    # Also surface any recent action_plan entries as 'recommendations' so
    # severity isn't always missing before the insights cache is populated.
    if not out["recommendations"]:
        async for ap in db.action_plans.find(
            {"user_id": user_id, "status": {"$ne": "archived"}},
            {"_id": 0, "action": 1, "type": 1},
        ).limit(10):
            out["recommendations"].append(ap)
    return out


async def _profile_with_priority(prof: Dict[str, Any]) -> Dict[str, Any]:
    """Hydrate a profile dict with the computed priority result."""
    sig = await _latest_portfolio_signals(prof["shadow_user_id"])
    pr = priority_engine.compute_priority(
        portfolio_score=sig.get("portfolio_score"),
        risk_score=sig.get("risk_score"),
        aum_rs=prof.get("aum_rs"),
        last_reviewed_at=prof.get("last_reviewed_at"),
        recommendations=sig.get("recommendations"),
        client_name=prof.get("name"),
    )
    return {
        **prof,
        "portfolio_score": sig.get("portfolio_score"),
        "risk_score": sig.get("risk_score"),
        "recommendation_count": len(sig.get("recommendations") or []),
        "priority": pr.to_dict(),
    }


# ── Workspace endpoints ─────────────────────────────────────────────────
@router.get("/workspace")
async def get_workspace(request: Request):
    user = await get_current_user(request)
    ws = await mfd_workspace.get_or_create_workspace(_session_user_id(user))
    return ws


@router.patch("/workspace")
async def update_workspace_mode(payload: WorkspaceModeUpdate, request: Request):
    user = await get_current_user(request)
    owner_uid = _session_user_id(user)
    # Mode flip (INDIVIDUAL ↔ ADVISORY) and meta patch can be combined in a
    # single PATCH so the onboarding wizard only needs one round-trip.
    if payload.mode is not None:
        try:
            await mfd_workspace.set_workspace_mode(owner_uid, payload.mode)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    ws = await mfd_workspace.update_workspace_meta(
        owner_uid,
        firm_name=payload.firm_name,
        client_count_range=payload.client_count_range,
        mfd_onboarding_completed=payload.mfd_onboarding_completed,
    )
    return ws


# ── Profile listing ─────────────────────────────────────────────────────
@router.get("/profiles")
async def list_profiles(request: Request, include_self: bool = True):
    """Returns every profile in the user's workspace, each with a live
    priority score so the UI can sort/filter client-side."""
    user = await get_current_user(request)
    ws = await mfd_workspace.get_or_create_workspace(_session_user_id(user))
    profs = await mfd_workspace.list_profiles(
        ws["workspace_id"], include_self=include_self,
    )
    hydrated: List[Dict[str, Any]] = []
    for p in profs:
        hydrated.append(await _profile_with_priority(p))
    # Sort by priority score DESC so HIGH clients surface first.
    hydrated.sort(key=lambda x: x["priority"]["score"], reverse=True)
    return {"workspace": ws, "profiles": hydrated, "count": len(hydrated)}


# ── Profile CRUD ────────────────────────────────────────────────────────
@router.post("/profiles")
async def create_profile(payload: ProfileCreate, request: Request):
    user = await get_current_user(request)
    owner_uid = _session_user_id(user)
    ws = await mfd_workspace.get_or_create_workspace(owner_uid)
    # Creating a client implicitly upgrades the workspace to ADVISORY.
    if ws["type"] != mfd_workspace.WORKSPACE_ADVISORY:
        ws = await mfd_workspace.set_workspace_mode(
            owner_uid, mfd_workspace.WORKSPACE_ADVISORY,
        )
    prof = await mfd_workspace.create_client_profile(
        ws["workspace_id"],
        name=payload.name, aum_rs=payload.aum_rs,
        tags=payload.tags, notes=payload.notes,
        owner_user_id=owner_uid,
    )
    return await _profile_with_priority(prof)


@router.get("/profiles/{profile_id}")
async def get_profile(profile_id: str, request: Request):
    user = await get_current_user(request)
    prof = await _owned_or_404(profile_id, _session_user_id(user))
    return await _profile_with_priority(prof)


@router.patch("/profiles/{profile_id}")
async def update_profile(profile_id: str, payload: ProfileUpdate, request: Request):
    user = await get_current_user(request)
    await _owned_or_404(profile_id, _session_user_id(user))
    updates = payload.model_dump(exclude_none=True)
    prof = await mfd_workspace.update_profile(profile_id, **updates)
    return await _profile_with_priority(prof)


@router.delete("/profiles/{profile_id}")
async def delete_profile(profile_id: str, request: Request):
    user = await get_current_user(request)
    prof = await _owned_or_404(profile_id, _session_user_id(user))
    if prof["type"] == mfd_workspace.PROFILE_SELF:
        raise HTTPException(status_code=400, detail="Cannot delete the SELF profile")
    ok = await mfd_workspace.delete_profile(profile_id)
    if not ok:
        raise HTTPException(status_code=500, detail="Delete failed")
    return {"status": "ok", "profile_id": profile_id}


# ── Activation / deactivation (session-scoped impersonation) ────────────
@router.post("/profiles/{profile_id}/activate")
async def activate_profile(profile_id: str, request: Request):
    user = await get_current_user(request)
    await _owned_or_404(profile_id, _session_user_id(user))
    token = request.cookies.get("session_token")
    if not token:
        raise HTTPException(status_code=401, detail="No session token")
    await mfd_workspace.set_active_profile(token, profile_id)
    return {"status": "ok", "active_profile_id": profile_id}


@router.post("/profiles/deactivate")
async def deactivate_profile(request: Request):
    """Clear `active_profile_id` on the session — returns the MFD to their
    own SELF profile view. Useful for "Back to client list"."""
    await get_current_user(request)
    token = request.cookies.get("session_token")
    if not token:
        raise HTTPException(status_code=401, detail="No session token")
    await mfd_workspace.set_active_profile(token, None)
    return {"status": "ok", "active_profile_id": None}
