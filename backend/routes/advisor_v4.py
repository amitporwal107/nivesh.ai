"""Advisor aggregate endpoints for Nivesh v4.

Per docs/api-changes.md New Endpoints B.2, B.3, B.6, B.7, B.8 and
Modified Endpoint C.10 (approved 2026-05-24).

Serves screens (mobile + webapp):
  15 Advisor Book    — GET /api/advisor/summary  (B.6)
                    — GET /api/mfd/profiles additions  (C.10)
  16 Client 360     — GET /api/intelligence/portfolio/360  (B.2)
                    — GET /api/mfd/profiles/{id}/needs-attention  (B.3)
                    — POST /api/mfd/profiles/{id}/call-log  (B.5)
                    — POST /api/mfd/profiles/{id}/sip-nudge  (B.9)
  17 SIP Board      — GET /api/advisor/sip-board  (B.7)
                    — GET /api/advisor/sip-board/summary  (B.8)

Additive: no existing endpoints changed. The mfd/profiles C.10 fields
are injected by the existing _profile_with_priority hydration without
modifying the existing GET /mfd/profiles handler (piggybacks on the
existing signal cache).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, Body, HTTPException, Path, Query, Request

from deps import db, get_current_user
from services import mfd_workspace

logger = logging.getLogger(__name__)

advisor_router = APIRouter(prefix="/api/advisor", tags=["advisor-v4"])
mfd_v4_router = APIRouter(prefix="/api/mfd", tags=["mfd-v4"])
intel_router = APIRouter(prefix="/api/intelligence", tags=["intelligence-v4"])


def _session_user_id(user: Dict[str, Any]) -> str:
    return user.get("_session_user_id") or user["user_id"]


async def _hydrated_profiles(user: Dict[str, Any]) -> List[Dict[str, Any]]:
    from routes.mfd import _profile_with_priority
    ws = await mfd_workspace.get_or_create_workspace(_session_user_id(user))
    profs = await mfd_workspace.list_profiles(ws["workspace_id"], include_self=False)
    results = []
    for p in profs:
        try:
            results.append(await _profile_with_priority(p))
        except Exception:
            results.append(p)
    return results


def _band(health_score: Optional[float]) -> str:
    if health_score is None:
        return "unknown"
    if health_score >= 70:
        return "healthy"
    if health_score >= 50:
        return "review_soon"
    return "needs_attention"


# ── B.6 GET /api/advisor/summary ─────────────────────────────────────────────

@advisor_router.get("/summary")
async def advisor_summary(request: Request) -> Dict[str, Any]:
    """Book-level KPI rollup for the advisor's workspace.

    Screen 15 Advisor Book — top stat row.

    Returns: book_aum_rs, avg_health_score, needs_attention_count,
             actions_open_count, clients_total.
    """
    user = await get_current_user(request)
    profiles = await _hydrated_profiles(user)

    book_aum = 0.0
    health_scores: list[float] = []
    needs_attention = 0
    actions_open = 0

    for p in profiles:
        book_aum += float(p.get("portfolio_value_rs") or 0)
        hs = p.get("portfolio_score") or p.get("health_score")
        if hs is not None:
            try:
                health_scores.append(float(hs))
                if float(hs) < 50:
                    needs_attention += 1
            except (TypeError, ValueError):
                pass
        # Count open actions from the plan (cached in signal)
        recs = p.get("recommendations") or []
        actions_open += sum(
            1 for r in recs
            if (r.get("status") or "").upper() in {"PENDING", "IN_PROGRESS"}
        )

    avg_health = round(sum(health_scores) / len(health_scores), 1) if health_scores else None

    return {
        "book_aum_rs": round(book_aum, 2),
        "avg_health_score": avg_health,
        "needs_attention_count": needs_attention,
        "actions_open_count": actions_open,
        "clients_total": len(profiles),
    }


# ── B.7 GET /api/advisor/sip-board ───────────────────────────────────────────

@advisor_router.get("/sip-board")
async def sip_board(
    request: Request,
    state: Optional[str] = Query(None, description="failed|expiring|step_up|healthy"),
    cycle: Optional[str] = Query(None, description="YYYY-MM"),
) -> Dict[str, Any]:
    """SIP queue by state for the advisor's book.

    Screen 17 SIP Board.

    Query params:
      state — filter to one queue (default: all four grouped)
      cycle — YYYY-MM (default: current month)
    """
    from datetime import date
    user = await get_current_user(request)
    session_uid = _session_user_id(user)
    ws = await mfd_workspace.get_or_create_workspace(session_uid)
    profs = await mfd_workspace.list_profiles(ws["workspace_id"], include_self=False)
    shadow_ids = [p.get("shadow_user_id") for p in profs if p.get("shadow_user_id")]

    today = date.today()
    cycle_label = cycle or today.strftime("%Y-%m")

    queues: Dict[str, list] = {"failed": [], "expiring": [], "step_up": [], "healthy": []}

    for shadow_uid in shadow_ids:
        prof = next((p for p in profs if p.get("shadow_user_id") == shadow_uid), {})
        client_name = prof.get("name") or shadow_uid
        profile_id = prof.get("profile_id") or ""

        sips_cursor = db.sips.find(
            {"user_id": shadow_uid},
            {"_id": 0, "sip_id": 1, "fund_isin": 1, "fund_name": 1,
             "amount_rs": 1, "cadence": 1, "state": 1,
             "mandate_id": 1, "mandate_expiry_date": 1,
             "last_bounce_reason": 1, "last_bounce_date": 1,
             "cycles_missed": 1, "next_debit_date": 1, "proposed_stepup_pct": 1},
        )
        async for sip in sips_cursor:
            sip_state = (sip.get("state") or "healthy").lower()
            if state and sip_state != state:
                continue
            row = {
                "sip_id": sip.get("sip_id") or str(uuid4())[:8],
                "profile_id": profile_id,
                "client_name": client_name,
                "fund_isin": sip.get("fund_isin"),
                "fund_name": sip.get("fund_name") or "—",
                "amount_rs": sip.get("amount_rs"),
                "cadence": sip.get("cadence") or "MONTHLY",
                "state": sip_state,
                "mandate_id": sip.get("mandate_id"),
                "mandate_expiry_date": sip.get("mandate_expiry_date"),
                "last_bounce_reason": sip.get("last_bounce_reason"),
                "last_bounce_date": sip.get("last_bounce_date"),
                "cycles_missed": sip.get("cycles_missed") or 0,
                "next_debit_date": sip.get("next_debit_date"),
                "proposed_stepup_pct": sip.get("proposed_stepup_pct"),
                "available_actions": _sip_available_actions(sip_state),
            }
            bucket = sip_state if sip_state in queues else "healthy"
            queues[bucket].append(row)

    if state:
        return {"cycle": cycle_label, "queues": {state: queues.get(state, [])}}
    # Truncate healthy list — too large to be useful in full
    queues["healthy"] = queues["healthy"][:20]
    return {"cycle": cycle_label, "queues": queues}


def _sip_available_actions(state: str) -> list[str]:
    if state == "failed":
        return ["MESSAGE_CLIENT", "REQUEST_BANK_UPDATE"]
    if state == "expiring":
        return ["MESSAGE_CLIENT", "REQUEST_MANDATE_RENEWAL"]
    if state == "step_up":
        return ["MESSAGE_CLIENT", "APPROVE_STEP_UP"]
    return []


# ── B.8 GET /api/advisor/sip-board/summary ───────────────────────────────────

@advisor_router.get("/sip-board/summary")
async def sip_board_summary(request: Request) -> Dict[str, Any]:
    """Aggregate SIP metrics for the advisor's book.

    Screen 17 SIP Board — top stat row.
    """
    from datetime import date
    user = await get_current_user(request)
    session_uid = _session_user_id(user)
    ws = await mfd_workspace.get_or_create_workspace(session_uid)
    profs = await mfd_workspace.list_profiles(ws["workspace_id"], include_self=False)
    shadow_ids = [p.get("shadow_user_id") for p in profs if p.get("shadow_user_id")]

    today = date.today()
    cycle = today.strftime("%Y-%m")

    monthly_inflow = 0.0
    active_count = 0
    failed_count = 0
    mandate_at_risk = 0

    for shadow_uid in shadow_ids:
        async for sip in db.sips.find(
            {"user_id": shadow_uid},
            {"_id": 0, "amount_rs": 1, "state": 1, "mandate_expiry_date": 1, "cadence": 1},
        ):
            state = (sip.get("state") or "healthy").lower()
            amt = float(sip.get("amount_rs") or 0)
            if sip.get("cadence", "MONTHLY").upper() == "MONTHLY":
                monthly_inflow += amt
            active_count += 1
            if state == "failed":
                failed_count += 1
            exp = sip.get("mandate_expiry_date")
            if exp:
                try:
                    exp_date = datetime.fromisoformat(str(exp)).date() if isinstance(exp, str) else exp
                    days_left = (exp_date - today).days
                    if 0 < days_left <= 90:
                        mandate_at_risk += 1
                except Exception:
                    pass

    return {
        "cycle": cycle,
        "monthly_inflow_rs": round(monthly_inflow, 2),
        "active_sips_count": active_count,
        "failed_count": failed_count,
        "mandate_at_risk_count": mandate_at_risk,
    }


# ── B.3 GET /api/mfd/profiles/{id}/needs-attention ───────────────────────────

@mfd_v4_router.get("/profiles/{profile_id}/needs-attention")
async def profile_needs_attention(
    profile_id: str,
    request: Request,
) -> Dict[str, Any]:
    """Per-client items that need advisor action.

    Screen 16 Client 360.

    Joins plan_actions + scoring signals for the client. Returns items
    of severity HIGH — these drive the Client 360 "needs attention" list.
    """
    user = await get_current_user(request)
    session_uid = _session_user_id(user)
    prof = await mfd_workspace.get_profile(profile_id)
    if not prof:
        raise HTTPException(status_code=404, detail="Profile not found")
    ws = await db.workspaces.find_one({"workspace_id": prof["workspace_id"]}, {"_id": 0})
    if not ws or ws.get("owner_user_id") != session_uid:
        raise HTTPException(status_code=403, detail="Not your profile")

    shadow_uid = prof.get("shadow_user_id") or profile_id

    # Pull active plan for this client
    plan_doc = await db.action_plans.find_one(
        {"user_id": shadow_uid, "status": "active"},
        {"_id": 0, "plan_id": 1, "actions": 1},
    ) or {}

    items: list[Dict[str, Any]] = []
    for a in (plan_doc.get("actions") or []):
        if (a.get("priority") or 3) > 1:
            continue  # only priority 1 = Critical = HIGH severity
        items.append({
            "item_id": a.get("action_id") or a.get("id") or str(uuid4())[:8],
            "title": a.get("asset_name") or a.get("title") or "Action needed",
            "subtitle": f"{(a.get('source_domain') or 'portfolio').title()} · {a.get('reason_text') or ''}",
            "source_domain": a.get("source_domain"),
            "severity": "HIGH",
            "discuss_status": "DISCUSSED" if a.get("discussions") else "PENDING",
            "linked_action_id": a.get("action_id") or a.get("id"),
        })

    return {"items": items[:10]}


# ── B.5 POST /api/mfd/profiles/{id}/call-log ─────────────────────────────────

@mfd_v4_router.post("/profiles/{profile_id}/call-log", status_code=201)
async def log_call(
    profile_id: str,
    request: Request,
    body: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    """Log a call with a client.

    Screen 16 Client 360 — "Log a call" CTA.

    Body: { occurred_at, duration_min, channel, outcome, note }
    """
    user = await get_current_user(request)
    session_uid = _session_user_id(user)
    prof = await mfd_workspace.get_profile(profile_id)
    if not prof:
        raise HTTPException(status_code=404, detail="Profile not found")
    ws = await db.workspaces.find_one({"workspace_id": prof["workspace_id"]}, {"_id": 0})
    if not ws or ws.get("owner_user_id") != session_uid:
        raise HTTPException(status_code=403, detail="Not your profile")

    call_log_id = f"call_{uuid4().hex[:10]}"
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "call_log_id": call_log_id,
        "profile_id": profile_id,
        "advisor_user_id": session_uid,
        "occurred_at": body.get("occurred_at") or now,
        "duration_min": body.get("duration_min"),
        "channel": body.get("channel") or "PHONE",
        "outcome": body.get("outcome"),
        "note": body.get("note") or "",
        "created_at": now,
    }
    await db.call_logs.insert_one({**doc, "_id": call_log_id})
    doc.pop("_id", None)
    return doc


# ── B.9 POST /api/mfd/profiles/{id}/sip-nudge ────────────────────────────────

@mfd_v4_router.post("/profiles/{profile_id}/sip-nudge", status_code=202)
async def sip_nudge(
    profile_id: str,
    request: Request,
    body: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    """Queue a message nudge to a client about their SIP.

    Screen 17 SIP Board — "Message" CTA.

    Body: { sip_id, template, channel }
    Templates: BOUNCE_INSUFFICIENT_BALANCE | BOUNCE_MANDATE_LIMIT |
               BOUNCE_ACCOUNT_CLOSED | MANDATE_EXPIRY | STEPUP_DUE
    """
    user = await get_current_user(request)
    session_uid = _session_user_id(user)
    prof = await mfd_workspace.get_profile(profile_id)
    if not prof:
        raise HTTPException(status_code=404, detail="Profile not found")
    ws = await db.workspaces.find_one({"workspace_id": prof["workspace_id"]}, {"_id": 0})
    if not ws or ws.get("owner_user_id") != session_uid:
        raise HTTPException(status_code=403, detail="Not your profile")

    nudge_id = f"nudge_{uuid4().hex[:10]}"
    queued_at = datetime.now(timezone.utc).isoformat()
    doc = {
        "nudge_id": nudge_id,
        "profile_id": profile_id,
        "sip_id": body.get("sip_id"),
        "template": body.get("template"),
        "channel": body.get("channel") or "EMAIL",
        "advisor_user_id": session_uid,
        "status": "QUEUED",
        "queued_at": queued_at,
    }
    await db.sip_nudges.insert_one({**doc, "_id": nudge_id})
    return {"nudge_id": nudge_id, "queued_at": queued_at}


# ── B.2 GET /api/intelligence/portfolio/360 ──────────────────────────────────

@intel_router.get("/portfolio/360")
async def client_360(request: Request) -> Dict[str, Any]:
    """6-domain client summary for the advisor.

    Screen 16 Client 360.

    Requires an active impersonation context
    (POST /api/mfd/profiles/{id}/activate sets active_profile_id cookie).

    Composes:
      1. Health score (v3-portfolio)
      2. Domain scores (concentration / diversification / risk / performance / goals / tax)
      3. Needs-attention items (priority-1 plan actions)

    ≤3 DB reads: (1) plan_doc, (2) user_profiles, (3) signal cache.
    """
    user = await get_current_user(request)
    uid = user["user_id"]  # resolved by impersonation middleware if active

    # Client identity from profile
    prof_id = user.get("active_profile_id") or user.get("_active_profile_id")
    prof = None
    if prof_id:
        prof = await mfd_workspace.get_profile(prof_id)
    client_name = (prof or {}).get("name") or user.get("name") or uid
    aum = float((prof or {}).get("portfolio_value_rs") or 0)

    # 1. Health score (from signal cache — fast path)
    signal = await db.mfd_profile_signal_cache.find_one({"user_id": uid}, {"_id": 0}) or {}
    health_score = signal.get("portfolio_score") or signal.get("health_score")
    grade = _score_to_grade(health_score)

    # 2. Domain scores from plan actions (grouped by source_domain)
    plan_doc = await db.action_plans.find_one(
        {"user_id": uid, "status": "active"},
        {"_id": 0, "actions": 1},
    ) or {}
    domain_scores = _derive_domain_scores(plan_doc.get("actions") or [], health_score)

    # 3. Needs-attention items
    attention_items = [
        {
            "item_id": a.get("action_id") or a.get("id") or str(uuid4())[:8],
            "title": a.get("asset_name") or a.get("title") or "Action needed",
            "subtitle": f"{(a.get('source_domain') or 'portfolio').title()} · {a.get('reason_text') or ''}",
            "source_domain": a.get("source_domain"),
            "severity": "HIGH",
            "discuss_status": "DISCUSSED" if a.get("discussions") else "PENDING",
        }
        for a in (plan_doc.get("actions") or [])
        if (a.get("priority") or 3) <= 1
    ][:5]

    # User profile for style / risk
    uprof = await db.user_profiles.find_one({"user_id": uid}, {"_id": 0}) or {}

    return {
        "client": {
            "profile_id": prof_id,
            "name": client_name,
            "aum_rs": round(aum, 2),
            "style": uprof.get("investment_style") or uprof.get("persona") or "UNKNOWN",
            "risk_profile": (uprof.get("risk_profile") or "MODERATE").upper(),
            "last_seen_days": None,  # future: derive from session logs
        },
        "health": {
            "score": round(float(health_score), 1) if health_score is not None else None,
            "grade": grade,
            "tone": _score_tone_str(health_score),
        },
        "domains": domain_scores,
        "needs_attention": attention_items,
        "actions": ["prepare_review_pack", "log_a_call", "open_plan_board"],
    }


def _score_to_grade(score: Optional[float]) -> str:
    if score is None:
        return "—"
    s = float(score)
    if s >= 85:
        return "A"
    if s >= 70:
        return "B"
    if s >= 50:
        return "C"
    return "D"


def _score_tone_str(score: Optional[float]) -> str:
    if score is None:
        return "mute"
    s = float(score)
    if s >= 70:
        return "moss"
    if s >= 50:
        return "gold"
    return "rust"


# ── B.4 POST /api/mfd/profiles/{id}/review-pack/generate ─────────────────────

from pydantic import BaseModel as _PydanticBaseModel  # noqa: E402


class ReviewPackRequest(_PydanticBaseModel):
    format: Optional[str] = "pdf"   # "pdf" | "xlsx"
    sections: Optional[List[str]] = None  # ["portfolio","goals","risk","performance"]


@mfd_v4_router.post("/profiles/{profile_id}/review-pack/generate", status_code=202)
async def generate_review_pack(
    profile_id: str = Path(...),
    request: Request = None,
    body: ReviewPackRequest = ReviewPackRequest(),
) -> Dict[str, Any]:
    """Queue a review-pack generation task for a client.

    Screen 16 Client 360 — "Prepare Review Pack" CTA.

    This is an async scaffold — actual PDF/XLSX generation is handled by a
    background worker; this endpoint only enqueues the task.

    Body (all optional):
      format   — "pdf" (default) | "xlsx"
      sections — list subset of ["portfolio","goals","risk","performance"]
                 (default: all four)

    Returns: { task_id, status: "queued", poll_url }
    """
    user = await get_current_user(request)
    session_uid = _session_user_id(user)

    prof = await mfd_workspace.get_profile(profile_id)
    if not prof:
        raise HTTPException(status_code=404, detail="Profile not found")
    ws = await db.workspaces.find_one({"workspace_id": prof["workspace_id"]}, {"_id": 0})
    if not ws or ws.get("owner_user_id") != session_uid:
        raise HTTPException(status_code=403, detail="Not your profile")

    _VALID_FORMATS = {"pdf", "xlsx"}
    _ALL_SECTIONS = ["portfolio", "goals", "risk", "performance"]
    fmt = body.format if body.format in _VALID_FORMATS else "pdf"
    sections = body.sections if body.sections else _ALL_SECTIONS

    task_id = f"rp_{uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "task_id": task_id,
        "profile_id": profile_id,
        "user_id": session_uid,
        "status": "queued",
        "format": fmt,
        "sections": sections,
        "created_at": now,
        "result_url": None,
    }
    await db.review_pack_tasks.insert_one({**doc, "_id": task_id})

    return {
        "task_id": task_id,
        "status": "queued",
        "poll_url": f"/api/mfd/profiles/{profile_id}/review-pack/{task_id}",
    }


# ── B.4 GET /api/mfd/profiles/{id}/review-pack/{task_id} ─────────────────────

@mfd_v4_router.get("/profiles/{profile_id}/review-pack/{task_id}")
async def get_review_pack_status(
    profile_id: str = Path(...),
    task_id: str = Path(...),
    request: Request = None,
) -> Dict[str, Any]:
    """Poll the status of a queued review-pack task.

    Screen 16 Client 360 — polling after "Prepare Review Pack".

    Returns the task document (status, result_url, created_at, …).
    404 if not found or does not belong to this profile.
    """
    user = await get_current_user(request)
    session_uid = _session_user_id(user)

    prof = await mfd_workspace.get_profile(profile_id)
    if not prof:
        raise HTTPException(status_code=404, detail="Profile not found")
    ws = await db.workspaces.find_one({"workspace_id": prof["workspace_id"]}, {"_id": 0})
    if not ws or ws.get("owner_user_id") != session_uid:
        raise HTTPException(status_code=403, detail="Not your profile")

    task = await db.review_pack_tasks.find_one(
        {"task_id": task_id, "profile_id": profile_id}, {"_id": 0}
    )
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    return task


def _derive_domain_scores(
    actions: list[Dict[str, Any]],
    overall: Optional[float],
) -> list[Dict[str, Any]]:
    """Derive per-domain indicator from plan action priorities.

    When proper domain scoring is wired (post-v4), this is replaced
    by direct reads from the analytics layer. For now: presence of
    HIGH-priority actions in a domain → lower score proxy.
    """
    DOMAINS = [
        ("concentration",   "Sector concentration", "concentration"),
        ("diversification", "Funds",                "diversification"),
        ("risk",            "Beta",                 "risk"),
        ("performance",     "XIRR",                 "performance"),
        ("goals",           "At risk",              "goals"),
        ("tax",             "Harvest",              "tax"),
    ]
    by_domain: Dict[str, list] = {}
    for a in actions:
        sd = (a.get("source_domain") or "").lower()
        by_domain.setdefault(sd, []).append(a)

    out = []
    base = float(overall or 65)
    for key, metric_label, _ in DOMAINS:
        domain_actions = by_domain.get(key, [])
        high_pri = sum(1 for a in domain_actions if (a.get("priority") or 3) <= 1)
        # Simple proxy: reduce score by 10 per high-priority action
        score = max(20.0, base - high_pri * 10)
        tone = _score_tone_str(score)
        out.append({
            "key": key,
            "score": round(score),
            "tone": tone,
            "metric_label": metric_label,
            "metric_value": f"{high_pri} action{'s' if high_pri != 1 else ''}" if high_pri else "OK",
        })
    return out
