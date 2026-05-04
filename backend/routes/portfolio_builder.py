"""Portfolio Builder + Risk Profile Chat + Simulation + Export — one router.

All four pieces of the empty-state advisor flow:

  POST /api/portfolio-builder/generate              ← AI Portfolio Builder
  POST /api/portfolio-builder/simulate              ← What-if scenarios
  GET  /api/portfolio-builder/export.pdf            ← PDF export
  POST /api/portfolio-builder/whatsapp-share        ← WhatsApp deeplink

  POST /api/risk-profile/start                       ← begin chat
  POST /api/risk-profile/{session_id}/answer         ← submit answer

The Builder endpoints reuse `services/portfolio_builder.build_proposed_portfolio`.
The Simulation endpoint wraps `services/goal_engine.scenario_matrix` for
what-if drawdown/return shocks. Risk Profile chat hits `risk_profile_chat`.
PDF/WA wrap `portfolio_builder_export`.
"""
from __future__ import annotations
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from deps import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["portfolio-builder"])


# ─────────────────────────────────────────────────────────────────────────
# AI Portfolio Builder
# ─────────────────────────────────────────────────────────────────────────
class BuilderRequest(BaseModel):
    monthly_sip_rs: Optional[float] = Field(None, ge=0)
    lumpsum_rs: Optional[float] = Field(None, ge=0)


@router.post("/portfolio-builder/generate")
async def generate_portfolio(payload: BuilderRequest, request: Request):
    """Generate a proposed portfolio for the current user.

    Reads risk profile + active goals from the user's profile, runs
    target_allocator + goal_fund_picker, returns full builder payload.
    """
    user = await get_current_user(request)
    from services import portfolio_builder as _pb
    return await _pb.build_proposed_portfolio(
        user["user_id"],
        monthly_sip_rs=payload.monthly_sip_rs,
        lumpsum_rs=payload.lumpsum_rs,
    )


# ─────────────────────────────────────────────────────────────────────────
# Simulation overlay — what-if return / drawdown scenarios
# ─────────────────────────────────────────────────────────────────────────
class SimulateBuilderRequest(BaseModel):
    starting_corpus_rs: float = Field(0, ge=0)
    monthly_sip_rs: float = Field(0, ge=0)
    years: float = Field(..., gt=0, le=50)
    future_target_rs: float = Field(0, ge=0)
    # Allocation can be passed in directly (advisor tweaked it), else we
    # call target_allocator for the user.
    allocation: Optional[Dict[str, float]] = None


@router.post("/portfolio-builder/simulate")
async def simulate_builder_portfolio(payload: SimulateBuilderRequest, request: Request):
    """Run the 4-scenario matrix (base / bull / bear / stress) on the
    proposed portfolio.

    Returns:
        {
          "scenarios": {base: {return_pct, corpus_rs, success_pct}, ...},
          "monte_carlo": {p10, p50, p90, success_pct},
          "allocation_used": {...},
          "blended_return_pct": 11.4,
          "blended_vol_pct": 14.2
        }
    """
    user = await get_current_user(request)
    from services import goal_engine as _ge
    from services.target_allocator import compute_target_allocation

    if payload.allocation:
        allocation = {k: float(v) for k, v in payload.allocation.items()}
    else:
        ta = await compute_target_allocation(user["user_id"])
        allocation = ta.allocation or {}
    if not allocation:
        raise HTTPException(400, "No allocation available — set a risk profile first")

    blended = _ge.blend_return_vol(allocation)
    scenarios = _ge.scenario_matrix(
        starting_corpus_rs=payload.starting_corpus_rs,
        monthly_sip_rs=payload.monthly_sip_rs,
        years=payload.years,
        allocation=allocation,
        future_target_rs=payload.future_target_rs,
    )
    # Monte-Carlo is more expensive; cap runs and let users opt out via
    # ?fast=true if needed. For MVP we always run a small 500-path sim.
    try:
        mc = _ge.monte_carlo_success(
            starting_corpus_rs=payload.starting_corpus_rs,
            monthly_sip_rs=payload.monthly_sip_rs,
            years=payload.years,
            allocation=allocation,
            future_target_rs=payload.future_target_rs,
            n_runs=500,
        )
    except Exception as e:  # noqa: BLE001
        logger.debug("monte_carlo failed: %s", e)
        mc = None

    return {
        "allocation_used": allocation,
        "blended_return_pct": blended.get("annual_return_pct"),
        "blended_vol_pct": blended.get("annual_vol_pct"),
        "scenarios": scenarios,
        "monte_carlo": mc,
        "inputs": payload.dict(),
    }


