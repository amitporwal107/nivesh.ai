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
    # ── NEW: advisor identity fields captured in Firm step ───────────
    # These are REQUIRED for the Client CAS Invite flow so we can
    # populate the 'Notify Advisor on WhatsApp' CTA when a link
    # expires. Stored on the workspace doc (not the user doc) because
    # a single MFD could run multiple firms in future.
    advisor_name: Optional[str] = Field(None, max_length=120)
    advisor_mobile: Optional[str] = Field(None, max_length=20)
    advisor_email: Optional[str] = Field(None, max_length=255)
    arn_or_ria: Optional[str] = Field(None, max_length=50, description="ARN-xxxxx or INA-xxxxx")


class ProfileCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    aum_rs: Optional[float] = None
    tags: Optional[List[str]] = None
    notes: Optional[str] = None
    # ── NEW: mandatory-in-UI client contact (so the invite-CAS flow
    # can auto-fill WhatsApp + email share). Backend keeps them
    # optional to avoid breaking any callers that pre-create profiles
    # without contacts (e.g. CAS-first import flow).
    email: Optional[str] = Field(None, max_length=255)
    mobile: Optional[str] = Field(None, max_length=20)
    pan: Optional[str] = Field(None, max_length=10)


class ProfileUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=120)
    aum_rs: Optional[float] = None
    tags: Optional[List[str]] = None
    notes: Optional[str] = None
    email: Optional[str] = Field(None, max_length=255)
    mobile: Optional[str] = Field(None, max_length=20)
    pan: Optional[str] = Field(None, max_length=10)
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
    """Pull the latest portfolio signals for a given user_id so the priority
    engine has something to chew on.

    STALE-WHILE-REVALIDATE pattern:
    - If ANY cache exists (even expired) → return immediately (< 5ms).
    - If cache is older than TTL → schedule background refresh (no await).
    - If no cache at all → compute fast lightweight signals synchronously
      (AUM aggregation only, ~50ms), then schedule full AI refresh in background.

    This guarantees the Advisor Board always renders in < 500ms regardless of
    how many clients are in the workspace.
    """
    from datetime import datetime, timezone, timedelta
    import asyncio as _asyncio

    STALE_TTL = timedelta(hours=1)      # return fresh from cache if < 1h
    now = datetime.now(timezone.utc)
    cached = await db.mfd_profile_signal_cache.find_one({"user_id": user_id}, {"_id": 0})

    if cached:
        result = {
            "portfolio_score":     cached.get("portfolio_score"),
            "risk_score":          cached.get("risk_score"),
            "portfolio_value_rs":  cached.get("portfolio_value_rs") or 0.0,
            "ai_summary":          cached.get("ai_summary"),
            "recommendations":     cached.get("recommendations") or [],
        }
        # Background refresh only if stale — never blocks the response.
        try:
            cached_at = datetime.fromisoformat(cached["cached_at"])
            if now - cached_at >= STALE_TTL:
                _asyncio.ensure_future(_rebuild_signal_cache(user_id, now))
        except Exception:  # noqa: BLE001
            pass
        return result  # ← always fast

    # No cache at all: compute fast signals (no AI) and return immediately,
    # then let the background task populate the full cache for next load.
    out: Dict[str, Any] = await _fast_signals_no_ai(user_id)
    _asyncio.ensure_future(_rebuild_signal_cache(user_id, now))
    return out


