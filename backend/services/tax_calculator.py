"""Tax Calculator — LTCG/STCG for holdings using ClearTax rules.

Implements Indian capital gains tax rules per
https://cleartax.in/s/capital-gains-income (FY 2025-26, post 23-Jul-2024):

Equity MF / Listed Equity / Equity ETF:
    STCG (≤ 12 months): 20%
    LTCG (>  12 months): 12.5% on gains exceeding ₹1,25,000 / FY

Debt MF acquired on/after 01-Apr-2023: taxed at slab rate (always)
Debt MF acquired before 01-Apr-2023:
    STCG (≤ 24 months): slab
    LTCG (>  24 months): 12.5%

Gold / Gold ETF / SGB / Property:
    STCG (≤ 24 months): slab
    LTCG (>  24 months): 12.5%

Bonds (listed):
    STCG (≤ 12 months): 20%
    LTCG (>  12 months): 12.5%

When user's income slab is unknown, we default to `DEFAULT_SLAB_RATE` (30% —
conservative). When `buy_date` is missing on a holding, the tax impact is
flagged `tax_impact_pending` (True) and excluded from plan-level aggregates
instead of fabricating a number.
"""
from datetime import datetime, timezone, date
from typing import Dict, Any, Optional, List
import logging

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────
# ClearTax FY 2025-26 rates (https://cleartax.in/s/capital-gains-income)
# ──────────────────────────────────────────────────────────────────────
EQUITY_STCG_RATE = 0.20          # 20% (Sec 111A)
EQUITY_LTCG_RATE = 0.125         # 12.5% (Sec 112A)
EQUITY_LTCG_EXEMPTION = 125000   # ₹1.25L per FY, aggregated across equity

NON_EQUITY_LTCG_RATE = 0.125     # Gold/SGB/listed bonds/debt-pre-Apr23

DEFAULT_SLAB_RATE = 0.30         # fallback when user slab unknown

# Holding period thresholds (days)
THRESHOLD_EQUITY_DAYS = 365      # 12 months
THRESHOLD_OTHERS_DAYS = 730      # 24 months (close enough; tax year calendar OK)

# Debt-MF cutover date (post-Finance Act 2023 — always short-term / slab)
DEBT_MF_SLAB_CUTOVER = date(2023, 4, 1)

# Legacy constants kept for backward compat (other modules may import)
STCG_RATE = EQUITY_STCG_RATE
LTCG_RATE = EQUITY_LTCG_RATE
LTCG_EXEMPTION = EQUITY_LTCG_EXEMPTION
LTCG_THRESHOLD_DAYS = THRESHOLD_EQUITY_DAYS


# ──────────────────────────────────────────────────────────────────────
# Asset classification
# ──────────────────────────────────────────────────────────────────────

def _is_equity_like(asset_type: str, name: str = "") -> bool:
    at = (asset_type or "").lower()
    n = (name or "").lower()
    if at in ("equity", "stock"):
        return True
    if at in ("mutual_fund", "mf"):
        # debt funds flagged via name/sector; default MF → equity
        if any(k in n for k in ["liquid", "gilt", "bond fund", "corporate bond", "short term", "overnight", "banking & psu", "low duration", "ultra short", "medium duration", "long duration", "credit risk", "floater", "dynamic bond", "debt"]):
            return False
        return True
    if at == "etf":
        if any(k in n for k in ["gold", "sgb", "liquid", "gilt", "bond"]):
            return False
        return True
    return False


def _is_gold_like(asset_type: str, name: str = "") -> bool:
    at = (asset_type or "").lower()
    n = (name or "").lower()
    return at == "gold" or "gold" in n or "sgb" in n or "sovereign gold" in n


def _is_debt_like(asset_type: str, name: str = "") -> bool:
    at = (asset_type or "").lower()
    n = (name or "").lower()
    if at in ("bond", "debt", "fd", "deposit"):
        return True
    if at in ("mutual_fund", "etf") and any(k in n for k in ["liquid", "gilt", "bond", "corporate bond", "short term", "overnight", "banking & psu", "low duration", "ultra short", "medium duration", "long duration", "credit risk", "floater", "dynamic bond", "debt"]):
        return True
    return False


def _classify_asset(asset_type: str, name: str = "") -> str:
    """Return one of: 'equity', 'debt', 'gold', 'other'."""
    if _is_gold_like(asset_type, name):
        return "gold"
    if _is_debt_like(asset_type, name):
        return "debt"
    if _is_equity_like(asset_type, name):
        return "equity"
    return "other"


# ──────────────────────────────────────────────────────────────────────
# Date helpers
# ──────────────────────────────────────────────────────────────────────

