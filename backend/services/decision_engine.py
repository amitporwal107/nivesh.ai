"""Decision Engine — EXIT and ADD scoring for portfolio optimization.

Implements:
- MF EXIT Score (overlap + tax + cost + quality + fit)
- MF ADD Score (gap fit + low overlap + quality + low cost + headroom)
- Stock EXIT Score (concentration + tax + quality + momentum + sector + role)
- Inline MF/Stock quality scoring
"""
from typing import Dict, Any, List, Optional
import logging
from collections import defaultdict

from services import tax_calculator, portfolio_intelligence
from deps import db

logger = logging.getLogger(__name__)

# ── MF EXIT Score Weights ────────────────────────────────────────────────
MF_EXIT_WEIGHTS = {
    "overlap": 0.30,
    "tax": 0.25,
    "cost": 0.15,
    "quality": 0.20,
    "fit": 0.10,
}

# ── MF ADD Score Weights ─────────────────────────────────────────────────
MF_ADD_WEIGHTS = {
    "gap_fit": 0.30,
    "low_overlap": 0.25,
    "quality": 0.25,
    "low_cost": 0.10,
    "headroom": 0.10,
}

# ── Stock EXIT Score Weights ─────────────────────────────────────────────
STOCK_EXIT_WEIGHTS = {
    "concentration": 0.25,
    "tax": 0.20,
    "quality": 0.25,
    "momentum": 0.15,
    "sector": 0.10,
    "role": 0.05,
}

# ── Thresholds ───────────────────────────────────────────────────────────
EXIT_THRESHOLD_HIGH = 7.0  # ≥ 7 = EXIT
EXIT_THRESHOLD_LOW = 4.0   # < 4 = Keep/Add
ADD_THRESHOLD_HIGH = 7.0   # ≥ 7 = ADD
ADD_THRESHOLD_LOW = 5.0    # < 5 = Ignore


# ══════════════════════════════════════════════════════════════════════════
# MF QUALITY SCORING (INLINE)
# ══════════════════════════════════════════════════════════════════════════

def calculate_mf_quality_score(
    fund_metadata: Dict[str, Any],
    performance_ratios: Dict[str, Any],
    category_avg: Optional[Dict[str, Any]] = None,
) -> float:
    """Calculate MF Quality Score (0-10).
    
    Lower is better (1-3 = strong, 4-6 = average, 7-10 = weak)
    
    Components:
    - Performance consistency (vs category)
    - Risk-adjusted return (Sharpe/Sortino)
    - Expense ratio (cost efficiency)
    - AUM stability (reliability)
    """
    scores = []
    
    # 1. Performance vs category (25%)
    ret_1y = performance_ratios.get("ret_1y")
    ret_3y = performance_ratios.get("ret_3y")
    if ret_1y is not None and ret_3y is not None:
        # Simplified: if both > 12%, strong (score 2)
        # if both 8-12%, average (score 5)
        # if both < 8%, weak (score 8)
        avg_ret = (float(ret_1y) + float(ret_3y)) / 2
        if avg_ret >= 12:
            scores.append(2.0)
        elif avg_ret >= 8:
            scores.append(5.0)
        else:
            scores.append(8.0)
    else:
        scores.append(5.0)  # Neutral if no data
    
    # 2. Risk-adjusted return (25%)
    sharpe = performance_ratios.get("sharpe")
    sortino = performance_ratios.get("sortino")
    if sharpe is not None:
        sharpe_val = float(sharpe)
        if sharpe_val >= 1.5:
            scores.append(2.0)  # Excellent
        elif sharpe_val >= 0.8:
            scores.append(5.0)  # Average
        else:
            scores.append(8.0)  # Poor
    elif sortino is not None:
        sortino_val = float(sortino)
        if sortino_val >= 1.5:
            scores.append(2.0)
        elif sortino_val >= 0.8:
            scores.append(5.0)
        else:
            scores.append(8.0)
    else:
        scores.append(5.0)
    
    # 3. Expense ratio (25%)
    expense_ratio = fund_metadata.get("expense_ratio")
    if expense_ratio is not None:
        exp_val = float(expense_ratio)
        if exp_val <= 0.5:
            scores.append(2.0)  # Very low cost
        elif exp_val <= 1.0:
            scores.append(5.0)  # Average
        else:
            scores.append(8.0)  # High cost
    else:
        scores.append(5.0)
    
    # 4. AUM stability (25%)
    aum_cr = fund_metadata.get("aum_cr")
    if aum_cr is not None:
        aum_val = float(aum_cr)
        if aum_val >= 5000:  # ≥ ₹5000 Cr
            scores.append(2.0)  # Large, stable
        elif aum_val >= 1000:
            scores.append(5.0)  # Medium
        else:
            scores.append(7.0)  # Small (slightly risky)
    else:
        scores.append(5.0)
    
    # Average score
    quality_score = sum(scores) / len(scores) if scores else 5.0
    return round(quality_score, 2)