async def _fast_signals_no_ai(user_id: str) -> Dict[str, Any]:
    """Lightweight signals computable in <100ms — no AI, no slow health engine."""
    out: Dict[str, Any] = {
        "portfolio_score": None,
        "risk_score": None,
        "portfolio_value_rs": 0.0,
        "ai_summary": None,
        "recommendations": [],
    }
    try:
        pipeline = [
            {"$match": {"user_id": user_id}},
            {"$group": {
                "_id": None,
                "value": {"$sum": {"$multiply": [
                    {"$ifNull": ["$quantity", 0]},
                    {"$ifNull": ["$current_price", 0]},
                ]}},
                "invested": {"$sum": {"$multiply": [
                    {"$ifNull": ["$quantity", 0]},
                    {"$ifNull": ["$buy_price", 0]},
                ]}},
                "count": {"$sum": 1},
            }},
        ]
        async for row in db.holdings.aggregate(pipeline):
            val = float(row.get("value") or 0.0)
            inv = float(row.get("invested") or 0.0)
            out["portfolio_value_rs"] = val
            if inv > 0:
                # Simple return-based proxy score: cap at 100
                ret_pct = (val - inv) / inv * 100.0
                out["portfolio_score"] = round(min(100.0, max(0.0, 50.0 + ret_pct)), 1)
    except Exception:  # noqa: BLE001
        pass

    async for ap in db.action_plans.find(
        {"user_id": user_id, "status": {"$ne": "archived"}},
        {"_id": 0, "action": 1, "type": 1},
    ).limit(10):
        out["recommendations"].append(ap)
    return out


async def _rebuild_signal_cache(user_id: str, ts) -> None:
    """Background task: full health build (with AI) → update cache."""
    try:
        out = await _fast_signals_no_ai(user_id)

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
            logger.debug("build_portfolio_health failed for %s in bg", user_id, exc_info=True)

        await db.mfd_profile_signal_cache.update_one(
            {"user_id": user_id},
            {"$set": {**out, "user_id": user_id, "cached_at": ts.isoformat()}},
            upsert=True,
        )
    except Exception:  # noqa: BLE001
        logger.debug("_rebuild_signal_cache failed for %s", user_id, exc_info=True)


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
        advisor_name=payload.advisor_name,
        advisor_mobile=payload.advisor_mobile,
        advisor_email=payload.advisor_email,
        arn_or_ria=payload.arn_or_ria,
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
    # Reject duplicates by email / mobile / PAN — surface the existing
    # record so the advisor can switch to it instead of creating a ghost.
    from services import identity_uniqueness as _iu
    chk = await _iu.check_identity_uniqueness(
        email=payload.email, mobile=payload.mobile, pan=payload.pan,
    )
    if not chk.ok:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "identity_conflict",
                "message": "A user / client with the same identifier already exists.",
                **chk.to_dict(),
            },
        )
    prof = await mfd_workspace.create_client_profile(
        ws["workspace_id"],
        name=payload.name, aum_rs=payload.aum_rs,
        tags=payload.tags, notes=payload.notes,
        email=payload.email, mobile=payload.mobile, pan=payload.pan,
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
    # Same uniqueness gate when an advisor edits a client's contact info.
    if any(k in updates for k in ("email", "mobile", "pan")):
        from services import identity_uniqueness as _iu
        chk = await _iu.check_identity_uniqueness(
            email=updates.get("email"),
            mobile=updates.get("mobile"),
            pan=updates.get("pan"),
            exclude_profile_id=profile_id,
        )
        if not chk.ok:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "identity_conflict",
                    "message": "Another user / client already uses one of these identifiers.",
                    **chk.to_dict(),
                },
            )
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


