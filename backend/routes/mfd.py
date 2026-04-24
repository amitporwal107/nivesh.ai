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
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from deps import db, get_current_user
from services import mfd_workspace, priority_engine

logger = logging.getLogger(__name__)
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
    the priority engine has something to chew on. Tolerant of missing data.

    Returns:
      - portfolio_score: unified Portfolio Health (0-100) from the same
        service the dashboard uses — so the MFD row matches what they'll
        see after impersonating.
      - risk_score: 0-100 from the Health.components["risk"] sub-score,
        inverted (the component is "risk health" where higher = safer;
        we flip so higher = riskier to stay consistent with the priority
        engine's convention).
      - portfolio_value_rs: live sum of (quantity × current_price) across
        holdings — the "AUM as of today".
      - ai_summary: one-line explain-why, built from the Health summary.
      - recommendations: active action plan rows.

    Results are cached in `mfd_profile_signal_cache` with a 15-minute TTL
    so the Advisor list loads in <1s even for 10+ clients (the uncached
    build_portfolio_health path is 10-15s per client).
    """
    from datetime import datetime, timezone, timedelta
    cache_ttl = timedelta(minutes=15)
    now = datetime.now(timezone.utc)
    cached = await db.mfd_profile_signal_cache.find_one({"user_id": user_id}, {"_id": 0})
    if cached:
        try:
            cached_at = datetime.fromisoformat(cached["cached_at"])
            if now - cached_at < cache_ttl:
                return {
                    "portfolio_score":     cached.get("portfolio_score"),
                    "risk_score":          cached.get("risk_score"),
                    "portfolio_value_rs":  cached.get("portfolio_value_rs") or 0.0,
                    "ai_summary":          cached.get("ai_summary"),
                    "recommendations":     cached.get("recommendations") or [],
                }
        except Exception:  # noqa: BLE001
            pass

    out: Dict[str, Any] = {
        "portfolio_score": None,
        "risk_score": None,
        "portfolio_value_rs": 0.0,
        "ai_summary": None,
        "recommendations": [],
    }

    # 1. Unified Portfolio Health (same service used by /insights/analysis).
    try:
        from services import portfolio_health as _ph
        hr = await _ph.build_portfolio_health(user_id)
        if hr and hr.health_score is not None:
            out["portfolio_score"] = float(hr.health_score)
            risk_comp = (hr.components or {}).get("risk")
            if risk_comp is not None:
                out["risk_score"] = max(0.0, min(100.0, 100.0 - float(risk_comp.score)))
            if hr.summary:
                out["ai_summary"] = hr.summary
    except Exception:  # noqa: BLE001
        logger.debug("build_portfolio_health failed for %s", user_id, exc_info=True)

    # 2. Live AUM — sum(quantity × current_price) across all holdings.
    try:
        pipeline = [
            {"$match": {"user_id": user_id}},
            {"$group": {
                "_id": None,
                "value": {"$sum": {"$multiply": [
                    {"$ifNull": ["$quantity", 0]},
                    {"$ifNull": ["$current_price", 0]},
                ]}},
                "count": {"$sum": 1},
            }},
        ]
        async for row in db.holdings.aggregate(pipeline):
            out["portfolio_value_rs"] = float(row.get("value") or 0.0)
    except Exception:  # noqa: BLE001
        pass

    # 3. Active action_plan entries → recommendations for priority engine.
    async for ap in db.action_plans.find(
        {"user_id": user_id, "status": {"$ne": "archived"}},
        {"_id": 0, "action": 1, "type": 1},
    ).limit(10):
        out["recommendations"].append(ap)

    # Persist to the cache collection — upsert so the TTL resets each call.
    await db.mfd_profile_signal_cache.update_one(
        {"user_id": user_id},
        {"$set": {**out, "user_id": user_id, "cached_at": now.isoformat()}},
        upsert=True,
    )
    return out


async def _profile_with_priority(prof: Dict[str, Any]) -> Dict[str, Any]:
    """Hydrate a profile dict with the computed priority result."""
    sig = await _latest_portfolio_signals(prof["shadow_user_id"])
    # Prefer the live portfolio value (holdings × live price) over the
    # manually-entered AUM field. The manual AUM is only a starting
    # estimate from MFD onboarding; once holdings exist they are truth.
    live_aum = sig.get("portfolio_value_rs") or 0.0
    effective_aum = live_aum if live_aum > 0 else prof.get("aum_rs")
    pr = priority_engine.compute_priority(
        portfolio_score=sig.get("portfolio_score"),
        risk_score=sig.get("risk_score"),
        aum_rs=effective_aum,
        last_reviewed_at=prof.get("last_reviewed_at"),
        recommendations=sig.get("recommendations"),
        client_name=prof.get("name"),
    )
    return {
        **prof,
        "portfolio_score": sig.get("portfolio_score"),
        "risk_score": sig.get("risk_score"),
        "portfolio_value_rs": live_aum if live_aum > 0 else None,
        "ai_summary": sig.get("ai_summary"),
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
    import asyncio
    user = await get_current_user(request)
    ws = await mfd_workspace.get_or_create_workspace(_session_user_id(user))
    profs = await mfd_workspace.list_profiles(
        ws["workspace_id"], include_self=include_self,
    )
    # Hydrate all profiles in parallel — each call runs build_portfolio_health
    # which is I/O-bound. Serial execution across 3-10 clients was the
    # primary cause of the "Loading client book…" stall observed on the
    # Advisor dashboard (Apr 2026).
    hydrated = list(await asyncio.gather(*(
        _profile_with_priority(p) for p in profs
    )))
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


# ── Advisor notes (freeform + structured SIP meta) ──────────────────────
class ClientNotesPayload(BaseModel):
    """Structured notes about an MFD client. Stored per profile, editable
    only by the workspace owner. SIP amount/due-date live here because
    neither is reliably parsable from CAS — advisors input them manually
    once, then we render it everywhere (snapshot · PDF report · priority
    rules once we wire SIP-gap detection)."""
    note: Optional[str] = Field(default=None, max_length=4000)
    sip_amount_rs: Optional[float] = Field(default=None, ge=0)
    sip_frequency: Optional[str] = None  # "monthly" | "quarterly" | etc.
    next_sip_due: Optional[str] = None   # ISO yyyy-mm-dd
    preferred_channel: Optional[str] = None  # "whatsapp" | "email" | "phone"


def _notes_doc_out(doc: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Strip Mongo internals and default empty fields."""
    if not doc:
        return {
            "note": None, "sip_amount_rs": None, "sip_frequency": None,
            "next_sip_due": None, "preferred_channel": None,
            "updated_at": None,
        }
    return {
        "note": doc.get("note"),
        "sip_amount_rs": doc.get("sip_amount_rs"),
        "sip_frequency": doc.get("sip_frequency"),
        "next_sip_due": doc.get("next_sip_due"),
        "preferred_channel": doc.get("preferred_channel"),
        "updated_at": doc.get("updated_at"),
    }


@router.get("/profiles/{profile_id}/notes")
async def get_client_notes(profile_id: str, request: Request):
    user = await get_current_user(request)
    await _owned_or_404(profile_id, _session_user_id(user))
    doc = await db.mfd_client_notes.find_one(
        {"profile_id": profile_id}, {"_id": 0},
    )
    return _notes_doc_out(doc)


@router.put("/profiles/{profile_id}/notes")
async def put_client_notes(
    profile_id: str, payload: ClientNotesPayload, request: Request,
):
    from datetime import datetime, timezone
    user = await get_current_user(request)
    await _owned_or_404(profile_id, _session_user_id(user))
    update = {
        **payload.model_dump(exclude_none=False),
        "profile_id": profile_id,
        "owner_user_id": _session_user_id(user),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.mfd_client_notes.update_one(
        {"profile_id": profile_id},
        {"$set": update},
        upsert=True,
    )
    doc = await db.mfd_client_notes.find_one({"profile_id": profile_id}, {"_id": 0})
    return _notes_doc_out(doc)


# ── Portfolio trend — derived, no schema change ─────────────────────────
@router.get("/profiles/{profile_id}/portfolio-trend")
async def portfolio_trend(profile_id: str, request: Request):
    """Invested ₹ vs Current ₹ (live prices) for a profile's shadow user.
    No real daily snapshot history exists yet, so we return the single
    cumulative delta. The frontend renders it as a summary strip with an
    optional "sparkline coming soon" placeholder."""
    user = await get_current_user(request)
    prof = await _owned_or_404(profile_id, _session_user_id(user))
    shadow = prof["shadow_user_id"]
    invested = 0.0
    current = 0.0
    recent_buys: List[Dict[str, Any]] = []
    cursor = db.holdings.find(
        {"user_id": shadow},
        {"_id": 0, "name": 1, "quantity": 1, "buy_price": 1, "current_price": 1,
         "buy_date": 1, "asset_type": 1},
    )
    async for h in cursor:
        qty = float(h.get("quantity") or 0)
        bp = float(h.get("buy_price") or 0)
        cp = float(h.get("current_price") or 0)
        invested += qty * bp
        current  += qty * cp
        bd = h.get("buy_date")
        if bd:
            recent_buys.append({
                "name": h.get("name"),
                "asset_type": h.get("asset_type"),
                "quantity": qty,
                "buy_price": bp,
                "current_price": cp,
                "value_rs": qty * cp,
                "buy_date": bd,
            })
    recent_buys.sort(key=lambda r: r["buy_date"] or "", reverse=True)
    delta = current - invested
    pct = (delta / invested * 100.0) if invested > 0 else None
    return {
        "invested_rs": round(invested, 2),
        "current_rs": round(current, 2),
        "absolute_change_rs": round(delta, 2),
        "percent_change": round(pct, 2) if pct is not None else None,
        "recent_buys": recent_buys[:5],
    }
