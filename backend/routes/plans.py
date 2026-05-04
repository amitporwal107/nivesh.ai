"""Action Plan API Routes — REST endpoints for V2 action plan system."""
from fastapi import APIRouter, Request, HTTPException
from typing import Optional
from pydantic import BaseModel
import logging

from deps import get_current_user, db
from services import (
    action_plan_manager,
    portfolio_intelligence,
    signal_detector,
)

router = APIRouter(prefix="/api")
plan_manager = action_plan_manager.get_plan_manager()
logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════
# REQUEST/RESPONSE MODELS
# ══════════════════════════════════════════════════════════════════════════

class ActionStatusUpdate(BaseModel):
    """Request body for updating action status."""
    status: str  # "PENDING" | "IN_PROGRESS" | "COMPLETED" | "SKIPPED"
    completion_note: Optional[str] = None


class ActionFeedback(BaseModel):
    """Request body for action feedback."""
    useful: bool  # True = 👍, False = 👎
    comment: Optional[str] = None


# ══════════════════════════════════════════════════════════════════════════
# PLAN GENERATION
# ══════════════════════════════════════════════════════════════════════════

@router.post("/plans/generate")
async def generate_plan(request: Request):
    """Generate a new action plan.
    
    Flow:
    1. Fetch portfolio data
    2. Run portfolio intelligence
    3. Generate signals
    4. Calculate scores
    5. Create plan (status="preview")
    6. Return plan for user review
    
    Returns:
        {
            "plan": {...},
            "message": "Plan generated successfully"
        }
    """
    user = await get_current_user(request)
    user_id = user["user_id"]
    
    # Fetch portfolio data
    holdings = await db.holdings.find({"user_id": user_id}, {"_id": 0}).to_list(500)
    
    if not holdings:
        raise HTTPException(status_code=400, detail="No holdings found. Upload your portfolio first.")
    
    # Run portfolio intelligence
    intelligence = await portfolio_intelligence.compute_portfolio_intelligence(user_id)
    
    # Generate plan using ActionPlanManager
    plan = await plan_manager.generate_plan(user_id, intelligence, holdings)
    
    # Save as preview
    await plan_manager.create_plan(plan)
    
    return {
        "plan": plan,
        "message": "Plan generated successfully. Review and save to activate."
    }


# ══════════════════════════════════════════════════════════════════════════
# PLAN CRUD
# ══════════════════════════════════════════════════════════════════════════