def _build_lot_coverage(
    *,
    n_lot_resolved: int,
    n_holding_only: int,
    n_cas_transactions: int,
    n_cas_symbols: int,
    n_undated: int,
) -> Dict[str, Any]:
    """Classify the source CAS quality + recommend a follow-up action.

    The advisor's mental model is "did the CAS the client uploaded carry
    transaction history, and for how many holdings?". We infer it from:
      • n_cas_transactions  — total tx rows persisted for this user
      • n_cas_symbols       — distinct ISINs/schemes with txn rows
      • n_lot_resolved      — holdings split into FIFO lots
      • n_holding_only      — fell back to holding.buy_date (or undated)
      • n_undated           — bucketed as 'undated' (no buy_date at all)

    Quality levels (drives the UI CTA):
      no_data            — zero CAS transactions in DB. Almost certainly a
                           demat-only NSDL/CDSL CAS or a CAMS/KFintech
                           summary statement (no transaction history).
      partial            — CAS has SOME transactions but most holdings are
                           still unmatched. Typically a short-window
                           detailed CAS (last 3-6 months) — older SIPs
                           are missing.
      good               — most holdings split into per-lot history.
    """
    n_holdings = n_lot_resolved + n_holding_only
    if n_cas_transactions == 0:
        quality = "no_data"
        action = "request_detailed_cas"
        message = ("CAS uploaded has no transaction history. Ask the client "
                   "for a CAMS + KFintech detailed statement covering "
                   "01-Apr-2010 → today to unlock SIP-level tax bucketing.")
    elif n_holdings > 0 and n_lot_resolved < 0.5 * n_holdings:
        quality = "partial"
        action = "request_detailed_cas"
        message = (f"Only {n_lot_resolved}/{n_holdings} holdings have lot-level "
                   f"history. The CAS likely covers a short window — request a "
                   f"detailed statement for 01-Apr-2010 → today.")
    elif n_undated > 0 and n_undated >= 0.3 * max(n_holdings, 1):
        quality = "partial"
        action = "manual_or_extend"
        message = (f"{n_undated} holdings still undated (likely direct equity / "
                   f"NSDL holdings). Add manual buy dates for those, or extend "
                   f"the CAS date range.")
    else:
        quality = "good"
        action = None
        message = "Lot-level coverage looks healthy."

    return {
        "n_holdings_lot_resolved": n_lot_resolved,
        "n_holdings_holding_only": n_holding_only,
        "n_cas_transactions":      n_cas_transactions,
        "n_cas_symbols":           n_cas_symbols,
        "n_undated":               n_undated,
        "data_source": (
            "cas_lots" if n_lot_resolved > 0 and n_lot_resolved >= n_holding_only
            else "mixed" if n_lot_resolved > 0
            else "holdings_only"
        ),
        "cas_quality": quality,             # no_data | partial | good
        "recommended_action": action,        # request_detailed_cas | manual_or_extend | None
        "hint": message,
    }


