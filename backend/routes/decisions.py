"""Decision Engine API routes — Portfolio recommendations."""
from fastapi import APIRouter, Request, HTTPException
from typing import Optional

from deps import get_current_user
from services import decision_engine

router = APIRouter(prefix="/api")


@router.get("/decisions/recommendations")
async def get_portfolio_recommendations(request: Request):
    """Get top 3 actionable portfolio recommendations.
    
    Returns EXIT and ADD suggestions based on decision engine scoring.
    """
    user = await get_current_user(request)
    result = await decision_engine.generate_portfolio_actions(user["user_id"])
    return result


@router.get("/decisions/exit-analysis")
async def get_exit_analysis(request: Request):
    """Get detailed EXIT analysis for all holdings."""
    user = await get_current_user(request)
    
    # TODO: Return detailed exit scores for all holdings
    return {"message": "Exit analysis endpoint - TBD"}


@router.get("/decisions/tax-impact")
async def get_tax_impact(request: Request):
    """Get tax impact analysis for portfolio."""
    user = await get_current_user(request)
    
    from deps import db
    from services import tax_calculator
    
    holdings = await db.holdings.find({"user_id": user["user_id"]}, {"_id": 0}).to_list(500)
    
    if not holdings:
        return {"error": "No holdings found"}
    
    # Calculate tax optimization suggestions
    optimization = tax_calculator.optimize_exit_timing(holdings)
    
    return {
        "exit_now_count": len(optimization["exit_now"]),
        "defer_to_ltcg_count": len(optimization["defer_to_ltcg"]),
        "loss_harvest_count": len(optimization["loss_harvest"]),
        "optimization": optimization,
    }
