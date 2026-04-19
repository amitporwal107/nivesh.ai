"""Tax Calculator — LTCG/STCG calculation for holdings.

Handles Indian tax rules:
- STCG (< 1 year): 15% (for equity/MF)
- LTCG (≥ 1 year): 10% on gains above ₹1L per year (for equity/MF)
- Indexed cost basis for debt funds (if > 3 years)
"""
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)

# Tax rates (Indian equity/MF)
STCG_RATE = 0.15  # 15%
LTCG_RATE = 0.10  # 10%
LTCG_EXEMPTION = 100000  # ₹1L exemption per year

# Holding period thresholds
STCG_THRESHOLD_DAYS = 365  # 1 year for equity/MF


def calculate_holding_period_days(buy_date: str) -> int:
    """Calculate holding period in days from buy_date to today."""
    try:
        if isinstance(buy_date, str):
            # Parse ISO format date
            buy_dt = datetime.fromisoformat(buy_date.replace('Z', '+00:00'))
        else:
            buy_dt = buy_date
        
        now = datetime.now(timezone.utc)
        delta = now - buy_dt
        return delta.days
    except Exception as e:
        logger.warning(f"Error parsing buy_date {buy_date}: {e}")
        return 0


def is_long_term(holding_period_days: int, asset_type: str = "equity") -> bool:
    """Check if holding qualifies as long-term capital gain."""
    # For equity/MF: 1 year threshold
    # For debt: 3 years (not implemented yet)
    return holding_period_days >= STCG_THRESHOLD_DAYS


def calculate_capital_gain(
    buy_price: float,
    current_price: float,
    quantity: float,
) -> float:
    """Calculate absolute capital gain in rupees."""
    invested = buy_price * quantity
    current_value = current_price * quantity
    return current_value - invested


def calculate_tax_impact(
    holding: Dict[str, Any],
    exit_amount_rs: Optional[float] = None,
) -> Dict[str, Any]:
    """Calculate tax impact for exiting a holding.
    
    Args:
        holding: Portfolio holding with buy_date, buy_price, current_price, quantity
        exit_amount_rs: Optional specific amount to exit (default: full holding)
    
    Returns:
        {
            "holding_period_days": int,
            "is_long_term": bool,
            "capital_gain": float,
            "taxable_gain": float,
            "tax_liability": float,
            "tax_rate": float,
            "post_tax_proceeds": float,
            "tax_score": float,  # 0-10 for decision engine
        }
    """
    try:
        # Extract holding details
        buy_price = float(holding.get("buy_price", 0))
        current_price = float(holding.get("current_price", 0))
        quantity = float(holding.get("quantity", 0))
        buy_date = holding.get("buy_date")
        
        if not buy_date or buy_price == 0 or current_price == 0:
            return _empty_tax_result("Missing price or date data")
        
        # Calculate holding period
        holding_period_days = calculate_holding_period_days(buy_date)
        is_lt = is_long_term(holding_period_days)
        
        # Calculate capital gain
        total_invested = buy_price * quantity
        total_current = current_price * quantity
        total_gain = total_current - total_invested
        
        # If partial exit specified, prorate the gain
        if exit_amount_rs:
            exit_ratio = exit_amount_rs / total_current if total_current > 0 else 0
            capital_gain = total_gain * exit_ratio
            exit_quantity = quantity * exit_ratio
        else:
            capital_gain = total_gain
            exit_quantity = quantity
            exit_amount_rs = total_current
        
        # Calculate tax
        if capital_gain <= 0:
            # No tax on losses
            tax_liability = 0
            taxable_gain = 0
            tax_rate = 0
            tax_score = 1.0  # Best score - no tax hit
        elif is_lt:
            # LTCG: 10% on gains above ₹1L
            taxable_gain = max(0, capital_gain - LTCG_EXEMPTION)
            tax_liability = taxable_gain * LTCG_RATE
            tax_rate = LTCG_RATE
            
            # Tax score: 0-10 (lower is better for exit)
            # < 1 year old = 10 (worst - STCG would apply)
            # 1-2 years = 3-5 (moderate LTCG)
            # > 2 years = 1-3 (acceptable LTCG)
            if holding_period_days < 365:
                tax_score = 10.0
            elif holding_period_days < 730:
                # 1-2 years: score 3-5
                tax_score = 5.0 - (holding_period_days - 365) / 365 * 2
            else:
                # > 2 years: score 1-3
                tax_score = max(1.0, 3.0 - (holding_period_days - 730) / 365)
        else:
            # STCG: 15% on all gains
            taxable_gain = capital_gain
            tax_liability = taxable_gain * STCG_RATE
            tax_rate = STCG_RATE
            tax_score = 10.0  # Worst score - STCG hit
        
        post_tax_proceeds = exit_amount_rs - tax_liability
        
        return {
            "holding_period_days": holding_period_days,
            "holding_period_years": round(holding_period_days / 365, 2),
            "is_long_term": is_lt,
            "capital_gain": round(capital_gain, 2),
            "taxable_gain": round(taxable_gain, 2),
            "tax_liability": round(tax_liability, 2),
            "tax_rate": tax_rate,
            "exit_amount_rs": round(exit_amount_rs, 2),
            "post_tax_proceeds": round(post_tax_proceeds, 2),
            "tax_efficiency_pct": round((post_tax_proceeds / exit_amount_rs * 100) if exit_amount_rs > 0 else 0, 2),
            "tax_score": round(tax_score, 2),  # 0-10 for decision engine
        }
    
    except Exception as e:
        logger.error(f"Tax calculation error: {e}")
        return _empty_tax_result(f"Calculation error: {str(e)}")