@router.get("/profiles/{profile_id}/tax-summary")
async def tax_summary(profile_id: str, request: Request):
    """Unrealized gain/loss scan + tax-harvesting opportunities.

    Implements the post-Jul-2024 / post-Apr-2023 Indian MF tax regime:

      • Equity (≥65% equity exposure): STCG <12m @ 20%, LTCG ≥12m @ 12.5%
        on gains beyond ₹1.25 L per FY (aggregated across all equity
        positions). No indexation.
      • Debt funds (post-Apr-2023 lots, "specified mutual funds"): ALL
        gains taxed at investor's slab rate (default 30% — UI overridable).
      • Hybrid funds: ≥65% equity → equity rules; <65% → debt rules.
        Equity exposure is read from holding metadata (`equity_exposure_pct`)
        when available; otherwise classified by `asset_type`.
      • Direct equities & ETFs (treated as equity for tax purposes).

    Returns harvest opportunities grouped into:
      • `harvest_picks` — LTCG positions to realize THIS FY to use the
        ₹1.25 L exemption (Rule 1).
      • `loss_picks` — losers to book to offset gains (Rule 4).
      • `near_lt_picks` — STCG positions within 30 days of crossing
        the 12-month threshold (Rule 10 — timing arbitrage).

    Cess + 4% surcharge is added on top of the indicative tax. STT and
    user slab rate are configurable via query params.
    """
    from datetime import datetime, timezone, timedelta
    user = await get_current_user(request)
    prof = await _owned_or_404(profile_id, _session_user_id(user))
    shadow = prof["shadow_user_id"]
    now = datetime.now(timezone.utc)

    # Tax constants — codified from the user-approved spec
    LTCG_EXEMPTION_INR = 125_000.0     # ₹1.25 L per FY
    EQUITY_STCG_RATE   = 0.20          # 20% (Sec 111A)
    EQUITY_LTCG_RATE   = 0.125         # 12.5% on gains > exemption (Sec 112A)
    DEBT_SLAB_RATE     = 0.30          # default; UI may override (POST tax-summary)
    CESS_PCT           = 0.04          # health & education cess on tax
    EQUITY_LT_DAYS     = 366
    DEBT_LT_DAYS       = 1096          # legacy 36-mo rule for pre-Apr-2023 lots
    DEBT_CUTOVER       = datetime(2023, 4, 1, tzinfo=timezone.utc)  # post: ALL gains @ slab

    total_invested = 0.0
    total_current  = 0.0
    eq_stcg = eq_ltcg = debt_stcg_slab = debt_ltcg = undated_gain = 0.0
    eq_stcg_n = eq_ltcg_n = debt_stcg_slab_n = debt_ltcg_n = undated_n = 0
    biggest: List[Dict[str, Any]] = []
    harvest_picks: List[Dict[str, Any]] = []
    loss_picks: List[Dict[str, Any]] = []
    near_lt_picks: List[Dict[str, Any]] = []
    n_lot_resolved = 0   # holdings split into multi-lot via CAS transactions
    n_holding_only  = 0  # holdings using their own buy_date (no CAS coverage)

    def _is_equity_taxed(asset: str, equity_pct: Optional[float]) -> bool:
        """Apply the 65% rule: ≥65% equity → equity tax bucket."""
        if equity_pct is not None:
            return equity_pct >= 65.0
        # Fallback by asset_type
        if asset in ("equity", "etf"):
            return True
        if asset == "mutual_fund":
            # Conservative: assume equity unless we know otherwise.
            # Fund-level enrichment can override via equity_exposure_pct.
            return True
        # gold, debt, hybrid_debt, fd, etc → debt tax bucket
        return False

    # ── Tier-2 lot-level coverage from cas_transactions ─────────────────
    # When a user has uploaded a CAS, each MF holding can be split into
    # the underlying SIP/purchase lots — each with its own buy_date and
    # buy_price. We use the FIFO matcher to derive these and bucket them
    # individually. Holdings without any CAS-transaction coverage fall
    # back to the single-lot holding.buy_date path below.
    #
    # Match keys are normalised (uppercase + whitespace-collapsed) on
    # BOTH sides because cas_transactions store ISIN as-extracted (mixed
    # case) while holdings.ticker is uppercased — without normalisation
    # we'd miss most matches.
    def _norm_isin(s: Any) -> Optional[str]:
        if not s:
            return None
        v = str(s).strip().upper()
        return v or None

    def _norm_name(s: Any) -> Optional[str]:
        if not s:
            return None
        v = " ".join(str(s).strip().upper().split())
        return v or None

    fifo_lots_by_isin: Dict[str, List[Any]] = {}
    fifo_lots_by_name: Dict[str, List[Any]] = {}
    fifo_n_tx = 0
    fifo_n_symbols = 0
    try:
        from services import tax_engine_fifo as _tef
        _state = await _tef.build_user_tax_state(shadow)
        fifo_n_tx = _state.n_transactions
        # Only use lot-level data when there's REAL CAS-transaction coverage
        # for at least one symbol. Otherwise FIFO is just the holding-level
        # data wrapped in a single seeded lot — no new info.
        if fifo_n_tx > 0:
            for sym, lots in _state.matcher.holdings.items():
                live = [l for l in lots if l.quantity > 1e-6 and l.buy_date]
                if not live:
                    continue
                fifo_n_symbols += 1
                # Index by ISIN-like key (uppercased)
                nk = _norm_isin(sym)
                if nk and nk.startswith("INF"):
                    fifo_lots_by_isin.setdefault(nk, live)
                # Index by scheme_name from the lots (any one carries it)
                for l in live:
                    nn = _norm_name(l.scheme_name)
                    if nn:
                        fifo_lots_by_name.setdefault(nn, live)
                        break
                # If `sym` itself is a scheme_name (no ISIN on the txn), index it by name too
                if nk and not nk.startswith("INF"):
                    nn2 = _norm_name(sym)
                    if nn2:
                        fifo_lots_by_name.setdefault(nn2, live)
    except Exception as e:  # noqa: BLE001
        logger.warning("FIFO tax-state build failed for %s: %s", shadow, e)

    def _resolve_lots(h: Dict[str, Any], qty: float, bp: float) -> List[Dict[str, Any]]:
        """Return per-lot {qty, buy_price, buy_dt, days_held} records.

        Match order: holding.isin → holding.ticker (often holds ISIN for MFs)
        → holding.name (scheme_name fallback). All keys normalised to
        uppercase / whitespace-collapsed before lookup. When FIFO lots
        cover within ±20% of the holding's current quantity, scale lot
        qty proportionally so headline totals stay consistent. Larger
        drift (CAS missing major buys/sells) → fall back to holding-
        level so we don't fabricate gains from stale CAS data.
        """
        matched = None
        # 1. ISIN-like keys
        for k in (h.get("isin"), h.get("ticker")):
            nk = _norm_isin(k)
            if nk and nk in fifo_lots_by_isin:
                matched = fifo_lots_by_isin[nk]
                break
        # 2. Scheme-name fallback (handles CAS txns without ISIN)
        if not matched:
            nn = _norm_name(h.get("name"))
            if nn and nn in fifo_lots_by_name:
                matched = fifo_lots_by_name[nn]

        if matched and qty > 0:
            sum_lots_qty = sum(l.quantity for l in matched)
            if sum_lots_qty > 0:
                drift = abs(sum_lots_qty - qty) / qty
                if drift <= 0.20:
                    # FIFO lot quantities ≈ holding quantity → trust FIFO.
                    # Scale to exactly match holding.qty so per-bucket sums
                    # reconcile with the headline total_invested.
                    scale = qty / sum_lots_qty
                    out = []
                    for l in matched:
                        bd = l.buy_date if l.buy_date.tzinfo else l.buy_date.replace(tzinfo=timezone.utc)
                        out.append({
                            "qty":       l.quantity * scale,
                            "buy_price": float(l.buy_price),
                            "buy_dt":    bd,
                            "days_held": (now - bd).days,
                            "source":    "cas_lot",
                        })
                    return out
                # else: drift > 20% — likely partial coverage; fall through

        # Holding-level fallback
        bd_raw = h.get("buy_date")
        bd = None
        days_held = None
        if bd_raw:
            try:
                bd = datetime.fromisoformat(str(bd_raw).replace("Z", "+00:00"))
                if bd.tzinfo is None:
                    bd = bd.replace(tzinfo=timezone.utc)
                days_held = (now - bd).days
            except Exception:  # noqa: BLE001
                pass
        return [{"qty": qty, "buy_price": bp, "buy_dt": bd,
                 "days_held": days_held, "source": "holding"}]

    async for h in db.holdings.find(
        {"user_id": shadow},
        {"_id": 0, "name": 1, "asset_type": 1, "ticker": 1, "isin": 1,
         "quantity": 1, "buy_price": 1, "current_price": 1, "buy_date": 1,
         "equity_exposure_pct": 1, "sector": 1},
    ):
        qty = float(h.get("quantity") or 0)
        bp  = float(h.get("buy_price") or 0)
        cp  = float(h.get("current_price") or 0)
        if qty <= 0 or cp <= 0:
            continue

        asset = (h.get("asset_type") or "").lower()
        eq_pct = h.get("equity_exposure_pct")
        is_equity = _is_equity_taxed(asset, eq_pct)
        lt_days = EQUITY_LT_DAYS if is_equity else DEBT_LT_DAYS

        # Display name — for SGBs the parser sometimes leaves the issuer
        # ("GOVERNMENT") in `name`; resolve the actual series from ISIN so
        # every downstream list (biggest, harvest, loss, near-LT) can tell
        # tranches apart.
        display_name = h.get("name")
        if asset == "gold":
            from services.sgb_prices import resolve_sgb_display_name
            display_name = resolve_sgb_display_name(display_name, h.get("ticker"))

        lot_records = _resolve_lots(h, qty, bp)
        # Skip holdings whose only data point is a placeholder cost basis
        # AND no CAS lots — nothing meaningful to bucket.
        if all(l["buy_price"] <= 0 for l in lot_records):
            continue

        used_cas = any(l["source"] == "cas_lot" for l in lot_records)
        if used_cas:
            n_lot_resolved += 1
        else:
            n_holding_only += 1

        for lot in lot_records:
            lot_qty       = lot["qty"]
            lot_bp        = lot["buy_price"]
            lot_bd        = lot["buy_dt"]
            lot_days_held = lot["days_held"]
            if lot_qty <= 0 or lot_bp < 0:
                continue

            lot_invested = lot_qty * lot_bp
            lot_current  = lot_qty * cp
            lot_gain     = lot_current - lot_invested
            total_invested += lot_invested
            total_current  += lot_current

            bucket = None
            if lot_days_held is None:
                undated_gain += lot_gain; undated_n += 1; bucket = "undated"
            elif is_equity:
                if lot_days_held >= lt_days:
                    eq_ltcg += lot_gain; eq_ltcg_n += 1; bucket = "equity_ltcg"
                else:
                    eq_stcg += lot_gain; eq_stcg_n += 1; bucket = "equity_stcg"
            else:
                # Debt / specified MF: post-Apr-2023 ALL gains at slab.
                # For lots bought BEFORE the cutover, legacy LTCG @12.5%
                # applies only when held > 36 months (no indexation).
                if lot_bd and lot_bd < DEBT_CUTOVER and lot_days_held >= DEBT_LT_DAYS:
                    debt_ltcg += lot_gain; debt_ltcg_n += 1; bucket = "debt_ltcg_legacy"
                else:
                    debt_stcg_slab += lot_gain; debt_stcg_slab_n += 1; bucket = "debt_slab"

            lot_tag = (f" · {lot_bd.date().isoformat()} lot"
                       if lot["source"] == "cas_lot" and lot_bd else "")

            # ── Harvest opportunity scoring (per-lot) ─────────────────
            # Rule 1: equity LTCG winners → realize up to ₹1.25 L this FY
            if bucket == "equity_ltcg" and lot_gain > 0:
                harvest_picks.append({
                    "name": display_name, "asset_type": asset,
                    "ticker": h.get("ticker"), "gain": round(lot_gain, 2),
                    "days_held": lot_days_held,
                    "lot_buy_date": lot_bd.date().isoformat() if lot_bd else None,
                    "lot_source": lot["source"],
                    "rationale": f"Equity LTCG{lot_tag} · use ₹1.25L exemption",
                })

            # Rule 4: book losers (any asset) — offset against any gains
            if lot_gain < 0 and abs(lot_gain) >= 1000:
                loss_picks.append({
                    "name": display_name, "asset_type": asset,
                    "ticker": h.get("ticker"), "gain": round(lot_gain, 2),
                    "days_held": lot_days_held,
                    "bucket": bucket,
                    "lot_buy_date": lot_bd.date().isoformat() if lot_bd else None,
                    "lot_source": lot["source"],
                    "rationale": f"Book loss{lot_tag} · offset against STCG/LTCG",
                })

            # Rule 10: timing arb — equity STCG within 30 days of LT cutover
            if bucket == "equity_stcg" and lot_gain > 0 and lot_days_held is not None:
                days_to_lt = EQUITY_LT_DAYS - lot_days_held
                if 0 < days_to_lt <= 30:
                    # Tax saving = (20% - 12.5%) × gain (ignoring exemption)
                    near_lt_picks.append({
                        "name": display_name, "asset_type": asset,
                        "gain": round(lot_gain, 2),
                        "days_held": lot_days_held,
                        "days_to_lt": days_to_lt,
                        "lot_buy_date": lot_bd.date().isoformat() if lot_bd else None,
                        "lot_source": lot["source"],
                        "tax_saving_if_wait": round(lot_gain * (EQUITY_STCG_RATE - EQUITY_LTCG_RATE), 2),
                        "rationale": f"Wait {days_to_lt}d{lot_tag} → save 7.5% tax",
                    })

            if abs(lot_gain) >= 10000:
                biggest.append({
                    "name": display_name, "asset_type": asset,
                    "gain": round(lot_gain, 2), "bucket": bucket,
                    "days_held": lot_days_held,
                    "lot_buy_date": lot_bd.date().isoformat() if lot_bd else None,
                    "lot_source": lot["source"],
                })

    biggest.sort(key=lambda x: x["gain"], reverse=True)
    harvest_picks.sort(key=lambda x: x["gain"], reverse=True)
    loss_picks.sort(key=lambda x: x["gain"])  # most negative first
    near_lt_picks.sort(key=lambda x: x["days_to_lt"])

    # ── Tax computation (post-Jul-2024 / post-Apr-2023 regime) ──────────
    # Equity LTCG: apply ₹1.25 L exemption ONCE, aggregated.
    eq_ltcg_taxable = max(0.0, eq_ltcg - LTCG_EXEMPTION_INR)
    exemption_used  = min(max(0.0, eq_ltcg), LTCG_EXEMPTION_INR)
    exemption_left  = max(0.0, LTCG_EXEMPTION_INR - exemption_used)

    tax_eq_stcg   = max(0.0, eq_stcg)         * EQUITY_STCG_RATE
    tax_eq_ltcg   = eq_ltcg_taxable           * EQUITY_LTCG_RATE
    tax_debt_slab = max(0.0, debt_stcg_slab)  * DEBT_SLAB_RATE
    tax_debt_ltcg = max(0.0, debt_ltcg)       * EQUITY_LTCG_RATE  # legacy 12.5%

    base_tax = tax_eq_stcg + tax_eq_ltcg + tax_debt_slab + tax_debt_ltcg
    cess     = base_tax * CESS_PCT
    est_tax_if_realized = base_tax + cess

    total_unrealized = total_current - total_invested

    return {
        # ── Totals ──
        "total_invested_rs":   round(total_invested, 2),
        "total_current_rs":    round(total_current, 2),
        "total_unrealized_rs": round(total_unrealized, 2),
        # ── Per-bucket gains ──
        "equity_stcg_rs":     round(eq_stcg, 2),
        "equity_ltcg_rs":     round(eq_ltcg, 2),
        "debt_slab_rs":       round(debt_stcg_slab, 2),
        "debt_ltcg_rs":       round(debt_ltcg, 2),
        "undated_gain_rs":    round(undated_gain, 2),
        "equity_stcg_count":  eq_stcg_n,
        "equity_ltcg_count":  eq_ltcg_n,
        "debt_slab_count":    debt_stcg_slab_n,
        "debt_ltcg_count":    debt_ltcg_n,
        "undated_count":      undated_n,
        # Backward-compat keys (existing UI bindings)
        "stcg_rs":     round(eq_stcg + debt_stcg_slab, 2),
        "ltcg_rs":     round(eq_ltcg + debt_ltcg, 2),
        "stcg_count":  eq_stcg_n + debt_stcg_slab_n,
        "ltcg_count":  eq_ltcg_n + debt_ltcg_n,
        # ── Tax breakdown (post-Jul-2024) ──
        "tax_breakdown": {
            "equity_stcg": round(tax_eq_stcg, 2),
            "equity_ltcg": round(tax_eq_ltcg, 2),
            "debt_slab":   round(tax_debt_slab, 2),
            "debt_ltcg_legacy": round(tax_debt_ltcg, 2),
            "cess_4pct":   round(cess, 2),
        },
        "ltcg_exemption_inr":      LTCG_EXEMPTION_INR,
        "ltcg_exemption_used":     round(exemption_used, 2),
        "ltcg_exemption_remaining": round(exemption_left, 2),
        "est_tax_if_realized_rs":  round(est_tax_if_realized, 2),
        "user_slab_rate":          DEBT_SLAB_RATE,
        # ── Tax-harvesting opportunities (the user's 10 rules, scored) ──
        "harvest_picks":   harvest_picks[:10],   # Rule 1
        "loss_picks":      loss_picks[:10],      # Rule 4
        "near_lt_picks":   near_lt_picks[:10],   # Rule 10
        "biggest_positions": biggest[:5],
        "coverage_pct": round(
            100.0 * (eq_stcg_n + eq_ltcg_n + debt_stcg_slab_n + debt_ltcg_n) /
            max(1, eq_stcg_n + eq_ltcg_n + debt_stcg_slab_n + debt_ltcg_n + undated_n),
            1,
        ),
        # ── Lot-level coverage (Tier-2 from cas_transactions) ──
        "lot_coverage": _build_lot_coverage(
            n_lot_resolved=n_lot_resolved,
            n_holding_only=n_holding_only,
            n_cas_transactions=fifo_n_tx,
            n_cas_symbols=fifo_n_symbols,
            n_undated=undated_n,
        ),
        # ── Tax regime metadata for UI footnote ──
        "regime": {
            "label":        "Indian MF Tax · post-Jul-2024 / post-Apr-2023",
            "equity_stcg":  "20% (no indexation)",
            "equity_ltcg":  "12.5% on gains > ₹1.25 L / FY",
            "debt_post_apr_2023": "Slab rate (no LTCG benefit)",
            "switch_warning": "Switching = sale + buy. Holding period resets, tax payable now.",
            "stt_note":     "STT applies on equity-fund redemptions.",
            "elss_note":    "ELSS deduction available only in old tax regime.",
            "lot_basis":    (
                "Lot-level holding periods from CAS transactions (per SIP installment)"
                if n_lot_resolved > 0
                else "Holding-level avg cost basis (no CAS-transaction coverage)"
            ),
        },
    }