# ══════════════════════════════════════════════════════════════════════════
# MF EXIT SCORE
# ══════════════════════════════════════════════════════════════════════════

async def calculate_mf_exit_score(
    mf_investment: Dict[str, Any],
    portfolio_intelligence_data: Dict[str, Any],
    holding: Dict[str, Any],
) -> Dict[str, Any]:
    """Calculate EXIT score for a mutual fund (0-10).
    
    Higher score = stronger exit recommendation
    
    Formula:
    MF Exit Score = 
        (0.30 × Overlap)
        + (0.25 × Tax)
        + (0.15 × Cost)
        + (0.20 × MF Quality)
        + (0.10 × Portfolio Fit)
    """
    scores = {}
    
    # 1. Overlap Score (30%)
    # Use fund overlap from portfolio intelligence
    pairs = portfolio_intelligence_data.get("pairwise_overlap", [])
    mf_id = mf_investment.get("instrument_id")
    
    # Find max overlap for this fund
    max_overlap = 0
    for pair in pairs:
        if pair["a"] == mf_id or pair["b"] == mf_id:
            max_overlap = max(max_overlap, pair["overlap_pct"])
    
    # Scale overlap to 0-10
    # 0% overlap = 0, 100% overlap = 10
    overlap_score = min(10, max_overlap / 10)
    scores["overlap"] = round(overlap_score, 2)
    
    # 2. Tax Score (25%)
    tax_result = tax_calculator.calculate_tax_impact(holding)
    scores["tax"] = tax_result["tax_score"]
    
    # 3. Cost Score (15%)
    expense_ratio = mf_investment.get("expense_ratio")
    if expense_ratio is not None:
        # Scale: 0% = 0, 2%+ = 10
        cost_score = min(10, float(expense_ratio) * 5)
    else:
        cost_score = 5.0
    scores["cost"] = round(cost_score, 2)
    
    # 4. MF Quality Score (20%)
    catalog = portfolio_intelligence_data.get("catalog", {})
    fund_data = catalog.get(mf_id, {})
    
    quality_score = calculate_mf_quality_score(
        fund_metadata={
            "expense_ratio": expense_ratio,
            "aum_cr": mf_investment.get("aum_cr"),
        },
        performance_ratios=fund_data.get("ratios", {}),
    )
    scores["quality"] = quality_score
    
    # 5. Portfolio Fit Score (10%)
    # Simple: if category is overweight → high score (should exit)
    # For MVP, use neutral score
    scores["fit"] = 5.0
    
    # Calculate weighted EXIT score
    exit_score = (
        scores["overlap"] * MF_EXIT_WEIGHTS["overlap"] +
        scores["tax"] * MF_EXIT_WEIGHTS["tax"] +
        scores["cost"] * MF_EXIT_WEIGHTS["cost"] +
        scores["quality"] * MF_EXIT_WEIGHTS["quality"] +
        scores["fit"] * MF_EXIT_WEIGHTS["fit"]
    )
    
    # Determine action
    if exit_score >= EXIT_THRESHOLD_HIGH:
        action = "EXIT"
        priority = "high"
    elif exit_score >= EXIT_THRESHOLD_LOW:
        action = "HOLD"
        priority = "medium"
    else:
        action = "KEEP"
        priority = "low"
    
    return {
        "mf_investment": mf_investment,
        "holding": holding,
        "exit_score": round(exit_score, 2),
        "action": action,
        "priority": priority,
        "score_breakdown": scores,
        "tax_impact": tax_result,
    }