def optimize_exit_timing(holdings: list[Dict[str, Any]]) -> Dict[str, Any]:
    """Suggest optimal exit timing to minimize tax impact.
    
    Args:
        holdings: List of portfolio holdings
    
    Returns:
        {
            "exit_now": [holdings with good tax efficiency],
            "defer_to_ltcg": [holdings close to 1 year, should wait],
            "loss_harvest": [holdings with losses, good for tax loss harvesting],
        }
    """
    exit_now = []
    defer_to_ltcg = []
    loss_harvest = []
    
    for h in holdings:
        tax_result = calculate_tax_impact(h)
        
        # If holding has loss, good for tax loss harvesting
        if tax_result["capital_gain"] < 0:
            loss_harvest.append({
                "holding": h,
                "loss_amount": abs(tax_result["capital_gain"]),
                "tax_score": tax_result["tax_score"],
            })
        
        # If STCG but close to LTCG (11-12 months), suggest deferral
        elif not tax_result["is_long_term"] and tax_result["holding_period_days"] > 300:
            days_to_ltcg = 365 - tax_result["holding_period_days"]
            defer_to_ltcg.append({
                "holding": h,
                "days_to_ltcg": days_to_ltcg,
                "stcg_impact": tax_result["tax_liability"],
                "recommendation": f"Wait {days_to_ltcg} days to save {tax_result['tax_liability']:.0f} in STCG",
            })
        
        # Otherwise, OK to exit now
        else:
            exit_now.append({
                "holding": h,
                "tax_score": tax_result["tax_score"],
                "tax_liability": tax_result["tax_liability"],
            })
    
    return {
        "exit_now": sorted(exit_now, key=lambda x: x["tax_score"]),
        "defer_to_ltcg": sorted(defer_to_ltcg, key=lambda x: x["days_to_ltcg"]),
        "loss_harvest": sorted(loss_harvest, key=lambda x: x["loss_amount"], reverse=True),
    }


def calculate_portfolio_tax_liability(
    holdings: list[Dict[str, Any]],
    exit_plan: list[Dict[str, Any]],
) -> Dict[str, Any]:
    """Calculate total tax liability for a planned exit strategy.
    
    Args:
        holdings: Portfolio holdings
        exit_plan: List of {holding_id, exit_amount_rs}
    
    Returns:
        {
            "total_exit_value": float,
            "total_capital_gain": float,
            "total_tax_liability": float,
            "post_tax_proceeds": float,
            "ltcg_count": int,
            "stcg_count": int,
            "breakdown": [...]
        }
    """
    holdings_map = {h.get("holding_id") or h.get("name"): h for h in holdings}
    
    total_exit_value = 0
    total_capital_gain = 0
    total_tax_liability = 0
    ltcg_count = 0
    stcg_count = 0
    breakdown = []
    
    for plan in exit_plan:
        holding_id = plan.get("holding_id")
        exit_amount = plan.get("exit_amount_rs")
        
        holding = holdings_map.get(holding_id)
        if not holding:
            continue
        
        tax_result = calculate_tax_impact(holding, exit_amount)
        
        total_exit_value += tax_result["exit_amount_rs"]
        total_capital_gain += tax_result["capital_gain"]
        total_tax_liability += tax_result["tax_liability"]
        
        if tax_result["is_long_term"]:
            ltcg_count += 1
        else:
            stcg_count += 1
        
        breakdown.append({
            "holding_name": holding.get("name"),
            "exit_amount": tax_result["exit_amount_rs"],
            "capital_gain": tax_result["capital_gain"],
            "tax_liability": tax_result["tax_liability"],
            "tax_type": "LTCG" if tax_result["is_long_term"] else "STCG",
        })
    
    return {
        "total_exit_value": round(total_exit_value, 2),
        "total_capital_gain": round(total_capital_gain, 2),
        "total_tax_liability": round(total_tax_liability, 2),
        "post_tax_proceeds": round(total_exit_value - total_tax_liability, 2),
        "effective_tax_rate": round((total_tax_liability / total_capital_gain * 100) if total_capital_gain > 0 else 0, 2),
        "ltcg_count": ltcg_count,
        "stcg_count": stcg_count,
        "breakdown": breakdown,
    }


def _empty_tax_result(reason: str) -> Dict[str, Any]:
    """Return empty tax result with reason."""
    return {
        "holding_period_days": 0,
        "holding_period_years": 0,
        "is_long_term": False,
        "capital_gain": 0,
        "taxable_gain": 0,
        "tax_liability": 0,
        "tax_rate": 0,
        "exit_amount_rs": 0,
        "post_tax_proceeds": 0,
        "tax_efficiency_pct": 0,
        "tax_score": 5.0,  # Neutral
        "error": reason,
    }