def calculate_holding_period_days(buy_date) -> Optional[int]:
    """Calculate holding period in days from buy_date to today.

    Returns None when buy_date is missing / unparseable — caller must treat
    this as 'tax pending' rather than STCG=0.
    """
    if not buy_date:
        return None
    try:
        if isinstance(buy_date, str):
            buy_dt = datetime.fromisoformat(buy_date.replace("Z", "+00:00"))
        elif isinstance(buy_date, datetime):
            buy_dt = buy_date
        elif isinstance(buy_date, date):
            buy_dt = datetime.combine(buy_date, datetime.min.time(), tzinfo=timezone.utc)
        else:
            return None
        if buy_dt.tzinfo is None:
            buy_dt = buy_dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - buy_dt).days
    except Exception as e:
        logger.warning(f"Error parsing buy_date {buy_date!r}: {e}")
        return None


def _parse_date(buy_date) -> Optional[date]:
    if not buy_date:
        return None
    try:
        if isinstance(buy_date, str):
            return datetime.fromisoformat(buy_date.replace("Z", "+00:00")).date()
        if isinstance(buy_date, datetime):
            return buy_date.date()
        if isinstance(buy_date, date):
            return buy_date
    except Exception:
        return None
    return None


def is_long_term(holding_period_days: Optional[int], asset_class: str = "equity") -> bool:
    """Check if the holding qualifies as long-term per ClearTax rules."""
    if holding_period_days is None:
        return False
    if asset_class == "equity":
        return holding_period_days > THRESHOLD_EQUITY_DAYS
    return holding_period_days > THRESHOLD_OTHERS_DAYS


def calculate_capital_gain(buy_price: float, current_price: float, quantity: float) -> float:
    invested = (buy_price or 0) * (quantity or 0)
    current_value = (current_price or 0) * (quantity or 0)
    return current_value - invested


# ──────────────────────────────────────────────────────────────────────
# Main entry point
# ──────────────────────────────────────────────────────────────────────