# ══════════════════════════════════════════════════════════════════════════
# MF ADD SCORE
# ══════════════════════════════════════════════════════════════════════════

def calculate_mf_add_score(
    candidate_fund: Dict[str, Any],
    portfolio_context: Dict[str, Any],
) -> Dict[str, Any]:
    """Calculate ADD score for a potential MF investment (0-10).
    
    Higher score = stronger add recommendation
    
    Formula:
    MF Add Score = 
        (0.30 × Gap Fit)
        + (0.25 × (10 - Overlap))
        + (0.25 × (10 - MF Quality))
        + (0.10 × (10 - Cost))
        + (0.10 × Headroom)
    """
    scores = {}
    
    # 1. Gap Fit (30%)
    # For MVP: check if fills asset allocation gap
    # If debt fund and portfolio has < 20% debt → high score
    # If equity fund and portfolio has < 60% equity → high score
    category = candidate_fund.get("category", "").lower()
    current_allocation = portfolio_context.get("asset_allocation", {})
    
    if "debt" in category and current_allocation.get("debt_pct", 0) < 20:
        gap_fit_score = 8.0  # Strong fit
    elif "equity" in category and current_allocation.get("equity_pct", 0) < 60:
        gap_fit_score = 7.0
    else:
        gap_fit_score = 5.0  # Neutral
    scores["gap_fit"] = gap_fit_score
    
    # 2. Low Overlap (25%)
    # Inverse of overlap: 10 - overlap_score
    # For MVP, assume new fund has low overlap
    overlap_score = 2.0  # Low overlap assumed
    scores["low_overlap"] = 10 - overlap_score
    
    # 3. Quality (25%)
    # Use (10 - quality_score) so lower quality = lower add score
    quality_score = calculate_mf_quality_score(
        fund_metadata=candidate_fund,
        performance_ratios=candidate_fund.get("ratios", {}),
    )
    scores["quality"] = 10 - quality_score
    
    # 4. Low Cost (10%)
    expense_ratio = candidate_fund.get("expense_ratio")
    if expense_ratio is not None:
        cost_score = min(10, float(expense_ratio) * 5)
        scores["low_cost"] = 10 - cost_score
    else:
        scores["low_cost"] = 5.0
    
    # 5. Headroom (10%)
    # Check if category has room for more allocation
    # For MVP: neutral
    scores["headroom"] = 5.0
    
    # Calculate weighted ADD score
    add_score = (
        scores["gap_fit"] * MF_ADD_WEIGHTS["gap_fit"] +
        scores["low_overlap"] * MF_ADD_WEIGHTS["low_overlap"] +
        scores["quality"] * MF_ADD_WEIGHTS["quality"] +
        scores["low_cost"] * MF_ADD_WEIGHTS["low_cost"] +
        scores["headroom"] * MF_ADD_WEIGHTS["headroom"]
    )
    
    # Determine action
    if add_score >= ADD_THRESHOLD_HIGH:
        action = "ADD"
        priority = "high"
    elif add_score >= ADD_THRESHOLD_LOW:
        action = "CONSIDER"
        priority = "medium"
    else:
        action = "IGNORE"
        priority = "low"
    
    return {
        "fund": candidate_fund,
        "add_score": round(add_score, 2),
        "action": action,
        "priority": priority,
        "score_breakdown": scores,
    }


# ══════════════════════════════════════════════════════════════════════════
# STOCK EXIT SCORE
# ══════════════════════════════════════════════════════════════════════════