# ── Portfolio trend — derived, no schema change ─────────────────────────
@router.get("/profiles/{profile_id}/portfolio-trend")
async def portfolio_trend(profile_id: str, request: Request):
    """Invested ₹ vs Current ₹ (live prices) for a profile's shadow user.
    Also returns recent purchases: first from holdings with buy_date, then
    from CAS transaction history, then from snapshot-delta (new holdings
    that appeared between the last two CAS snapshots).
    """
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
                "source": "holdings",
            })
    recent_buys.sort(key=lambda r: r["buy_date"] or "", reverse=True)

    # ── Fallback 1: CAS transaction history (if buy_date was not in holdings)
    if not recent_buys:
        async for t in db.cas_transactions.find(
            {"user_id": shadow, "type": {"$in": ["PURCHASE", "SIP_PURCHASE"]}},
            {"_id": 0, "scheme_name": 1, "date": 1, "amount": 1, "units": 1, "amc": 1, "type": 1},
        ).sort("date", -1).limit(10):
            recent_buys.append({
                "name": t.get("scheme_name") or t.get("name"),
                "asset_type": "Mutual Fund",
                "quantity": t.get("units"),
                "buy_price": None,
                "current_price": None,
                "value_rs": t.get("amount"),
                "buy_date": t.get("date"),
                "source": "cas_transaction",
            })

    # ── Fallback 2: Snapshot delta — new ISINs in latest vs previous snapshot
    if not recent_buys:
        snaps = await db.portfolio_snapshots.find(
            {"user_id": shadow},
            {"_id": 0, "snapshot_date": 1, "holdings": 1},
        ).sort("snapshot_date", -1).limit(2).to_list(2)
        if len(snaps) == 2:
            latest_isins = {h.get("isin") or h.get("ticker"): h for h in (snaps[0].get("holdings") or [])}
            prev_isins = {h.get("isin") or h.get("ticker") for h in (snaps[1].get("holdings") or [])}
            new_holdings = [
                h for k, h in latest_isins.items()
                if k and k not in prev_isins
            ][:10]
            for h in new_holdings:
                qty = float(h.get("quantity") or 0)
                cp = float(h.get("current_price") or h.get("buy_price") or 0)
                recent_buys.append({
                    "name": h.get("name"),
                    "asset_type": h.get("asset_type") or "Mutual Fund",
                    "quantity": qty,
                    "buy_price": h.get("buy_price"),
                    "current_price": cp,
                    "value_rs": qty * cp,
                    "buy_date": snaps[0]["snapshot_date"],
                    "source": "snapshot_delta",
                })

    delta = current - invested
    pct = (delta / invested * 100.0) if invested > 0 else None
    return {
        "invested_rs": round(invested, 2),
        "current_rs": round(current, 2),
        "absolute_change_rs": round(delta, 2),
        "percent_change": round(pct, 2) if pct is not None else None,
        "recent_buys": recent_buys[:10],
    }