@router.post("/plans/{plan_id}/save")
async def save_plan(plan_id: str, request: Request):
    """Save a preview plan as active.
    
    Changes status from "preview" to "active"
    """
    user = await get_current_user(request)
    user_id = user["user_id"]
    
    try:
        plan = await plan_manager.save_plan(plan_id, user_id)
        return {
            "plan": plan,
            "message": "Plan saved successfully"
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/plans/active")
async def get_active_plan(request: Request):
    """Get user's active plan.
    
    Also runs auto-archive for old completed plans.
    
    Returns:
        {
            "plan": {...} | null,
            "has_plan": true | false
        }
    """
    user = await get_current_user(request)
    user_id = user["user_id"]
    
    # Auto-archive old completed plans (runs in background)
    try:
        await plan_manager.auto_archive_old_completed_plans(user_id)
    except Exception as e:
        # Don't fail the request if auto-archive fails
        logger.warning(f"Auto-archive failed: {e}")
    
    plan = await plan_manager.get_active_plan(user_id)
    
    return {
        "plan": plan,
        "has_plan": plan is not None
    }


@router.delete("/plans/active")
async def clear_active_plan(request: Request):
    """Archive the current active plan.

    Used by the trash button in the Plan Board UI when the user wants
    to discard the current recommendations and start over (e.g. after
    significant portfolio changes, or when the suggestions feel stale).
    A completely fresh plan can then be generated via POST /plans/generate.

    Returns the archived plan's id + status so the UI can confirm.
    Idempotent — calling on a user with no active plan returns ok=False.
    """
    user = await get_current_user(request)
    user_id = user["user_id"]

    plan = await plan_manager.get_active_plan(user_id)
    if not plan:
        return {"ok": False, "reason": "no_active_plan",
                "message": "No active plan to clear."}
    archived = await plan_manager.archive_plan(
        plan["plan_id"], user_id, reason="cleared_by_user",
    )
    if not archived:
        return {"ok": False, "reason": "archive_failed",
                "plan_id": plan["plan_id"]}
    return {
        "ok": True,
        "plan_id": plan["plan_id"],
        "version": plan.get("version"),
        "message": "Active plan cleared. Generate a new plan to get fresh recommendations.",
    }


@router.get("/plans/active/health-projection")
async def get_active_plan_health_projection(request: Request):
    """Return current + projected Portfolio Health if pending actions are
    implemented.

    Response shape: see `services.portfolio_health_projection.project_health`.
    """
    user = await get_current_user(request)
    try:
        from services import portfolio_health_projection as _phproj
        result = await _phproj.project_health(user["user_id"])
    except Exception as e:  # noqa: BLE001
        logger.warning(f"health projection failed: {e}")
        return {"available": False, "reason": str(e)}
    if result is None:
        return {"available": False, "reason": "No active plan or no holdings."}
    return {"available": True, **result}


@router.get("/plans/history")
async def get_plan_history(
    request: Request,
    limit: int = 10,
    skip: int = 0,
):
    """Get user's plan history."""
    user = await get_current_user(request)
    user_id = user["user_id"]
    
    plans = await plan_manager.get_plan_history(user_id, limit, skip)
    
    return {
        "plans": plans,
        "count": len(plans)
    }


@router.get("/plans/{plan_id}")
async def get_plan(plan_id: str, request: Request):
    """Get specific plan by ID."""
    user = await get_current_user(request)
    user_id = user["user_id"]
    
    plan = await plan_manager.get_plan(plan_id, user_id)
    
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    
    return {"plan": plan}


# ══════════════════════════════════════════════════════════════════════════
# ACTION STATUS MANAGEMENT
# ══════════════════════════════════════════════════════════════════════════

@router.patch("/plans/{plan_id}/actions/{action_id}")
async def update_action_status(
    plan_id: str,
    action_id: str,
    body: ActionStatusUpdate,
    request: Request,
):
    """Update action status.
    
    Body:
        {
            "status": "PENDING" | "IN_PROGRESS" | "COMPLETED" | "SKIPPED",
            "completion_note": "Redeemed via Groww app" (optional)
        }
    
    Returns:
        Updated plan with new progress
    """
    user = await get_current_user(request)
    user_id = user["user_id"]
    
    try:
        updated_plan = await plan_manager.update_action_status(
            plan_id=plan_id,
            action_id=action_id,
            user_id=user_id,
            new_status=body.status,
            completion_note=body.completion_note,
        )
        
        return {
            "plan": updated_plan,
            "message": f"Action {action_id} marked as {body.status}"
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.patch("/plans/{plan_id}/actions/{action_id}/feedback")
async def submit_action_feedback(
    plan_id: str,
    action_id: str,
    body: ActionFeedback,
    request: Request,
):
    """Submit feedback for an action.
    
    Body:
        {
            "useful": true | false,
            "comment": "Optional feedback text"
        }
    
    Returns:
        Updated plan with feedback recorded
    """
    user = await get_current_user(request)
    user_id = user["user_id"]
    
    try:
        updated_plan = await plan_manager.update_action_feedback(
            plan_id=plan_id,
            action_id=action_id,
            user_id=user_id,
            useful=body.useful,
            comment=body.comment,
        )
        
        return {
            "plan": updated_plan,
            "message": "Feedback recorded successfully"
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ══════════════════════════════════════════════════════════════════════════
# PLAN REFRESH
# ══════════════════════════════════════════════════════════════════════════

@router.post("/plans/refresh")
async def refresh_plan(request: Request):
    """Refresh active plan (generate new version).
    
    Flow:
    1. Archive current active plan
    2. Generate new plan with incremented version
    3. Save as active
    
    Use when:
    - Portfolio has changed significantly
    - User wants updated recommendations
    """
    user = await get_current_user(request)
    user_id = user["user_id"]
    
    # Fetch latest portfolio data
    holdings = await db.holdings.find({"user_id": user_id}, {"_id": 0}).to_list(500)
    
    if not holdings:
        raise HTTPException(status_code=400, detail="No holdings found")
    
    # Run portfolio intelligence (fetched but not returned - used by plan_manager internally)
    await portfolio_intelligence.compute_portfolio_intelligence(user_id)
    
    # Refresh plan
    new_plan = await plan_manager.refresh_plan(user_id)
    
    return {
        "plan": new_plan,
        "message": f"Plan refreshed to version {new_plan['version']}"
    }


# ══════════════════════════════════════════════════════════════════════════
# SIGNALS (for UI)
# ══════════════════════════════════════════════════════════════════════════

@router.get("/signals/generate")
async def generate_signals(request: Request):
    """Generate portfolio signals without creating a full plan.
    
    Useful for showing signals in collapsible widget.
    
    Returns:
        {
            "signals": [...],
            "summary": {...}
        }
    """
    user = await get_current_user(request)
    user_id = user["user_id"]
    
    # Fetch portfolio data
    holdings = await db.holdings.find({"user_id": user_id}, {"_id": 0}).to_list(500)
    
    if not holdings:
        return {
            "signals": [],
            "summary": {
                "total_signals": 0,
                "high_severity": 0,
                "medium_severity": 0,
                "low_severity": 0,
            }
        }
    
    # Run portfolio intelligence
    intelligence = await portfolio_intelligence.compute_portfolio_intelligence(user_id)
    
    # Generate signals
    portfolio_data = {
        "portfolio_intelligence": intelligence,
        "holdings": holdings,
        "total_value": sum(h["quantity"] * h["current_price"] for h in holdings),
    }
    
    signals = signal_detector.generate_signals(portfolio_data)
    summary = signal_detector.get_signal_summary(signals)
    
    return {
        "signals": signals,
        "summary": summary
    }


# ══════════════════════════════════════════════════════════════════════════
# PLAN SIMULATION (Future)
# ══════════════════════════════════════════════════════════════════════════

@router.post("/plans/{plan_id}/simulate")
async def simulate_plan(plan_id: str, request: Request):
    """Simulate plan impact (before/after comparison).
    
    For MVP: Placeholder
    In production: Show portfolio metrics before/after executing plan
    """
    user = await get_current_user(request)
    user_id = user["user_id"]
    
    plan = await plan_manager.get_plan(plan_id, user_id)
    
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    
    # For MVP: Return basic simulation
    return {
        "simulation": {
            "before": {
                "total_value": plan["metadata"]["portfolio_value_at_creation"],
                "overlap_score": 30.4,  # Placeholder
                "concentration_risk": "HIGH",
            },
            "after": {
                "total_value": plan["metadata"]["portfolio_value_at_creation"] - plan["freed_capital"] + plan["post_tax_proceeds"],
                "overlap_score": 45.0,  # Improved
                "concentration_risk": "MEDIUM",
            },
            "improvements": [
                "Overlap reduced by 15 points",
                "Concentration risk lowered",
                "Tax-efficient exits",
            ]
        },
        "message": "Simulation complete"
    }



@router.post("/plans/refresh-fundamentals")
async def refresh_fundamentals(request: Request):
    """Refresh fundamental data cache for all user's stock holdings.
    
    This endpoint:
    1. Fetches latest fundamental data from Groww for all stocks
    2. Caches data in Redis (24h expiry)
    3. Returns count of successfully updated stocks
    
    Should be called:
    - Once daily (can be automated)
    - Before generating a new plan
    - On user request
    """
    from services.groww_fundamentals import refresh_cache_for_user
    
    user = await get_current_user(request)
    user_id = user["user_id"]
    
    try:
        fundamentals_map = await refresh_cache_for_user(user_id)
        
        return {
            "success": True,
            "stocks_updated": len(fundamentals_map),
            "updated_stocks": list(fundamentals_map.keys()),
            "message": f"Successfully refreshed fundamental data for {len(fundamentals_map)} stocks"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