def calculate_tax_impact(
    holding: Dict[str, Any],
    exit_amount_rs: Optional[float] = None,
    user_slab_rate: float = DEFAULT_SLAB_RATE,
    ltcg_exemption_used: float = 0,
) -> Dict[str, Any]:
    """Calculate tax impact for exiting a holding using ClearTax FY 25-26 rules.

    Args:
        holding: dict with buy_date, buy_price, current_price, quantity, asset_type, name
        exit_amount_rs: optional partial exit (default: full value)
        user_slab_rate: user's income tax slab (for debt/gold STCG). Default 30%.
        ltcg_exemption_used: amount of ₹1.25L exemption already consumed in this FY
                             (aggregated across all equity exits in the same plan).

    Returns dict with holding_period_days/is_long_term/capital_gain/taxable_gain/
    tax_liability/tax_rate/exit_amount_rs/post_tax_proceeds/tax_score/tax_regime/
    tax_impact_pending.
    """
    try:
        buy_price = float(holding.get("buy_price", 0) or 0)
        current_price = float(holding.get("current_price", 0) or 0)
        quantity = float(holding.get("quantity", 0) or 0)
        buy_date = holding.get("buy_date")
        asset_type = holding.get("asset_type") or ""
        name = holding.get("name") or ""

        asset_class = _classify_asset(asset_type, name)
        total_invested = buy_price * quantity
        total_current = current_price * quantity
        total_gain = total_current - total_invested

        if exit_amount_rs and total_current > 0:
            exit_amount_rs = min(exit_amount_rs, total_current)
            capital_gain = total_gain * (exit_amount_rs / total_current)
        else:
            exit_amount_rs = total_current
            capital_gain = total_gain

        # ── Pending state: no buy_date OR no prices ──
        holding_period_days = calculate_holding_period_days(buy_date)
        if holding_period_days is None or buy_price == 0 or current_price == 0:
            return {
                "holding_period_days": holding_period_days,
                "holding_period_years": (round(holding_period_days / 365, 2) if holding_period_days else None),
                "is_long_term": None,
                "capital_gain": round(capital_gain, 2) if buy_price and current_price else 0.0,
                "taxable_gain": 0.0,
                "tax_liability": 0.0,
                "tax_rate": 0.0,
                "exit_amount_rs": round(exit_amount_rs, 2),
                "post_tax_proceeds": round(exit_amount_rs, 2),
                "tax_efficiency_pct": 100.0,
                "tax_score": 5.0,  # neutral (unknown)
                "tax_regime": "pending",
                "asset_class": asset_class,
                "tax_impact_pending": True,
                "pending_reason": (
                    "purchase_date_missing" if not buy_date else "price_missing"
                ),
            }

        # ── Debt MF cutover: post-Apr-2023 always slab (STCG-like) ──
        buy_dt = _parse_date(buy_date)
        if asset_class == "debt" and buy_dt and buy_dt >= DEBT_MF_SLAB_CUTOVER:
            is_lt = False
            tax_regime = "debt_slab_always"
        else:
            is_lt = is_long_term(holding_period_days, asset_class)
            tax_regime = f"{asset_class}_{'ltcg' if is_lt else 'stcg'}"

        if capital_gain <= 0:
            tax_liability = 0.0
            taxable_gain = 0.0
            tax_rate = 0.0
            tax_score = 0.0  # free exit
        else:
            if asset_class == "equity":
                if is_lt:
                    effective_exemption = max(0, EQUITY_LTCG_EXEMPTION - ltcg_exemption_used)
                    taxable_gain = max(0, capital_gain - effective_exemption)
                    tax_rate = EQUITY_LTCG_RATE
                else:
                    taxable_gain = capital_gain
                    tax_rate = EQUITY_STCG_RATE
            elif asset_class == "debt":
                # Debt: STCG at slab; LTCG (pre-Apr23 only, >24m) at 12.5%
                if is_lt:
                    taxable_gain = capital_gain
                    tax_rate = NON_EQUITY_LTCG_RATE
                else:
                    taxable_gain = capital_gain
                    tax_rate = user_slab_rate
            else:  # gold / other
                if is_lt:
                    taxable_gain = capital_gain
                    tax_rate = NON_EQUITY_LTCG_RATE
                else:
                    taxable_gain = capital_gain
                    tax_rate = user_slab_rate

            tax_liability = taxable_gain * tax_rate

            # Tax score (0-10) — proportional to tax hit as % of exit amount
            tax_pct_of_exit = (tax_liability / exit_amount_rs * 100) if exit_amount_rs > 0 else 0
            if tax_pct_of_exit < 2:
                tax_score = 1.0
            elif tax_pct_of_exit < 5:
                tax_score = 2.0 + (tax_pct_of_exit - 2) / 3 * 2
            elif tax_pct_of_exit < 10:
                tax_score = 4.0 + (tax_pct_of_exit - 5) / 5 * 3
            else:
                tax_score = min(10.0, 7.0 + (tax_pct_of_exit - 10) / 5 * 3)

        post_tax_proceeds = exit_amount_rs - tax_liability

        # Tax efficiency score — benefit per ₹ of tax cost.
        # When caller can't yet estimate benefit (per-action), we return a neutral
        # placeholder; the SWITCH scorer overrides this with a proper ratio.
        tax_efficiency_score = None  # filled by SWITCH/ADD callers

        return {
            "holding_period_days": holding_period_days,
            "holding_period_years": round(holding_period_days / 365, 2),
            "is_long_term": is_lt,
            "capital_gain": round(capital_gain, 2),
            "taxable_gain": round(taxable_gain, 2),
            "tax_liability": round(tax_liability, 2),
            "tax_rate": round(tax_rate, 4),
            "exit_amount_rs": round(exit_amount_rs, 2),
            "post_tax_proceeds": round(post_tax_proceeds, 2),
            "tax_efficiency_pct": round((post_tax_proceeds / exit_amount_rs * 100) if exit_amount_rs > 0 else 0, 2),
            "tax_efficiency_score": tax_efficiency_score,
            "tax_score": round(tax_score, 2),
            "tax_regime": tax_regime,
            "asset_class": asset_class,
            "tax_impact_pending": False,
        }

    except Exception as e:
        logger.error(f"Tax calculation error: {e}")
        return _empty_tax_result(f"Calculation error: {e}")




# ══════════════════════════════════════════════════════════════════════════
# FIFO-BASED TAX CALCULATION (V2)
# ══════════════════════════════════════════════════════════════════════════

