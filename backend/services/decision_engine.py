"""Decision Engine — EXIT and ADD scoring for portfolio optimization.

Uses InstrumentScoringEngine for all scoring operations.
Generates actionable recommendations based on scores and signals.
"""
from typing import Dict, Any, List, Optional
import logging

from services import tax_calculator, portfolio_intelligence, instrument_scoring
from deps import db

logger = logging.getLogger(__name__)

# Get scoring engine instance
scoring_engine = instrument_scoring.get_scoring_engine()

# Use InstrumentScoringEngine for all scoring (imported above)
# Scoring logic centralized in services/instrument_scoring.py


# ══════════════════════════════════════════════════════════════════════════
# MF EXIT SCORE (uses InstrumentScoringEngine)
# ══════════════════════════════════════════════════════════════════════════

async def calculate_mf_exit_score(
    mf_investment: Dict[str, Any],
    portfolio_intelligence_data: Dict[str, Any],
    holding: Dict[str, Any],
) -> Dict[str, Any]:
    """Calculate EXIT score for a mutual fund using InstrumentScoringEngine."""
    # Calculate tax impact
    tax_result = tax_calculator.calculate_tax_impact(holding)
    
    # Use scoring engine
    score_result = scoring_engine.score_mf_exit(
        mf_investment=mf_investment,
        portfolio_intelligence=portfolio_intelligence_data,
        tax_result=tax_result,
    )
    
    # Add additional context
    score_result["mf_investment"] = mf_investment
    score_result["holding"] = holding
    score_result["tax_impact"] = tax_result
    
    return score_result


# ══════════════════════════════════════════════════════════════════════════
# MF ADD SCORE (uses InstrumentScoringEngine)
# ══════════════════════════════════════════════════════════════════════════

def calculate_mf_add_score(
    candidate_fund: Dict[str, Any],
    portfolio_context: Dict[str, Any],
) -> Dict[str, Any]:
    """Calculate ADD score for a potential MF investment using InstrumentScoringEngine."""
    score_result = scoring_engine.score_mf_add(
        candidate_fund=candidate_fund,
        portfolio_context=portfolio_context,
    )
    
    return score_result


# ══════════════════════════════════════════════════════════════════════════
# STOCK EXIT SCORE (uses InstrumentScoringEngine)
# ══════════════════════════════════════════════════════════════════════════

async def calculate_stock_exit_score(
    stock_holding: Dict[str, Any],
    portfolio_context: Dict[str, Any],
) -> Dict[str, Any]:
    """Calculate EXIT score for a stock using InstrumentScoringEngine with real-time fundamentals.
    
    Flow:
    1. Fetch fundamental data from Groww (cached in Redis)
    2. Calculate tax impact
    3. Score using InstrumentScoringEngine
    """
    from services.groww_fundamentals import fetch_stock_fundamentals
    
    # Fetch real-time fundamentals from Groww
    nse_symbol = stock_holding.get("nse_symbol")
    fundamentals = None
    if nse_symbol:
        try:
            fundamentals = await fetch_stock_fundamentals(nse_symbol)
            if fundamentals:
                # Merge fundamentals into stock_holding for scoring
                stock_holding = {**stock_holding, **fundamentals}
                logger.info("Fetched fundamentals for %s: P/E=%s, ROE=%s", stock_holding['name'], fundamentals.get('pe_ratio'), fundamentals.get('roe'))
        except Exception as e:
            logger.warning("Failed to fetch fundamentals for %s: %s", nse_symbol, e)
    
    # Calculate tax impact
    tax_result = tax_calculator.calculate_tax_impact(stock_holding)
    
    # Use scoring engine
    score_result = scoring_engine.score_stock_exit(
        stock_holding=stock_holding,
        portfolio_context=portfolio_context,
        tax_result=tax_result,
    )
    
    # Add additional context
    score_result["stock_holding"] = stock_holding
    score_result["tax_impact"] = tax_result
    score_result["fundamentals"] = fundamentals  # NEW: For UI display
    
    return score_result


# ══════════════════════════════════════════════════════════════════════════
# ACTION GENERATION
# ══════════════════════════════════════════════════════════════════════════