async def calculate_stock_exit_score(
    stock_holding: Dict[str, Any],
    portfolio_context: Dict[str, Any],
) -> Dict[str, Any]:
    """Calculate EXIT score for a stock (0-10).
    
    Higher score = stronger exit recommendation
    
    Formula:
    Stock Exit Score = 
        (0.25 × Concentration)
        + (0.20 × Tax)
        + (0.25 × Quality)
        + (0.15 × Momentum)
        + (0.10 × Sector Exposure)
        + (0.05 × Portfolio Role)
    """
    scores = {}
    
    # 1. Concentration (25%)
    # If stock is > 10% of portfolio → high score
    total_value = portfolio_context.get("total_value", 1)
    stock_value = stock_holding["quantity"] * stock_holding["current_price"]
    concentration_pct = (stock_value / total_value * 100) if total_value > 0 else 0
    
    # Scale: 0% = 0, 10%+ = 10
    concentration_score = min(10, concentration_pct)
    scores["concentration"] = round(concentration_score, 2)
    
    # 2. Tax Score (20%)
    tax_result = tax_calculator.calculate_tax_impact(stock_holding)
    scores["tax"] = tax_result["tax_score"]
    
    # 3. Quality Score (25%)
    # For MVP: simplified placeholder (1-10)
    # In production: integrate fundamentals (ROCE, growth, valuation, debt)
    quality_score = 5.0  # Neutral for MVP
    scores["quality"] = quality_score
    
    # 4. Momentum (15%)
    # Simple: calculate recent return
    buy_price = stock_holding.get("buy_price", 0)
    current_price = stock_holding.get("current_price", 0)
    if buy_price > 0:
        return_pct = (current_price - buy_price) / buy_price * 100
        # Negative return = high exit score
        if return_pct < -20:
            momentum_score = 9.0  # Strong sell signal
        elif return_pct < 0:
            momentum_score = 7.0
        elif return_pct < 10:
            momentum_score = 5.0
        else:
            momentum_score = 3.0  # Positive momentum, keep
    else:
        momentum_score = 5.0
    scores["momentum"] = momentum_score
    
    # 5. Sector Exposure (10%)
    # If sector is overweight → high score
    # For MVP: neutral
    scores["sector"] = 5.0
    
    # 6. Portfolio Role (5%)
    # Core vs redundant
    # For MVP: neutral
    scores["role"] = 5.0
    
    # Calculate weighted EXIT score
    exit_score = (
        scores["concentration"] * STOCK_EXIT_WEIGHTS["concentration"] +
        scores["tax"] * STOCK_EXIT_WEIGHTS["tax"] +
        scores["quality"] * STOCK_EXIT_WEIGHTS["quality"] +
        scores["momentum"] * STOCK_EXIT_WEIGHTS["momentum"] +
        scores["sector"] * STOCK_EXIT_WEIGHTS["sector"] +
        scores["role"] * STOCK_EXIT_WEIGHTS["role"]
    )
    
    # Determine action
    if exit_score >= EXIT_THRESHOLD_HIGH:
        action = "EXIT"
        priority = "high"
    elif exit_score >= EXIT_THRESHOLD_LOW:
        action = "HOLD"
        priority = "medium"
    else:
        action = "KEEP"
        priority = "low"
    
    return {
        "stock_holding": stock_holding,
        "exit_score": round(exit_score, 2),
        "action": action,
        "priority": priority,
        "score_breakdown": scores,
        "tax_impact": tax_result,
    }


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
    """Generate human-readable exit reason from score breakdown."""
    scores = candidate["score_breakdown"]
    reasons = []
    
    if scores.get("overlap", 0) >= 7:
        reasons.append("high overlap with other funds")
    if scores.get("tax", 0) >= 7:
        reasons.append("significant tax liability")
    if scores.get("cost", 0) >= 7:
        reasons.append("high expense ratio")
    if scores.get("quality", 0) >= 7:
        reasons.append("underperforming vs category")
    if scores.get("concentration", 0) >= 7:
        reasons.append("overconcentrated position")
    if scores.get("momentum", 0) >= 7:
        reasons.append("negative momentum")
    
    if not reasons:
        return "Optimization opportunity identified"
    
    return f"Recommended due to: {', '.join(reasons)}"