def calculate_tax_impact_fifo(
    holding_lots: List[Dict[str, Any]],
    exit_amount_rs: float,
    current_price: float,
) -> Dict[str, Any]:
    """Calculate tax with FIFO logic for partial sells.
    
    Implements Indian tax rules with First-In-First-Out:
    1. Sort lots by buy_date (oldest first)
    2. Calculate gain per lot
    3. Classify as LTCG (> 365 days) or STCG (≤ 365 days)
    4. Apply ₹1L LTCG exemption
    5. Calculate total tax
    
    Args:
        holding_lots: [
            {
                "buy_date": "2023-01-01T00:00:00Z",
                "units": 100,
                "buy_price": 50,
                "lot_id": "lot_1"
            },
            {
                "buy_date": "2023-06-01T00:00:00Z",
                "units": 50,
                "buy_price": 55,
                "lot_id": "lot_2"
            }
        ]
        exit_amount_rs: 5000 (₹ to exit)
        current_price: 60 (current NAV/price)
    
    Returns:
        {
            "ltcg": 2000,
            "stcg": 500,
            "total_gain": 2500,
            "taxable_ltcg": 0,  # After ₹1L exemption
            "ltcg_tax": 0,
            "stcg_tax": 75,
            "total_tax": 75,
            "lot_breakdown": [...],
            "exit_units": 83.33,
            "note": "FIFO applied, ₹1L LTCG exemption available"
        }
    """
    if not holding_lots:
        return _empty_tax_result_fifo("No holding lots provided")
    
    # Sort lots by buy_date (FIFO)
    sorted_lots = sorted(
        holding_lots,
        key=lambda x: datetime.fromisoformat(x["buy_date"].replace('Z', '+00:00'))
    )
    
    remaining_amount = exit_amount_rs
    total_ltcg = 0
    total_stcg = 0
    total_units_sold = 0
    lot_breakdown = []
    
    today = datetime.now(timezone.utc)
    
    for lot in sorted_lots:
        if remaining_amount <= 0:
            break
        
        # Calculate lot value
        lot_units = float(lot["units"])
        lot_buy_price = float(lot["buy_price"])
        lot_current_value = lot_units * current_price
        
        # Determine how much to sell from this lot
        exit_from_lot_rs = min(remaining_amount, lot_current_value)
        exit_from_lot_units = exit_from_lot_rs / current_price
        
        # Calculate gain for this lot
        cost_basis = exit_from_lot_units * lot_buy_price
        gain = exit_from_lot_rs - cost_basis
        buy_date = datetime.fromisoformat(lot["buy_date"].replace('Z', '+00:00'))
        holding_period_days = (today - buy_date).days
        is_lt = is_long_term(holding_period_days)
        
        # Classify gain
        if is_lt:
            total_ltcg += gain
            gain_type = "LTCG"
        else:
            total_stcg += gain
            gain_type = "STCG"
        
        # Track lot breakdown
        lot_breakdown.append({
            "lot_id": lot.get("lot_id", f"lot_{len(lot_breakdown) + 1}"),
            "buy_date": lot["buy_date"],
            "units_sold": round(exit_from_lot_units, 4),
            "buy_price": lot_buy_price,
            "sell_price": current_price,
            "cost_basis": round(cost_basis, 2),
            "exit_value": round(exit_from_lot_rs, 2),
            "gain": round(gain, 2),
            "gain_type": gain_type,
            "holding_period_days": holding_period_days,
        })
        
        remaining_amount -= exit_from_lot_rs
        total_units_sold += exit_from_lot_units
    
    # Apply ₹1L LTCG exemption (note: this is at portfolio level, not per holding)
    # For now, we calculate taxable LTCG assuming exemption is available
    # The actual exemption is applied at portfolio level in calculate_portfolio_tax_fifo()
    taxable_ltcg = max(0, total_ltcg)  # Will subtract exemption at portfolio level
    
    # Calculate tax
    ltcg_tax = taxable_ltcg * LTCG_RATE
    stcg_tax = total_stcg * STCG_RATE if total_stcg > 0 else 0
    total_tax = ltcg_tax + stcg_tax
    
    # Tax score (0-10) for decision engine
    if total_stcg > 0:
        tax_score = 10.0  # STCG = worst
    elif total_ltcg > LTCG_EXEMPTION:
        tax_score = 5.0  # LTCG with tax
    else:
        tax_score = 1.0  # LTCG within exemption
    
    return {
        "ltcg": round(total_ltcg, 2),
        "stcg": round(total_stcg, 2),
        "total_gain": round(total_ltcg + total_stcg, 2),
        "taxable_ltcg": round(taxable_ltcg, 2),
        "ltcg_tax": round(ltcg_tax, 2),
        "stcg_tax": round(stcg_tax, 2),
        "total_tax": round(total_tax, 2),
        "exit_amount_rs": round(exit_amount_rs, 2),
        "exit_units": round(total_units_sold, 4),
        "post_tax_proceeds": round(exit_amount_rs - total_tax, 2),
        "tax_score": round(tax_score, 2),
        "lot_breakdown": lot_breakdown,
        "note": "FIFO applied. ₹1L LTCG exemption to be applied at portfolio level.",
    }