async def generate_portfolio_actions(user_id: str) -> Dict[str, Any]:
    """Generate top 3 actionable recommendations for portfolio optimization.
    
    Flow:
    1. Calculate EXIT scores for all holdings
    2. Calculate ADD scores for gap-filling funds
    3. Generate max 3 actions (prioritized by score)
    4. Simulate impact
    
    Returns:
        {
            "actions": [action1, action2, action3],
            "exit_candidates": [...],
            "add_candidates": [...],
            "simulation": {...},
        }
    """
    # 1. Get portfolio data
    holdings = await db.holdings.find({"user_id": user_id}, {"_id": 0}).to_list(500)
    intelligence = await portfolio_intelligence.compute_portfolio_intelligence(user_id)
    
    if not holdings:
        return {"error": "No holdings found", "actions": []}
    
    # Calculate portfolio context
    total_value = sum(h["quantity"] * h["current_price"] for h in holdings)
    mf_holdings = [h for h in holdings if h.get("asset_type", "").lower() in ["mutual_fund", "mutual fund"]]
    stock_holdings = [h for h in holdings if h.get("asset_type", "").lower() in ["equity", "stock"]]
    
    portfolio_context = {
        "total_value": total_value,
        "mf_count": len(mf_holdings),
        "stock_count": len(stock_holdings),
        "asset_allocation": {
            "equity_pct": 70,  # Placeholder for MVP
            "debt_pct": 20,
            "gold_pct": 10,
        },
    }
    
    # 2. Calculate EXIT scores
    mf_exit_scores = []
    for mf in intelligence.get("mf_investments", []):
        if not mf.get("resolved"):
            continue
        
        # Find corresponding holding
        holding = next((h for h in mf_holdings if h["name"] == mf["scheme_name"]), None)
        if not holding:
            continue
        
        exit_result = await calculate_mf_exit_score(mf, intelligence, holding)
        mf_exit_scores.append(exit_result)
    
    stock_exit_scores = []
    for stock in stock_holdings:
        exit_result = await calculate_stock_exit_score(stock, portfolio_context)
        stock_exit_scores.append(exit_result)
    
    # Sort by exit score (highest first)
    all_exit_candidates = sorted(
        mf_exit_scores + stock_exit_scores,
        key=lambda x: x["exit_score"],
        reverse=True
    )
    
    # 3. Generate actions (max 3)
    actions = []
    
    # Action 1 & 2: Top exit recommendations
    for i, candidate in enumerate(all_exit_candidates[:2]):
        if candidate["action"] == "EXIT":
            asset_type = "Mutual Fund" if "mf_investment" in candidate else "Stock"
            name = candidate.get("mf_investment", {}).get("scheme_name") or candidate.get("stock_holding", {}).get("name")
            
            actions.append({
                "action_id": f"exit_{i+1}",
                "type": "EXIT",
                "title": f"Exit {asset_type}: {name}",
                "asset_type": asset_type.lower(),
                "asset_name": name,
                "exit_score": candidate["exit_score"],
                "reason": _generate_exit_reason(candidate),
                "amount": candidate.get("mf_investment", {}).get("amount_rs") or (
                    candidate.get("stock_holding", {}).get("quantity", 0) *
                    candidate.get("stock_holding", {}).get("current_price", 0)
                ),
                "tax_impact": candidate["tax_impact"]["tax_liability"],
                "post_tax_proceeds": candidate["tax_impact"]["post_tax_proceeds"],
                "priority": candidate["priority"],
            })
    
    # Action 3: Add recommendation (placeholder for MVP)
    if len(actions) < 3:
        # For MVP, suggest a generic debt fund if portfolio lacks debt
        if portfolio_context["asset_allocation"]["debt_pct"] < 20:
            actions.append({
                "action_id": "add_1",
                "type": "ADD",
                "title": "Add Debt Fund to balance allocation",
                "asset_type": "mutual_fund",
                "asset_name": "Recommended Debt Fund (TBD)",
                "add_score": 7.5,
                "reason": "Portfolio lacks debt allocation (currently 20%, target 30%)",
                "suggested_amount": total_value * 0.10,  # 10% reallocation
                "priority": "high",
            })
    
    return {
        "actions": actions[:3],
        "exit_candidates": all_exit_candidates[:10],
        "add_candidates": [],  # TODO: implement add candidate search
        "portfolio_summary": portfolio_context,
    }


def _generate_exit_reason(candidate: Dict[str, Any]) -> str:
    """Generate human-readable exit reason from score breakdown.
    
    Priority order: Quality > Momentum > Overlap > Concentration > Cost > Tax
    Tax is mentioned last as it's informational, not a primary reason.
    """
    scores = candidate["score_breakdown"]
    reasons = []
    
    # Priority 1: Fundamental quality issues
    if scores.get("quality", 0) >= 7:
        reasons.append("weak fundamentals (poor ROE/P-E/Debt)")
    
    # Priority 2: Technical/momentum issues
    if scores.get("momentum", 0) >= 7:
        reasons.append("negative price momentum")
    
    # Priority 3: Portfolio structure issues
    if scores.get("overlap", 0) >= 7:
        reasons.append("high overlap with other funds")
    if scores.get("concentration", 0) >= 7:
        reasons.append("overconcentrated position")
    
    # Priority 4: Cost issues
    if scores.get("cost", 0) >= 7:
        reasons.append("high expense ratio")
    
    # Priority 5: Tax (informational only)
    if scores.get("tax", 0) >= 7 and len(reasons) > 0:
        # Only mention tax if there are other reasons
        reasons.append("plus tax implications on exit")
    
    if not reasons:
        return "Optimization opportunity identified"
    
    return f"Recommended due to: {', '.join(reasons)}"