# ─────────────────────────────────────────────────────────────────────────
# Export — PDF + WhatsApp
# ─────────────────────────────────────────────────────────────────────────
@router.post("/portfolio-builder/export.pdf")
async def export_portfolio_pdf(payload: BuilderRequest, request: Request):
    """Generate the proposed portfolio AND render it as a PDF in one call.

    Single round-trip from the frontend's "Download PDF" button — the
    frontend doesn't need to ship the builder payload separately.
    """
    user = await get_current_user(request)
    from services import portfolio_builder as _pb
    from services import portfolio_builder_export as _ex

    proposal = await _pb.build_proposed_portfolio(
        user["user_id"],
        monthly_sip_rs=payload.monthly_sip_rs,
        lumpsum_rs=payload.lumpsum_rs,
    )
    client_name = (user.get("name") or "Client").split("@")[0]
    pdf_bytes = _ex.render_portfolio_pdf(proposal, client_name=client_name)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="portfolio_proposal_{client_name}.pdf"',
        },
    )


class WhatsAppShareRequest(BaseModel):
    monthly_sip_rs: Optional[float] = Field(None, ge=0)
    lumpsum_rs: Optional[float] = Field(None, ge=0)
    client_name: Optional[str] = Field(None, max_length=80)
    public_url: Optional[str] = Field(None, max_length=500)


@router.post("/portfolio-builder/whatsapp-share")
async def whatsapp_share(payload: WhatsAppShareRequest, request: Request):
    """Generate the proposal + return a wa.me deeplink with a pre-filled
    message. Frontend opens the deeplink; user's WhatsApp picks contact."""
    user = await get_current_user(request)
    from services import portfolio_builder as _pb
    from services import portfolio_builder_export as _ex

    proposal = await _pb.build_proposed_portfolio(
        user["user_id"],
        monthly_sip_rs=payload.monthly_sip_rs,
        lumpsum_rs=payload.lumpsum_rs,
    )
    client_name = payload.client_name or (user.get("name") or "Client").split("@")[0]
    out = _ex.build_whatsapp_message(
        proposal, client_name=client_name, public_url=payload.public_url,
    )
    return out


# ─────────────────────────────────────────────────────────────────────────
# Conversational risk profile chat
# ─────────────────────────────────────────────────────────────────────────
@router.post("/risk-profile/start")
async def risk_profile_start(request: Request):
    """Begin a new risk-profile chat session. Returns first question."""
    user = await get_current_user(request)
    from services import risk_profile_chat as _rpc
    return _rpc.start_session(user["user_id"])


class RiskProfileAnswer(BaseModel):
    question_id: str
    value: str


@router.post("/risk-profile/{session_id}/answer")
async def risk_profile_answer(session_id: str, payload: RiskProfileAnswer, request: Request):
    """Submit one answer. Returns next question, or final result + persists
    the profile to user_profiles when complete."""
    user = await get_current_user(request)
    from services import risk_profile_chat as _rpc
    out = _rpc.submit_answer(session_id, payload.question_id, payload.value)
    if out.get("error"):
        raise HTTPException(400, detail=out)
    if out.get("complete"):
        # Fire-and-forget persist — don't block the response on the write.
        try:
            await _rpc.persist_profile(user["user_id"], out)
        except Exception as e:  # noqa: BLE001
            logger.warning("risk_profile persist failed: %s", e)
    return out