def calculate_portfolio_tax_fifo(
    exit_plan: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """Calculate total tax liability for a planned exit strategy with FIFO.
    
    Aggregates LTCG/STCG across multiple holdings and applies ₹1L exemption.
    
    Args:
        exit_plan: [
            {
                "holding_id": "mf_123",
                "exit_amount_rs": 480000,
                "lots": [...],
                "current_price": 150.5
            },
            ...
        ]
    
    Returns:
        {
            "total_exit_value": 730000,
            "total_ltcg": 130000,
            "total_stcg": 20000,
            "total_gain": 150000,
            "exemption_used": 100000,
            "taxable_ltcg": 30000,
            "ltcg_tax": 3000,
            "stcg_tax": 3000,
            "total_tax": 6000,
            "post_tax_proceeds": 724000,
            "effective_tax_rate": 4.0,  # %
            "breakdown": [...]
        }
    """
    if not exit_plan:
        return _empty_portfolio_tax_fifo("No exit plan provided")
    
    total_exit_value = 0
    total_ltcg = 0
    total_stcg = 0
    breakdown = []
    
    # Calculate tax for each holding
    for plan_item in exit_plan:
        holding_id = plan_item.get("holding_id")
        exit_amount = plan_item.get("exit_amount_rs", 0)
        lots = plan_item.get("lots", [])
        current_price = plan_item.get("current_price", 0)
        
        if not lots or current_price == 0:
            continue
        
        # Calculate FIFO tax for this holding
        tax_result = calculate_tax_impact_fifo(lots, exit_amount, current_price)
        
        total_exit_value += tax_result["exit_amount_rs"]
        total_ltcg += tax_result["ltcg"]
        total_stcg += tax_result["stcg"]
        
        breakdown.append({
            "holding_id": holding_id,
            "holding_name": plan_item.get("holding_name", "Unknown"),
            "exit_amount": tax_result["exit_amount_rs"],
            "ltcg": tax_result["ltcg"],
            "stcg": tax_result["stcg"],
            "total_gain": tax_result["total_gain"],
            "lots_used": len(tax_result["lot_breakdown"]),
        })
    
    # Apply ₹1L LTCG exemption (aggregated across portfolio)
    exemption_used = min(LTCG_EXEMPTION, total_ltcg)
    taxable_ltcg = max(0, total_ltcg - LTCG_EXEMPTION)
    
    # Calculate total tax
    ltcg_tax = taxable_ltcg * LTCG_RATE
    stcg_tax = total_stcg * STCG_RATE if total_stcg > 0 else 0
    total_tax = ltcg_tax + stcg_tax
    
    post_tax_proceeds = total_exit_value - total_tax
    
    # Calculate effective tax rate
    total_gain = total_ltcg + total_stcg
    effective_tax_rate = (total_tax / total_gain * 100) if total_gain > 0 else 0
    
    return {
        "total_exit_value": round(total_exit_value, 2),
        "total_ltcg": round(total_ltcg, 2),
        "total_stcg": round(total_stcg, 2),
        "total_gain": round(total_gain, 2),
        "exemption_used": round(exemption_used, 2),
        "taxable_ltcg": round(taxable_ltcg, 2),
        "ltcg_tax": round(ltcg_tax, 2),
        "stcg_tax": round(stcg_tax, 2),
        "total_tax": round(total_tax, 2),
        "post_tax_proceeds": round(post_tax_proceeds, 2),
        "effective_tax_rate": round(effective_tax_rate, 2),
        "breakdown": breakdown,
        "note": f"₹{exemption_used:,.0f} LTCG exemption applied across portfolio",
    }


def _empty_tax_result_fifo(reason: str) -> Dict[str, Any]:
    """Return empty FIFO tax result with reason."""
    return {
        "ltcg": 0,
        "stcg": 0,
        "total_gain": 0,
        "taxable_ltcg": 0,
        "ltcg_tax": 0,
        "stcg_tax": 0,
        "total_tax": 0,
        "exit_amount_rs": 0,
        "exit_units": 0,
        "post_tax_proceeds": 0,
        "tax_score": 5.0,  # Neutral
        "lot_breakdown": [],
        "note": reason,
        "error": reason,
    }


def _empty_portfolio_tax_fifo(reason: str) -> Dict[str, Any]:
    """Return empty portfolio tax result with reason."""
    return {
        "total_exit_value": 0,
        "total_ltcg": 0,
        "total_stcg": 0,
        "total_gain": 0,
        "exemption_used": 0,
        "taxable_ltcg": 0,
        "ltcg_tax": 0,
        "stcg_tax": 0,
        "total_tax": 0,
        "post_tax_proceeds": 0,
        "effective_tax_rate": 0,
        "breakdown": [],
        "note": reason,
        "error": reason,
    }


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
