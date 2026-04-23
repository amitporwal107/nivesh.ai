"""Portfolio Intelligence Service — legacy risk analysis + recommendations.

Note: `compute_health_score` was removed Feb 2026 — use
`services.portfolio_health.build_portfolio_health(user_id)` instead. It's
the single source of truth for Portfolio Health & Risk (see PRD).
"""
from typing import List
import math


def compute_risk_analysis(holdings: list, current_value: float) -> dict:
    """Detailed risk analysis with warnings and per-factor holdings breakdown."""
    if not holdings or current_value == 0:
        return {"score": 0, "label": "N/A", "concentration_risk": 0, "top_holding_pct": 0, "asset_count": 0, "sector_count": 0, "warnings": [], "risk_factors": []}

    score = _compute_risk_score(holdings, current_value)
    label = "Low" if score < 25 else "Moderate" if score < 50 else "High" if score < 75 else "Very High"

    values = [(h["name"], h["quantity"] * h["current_price"], h) for h in holdings]
    values.sort(key=lambda x: x[1], reverse=True)
    top_pct = (values[0][1] / current_value * 100) if values else 0

    # HHI
    shares = [v / current_value for _, v, _ in values if current_value > 0]
    hhi = sum(s ** 2 for s in shares) if shares else 0

    asset_types = set(h.get("asset_type") for h in holdings)
    sectors = set(h.get("sector", "Other") for h in holdings)

    warnings = []
    risk_factors = []
    
    if top_pct > 20:
        warnings.append(f"Top holding ({values[0][0][:30]}) is {top_pct:.1f}% of portfolio — high concentration risk")
        risk_factors.append({
            "factor": "Concentration Risk",
            "severity": "high" if top_pct > 30 else "medium",
            "description": f"Top holding is {top_pct:.1f}% of portfolio",
            "action_plan": f"Reduce top holding to under 15%. Consider trimming {_fmt(values[0][1] - current_value * 0.15)} from {values[0][0][:30]} and redistributing across 3-5 diversified funds.",
            "holdings": [{"name": n[:40], "value": round(v, 0), "pct": round(v / current_value * 100, 1)} for n, v, _ in values[:5]],
        })
    
    if len(asset_types) < 3:
        warnings.append(f"Only {len(asset_types)} asset types — consider diversifying across equity, debt, gold")
        risk_factors.append({
            "factor": "Low Diversification",
            "severity": "medium",
            "description": f"Only {len(asset_types)} asset types: {', '.join(sorted(asset_types))}",
            "action_plan": "Add 2-3 more asset types. Consider: Debt MFs for stability, Gold ETFs for inflation hedge, and REITs for real estate exposure.",
            "holdings": [],
        })
    
    if hhi > 0.15:
        warnings.append("Portfolio is concentrated in few holdings — spread across more instruments")

    # Check for zero/near-zero holdings
    zero_holdings = [h["name"] for h in holdings if h["quantity"] * h["current_price"] < 10]
    if zero_holdings:
        warnings.append(f"{len(zero_holdings)} holdings with near-zero value — consider cleaning up dead positions")

    # Check equity overweight
    equity_val = sum(h["quantity"] * h["current_price"] for h in holdings if h.get("asset_type") in ("equity", "mutual_fund", "etf"))
    equity_pct = equity_val / current_value * 100 if current_value > 0 else 0
    if equity_pct > 85:
        warnings.append(f"Equity exposure is {equity_pct:.0f}% — consider adding debt/gold for stability")
        target_eq = 75
        excess = equity_val - (current_value * target_eq / 100)
        risk_factors.append({
            "factor": "Equity Overweight",
            "severity": "high" if equity_pct > 90 else "medium",
            "description": f"Equity/MF/ETF is {equity_pct:.0f}% of portfolio. Recommended: 60-80%.",
            "action_plan": f"Reduce equity exposure by {_fmt(excess)}. Move to debt funds ({_fmt(excess * 0.6)}) and gold ({_fmt(excess * 0.4)}) for a balanced 75/15/10 allocation.",
            "holdings": [{"name": h["name"][:40], "value": round(h["quantity"] * h["current_price"], 0), "asset_type": h.get("asset_type")} 
                        for h in sorted(holdings, key=lambda x: x["quantity"] * x["current_price"], reverse=True) 
                        if h.get("asset_type") in ("equity", "mutual_fund", "etf")][:8],
        })

    # Sector concentration check
    sector_map_risk = {}
    for h in holdings:
        sec = h.get("sector", "Other")
        sector_map_risk[sec] = sector_map_risk.get(sec, 0) + h["quantity"] * h["current_price"]
    if sector_map_risk:
        top_sector = max(sector_map_risk, key=sector_map_risk.get)
        top_sector_pct = sector_map_risk[top_sector] / current_value * 100
        if top_sector_pct > 35:
            risk_factors.append({
                "factor": "Sector Concentration",
                "severity": "high" if top_sector_pct > 50 else "medium",
                "description": f"{top_sector} is {top_sector_pct:.0f}% of portfolio",
                "action_plan": f"Reduce {top_sector} exposure to under 25%. Diversify into other sectors like IT, Pharma, Banking, or FMCG to reduce sector-specific risk.",
                "holdings": [{"name": h["name"][:40], "value": round(h["quantity"] * h["current_price"], 0), "sector": h.get("sector")} 
                            for h in holdings if h.get("sector") == top_sector][:5],
            })

    # Regular plan warning
    regular_mfs = [h["name"] for h in holdings if "regular" in h.get("name", "").lower() and h.get("asset_type") == "mutual_fund"]
    if regular_mfs:
        warnings.append(f"{len(regular_mfs)} mutual funds in Regular plans — switch to Direct to save ~1% p.a.")

    return {
        "score": score,
        "label": label,
        "concentration_risk": round(hhi * 100, 1),
        "top_holding_pct": round(top_pct, 1),
        "asset_count": len(asset_types),
        "sector_count": len(sectors),
        "warnings": warnings[:6],
        "risk_factors": risk_factors[:5],
    }


def generate_recommendations(holdings: list, current_value: float, total_invested: float) -> list:
    """Generate rule-based recommendations with specific amounts for actionable insights."""
    if not holdings:
        return []

    recs = []
    asset_map = {}
    for h in holdings:
        at = h.get("asset_type", "other")
        asset_map[at] = asset_map.get(at, 0) + h["quantity"] * h["current_price"]

    equity_val = asset_map.get("equity", 0) + asset_map.get("mutual_fund", 0) + asset_map.get("etf", 0)
    debt_val = asset_map.get("bond", 0) + asset_map.get("fd", 0)
    debt_pct = debt_val / current_value * 100 if current_value > 0 else 0
    gold_val = asset_map.get("gold", 0)
    gold_pct = gold_val / current_value * 100 if current_value > 0 else 0
    mf_val = asset_map.get("mutual_fund", 0)
    mf_pct = mf_val / current_value * 100 if current_value > 0 else 0

    # 1. Regular → Direct switch
    regular_mfs = [h for h in holdings if "regular" in h.get("name", "").lower() and h.get("asset_type") == "mutual_fund"]
    if regular_mfs:
        total_regular = sum(h["quantity"] * h["current_price"] for h in regular_mfs)
        est_savings = total_regular * 0.01
        recs.append({
            "action": "switch",
            "title": f"Switch {len(regular_mfs)} funds to Direct Plans",
            "description": f"You have {len(regular_mfs)} mutual funds in Regular plans worth {_fmt(total_regular)}. Switching to Direct plans could save ~{_fmt(est_savings)}/year in commissions.",
            "priority": "high",
            "impact": f"Save ~{_fmt(est_savings)}/yr",
            "current_pct": round(total_regular / current_value * 100, 1) if current_value > 0 else 0,
            "target_pct": 0,
            "reduce_amount": round(total_regular, 0),
            "add_amount": 0,
            "simulated_savings_1yr": round(est_savings, 0),
        })

    # 2. Clean dead positions
    dead = [h for h in holdings if h["quantity"] * h["current_price"] < 50]
    if dead:
        dead_val = sum(h["quantity"] * h["current_price"] for h in dead)
        recs.append({
            "action": "sell",
            "title": f"Clean up {len(dead)} dead positions",
            "description": f"You have {len(dead)} holdings with near-zero value ({_fmt(dead_val)}). These add noise and complexity. Consider selling or redeeming.",
            "priority": "medium",
            "impact": "Simplify portfolio",
            "reduce_amount": round(dead_val, 0),
            "add_amount": 0,
            "simulated_savings_1yr": 0,
        })

    # 3. Gold overexposure
    if gold_pct > 15:
        target_gold_pct = 12
        excess_gold = gold_val - (current_value * target_gold_pct / 100)
        recs.append({
            "action": "rebalance",
            "title": "Reduce Gold Overexposure",
            "description": f"Gold is {gold_pct:.1f}% of your portfolio ({_fmt(gold_val)}). Recommended range: 10-15%. Reduce by {_fmt(excess_gold)} and redirect to equity or debt for better growth.",
            "priority": "high" if gold_pct > 25 else "medium",
            "impact": f"Reduce by {_fmt(excess_gold)}",
            "current_pct": round(gold_pct, 1),
            "target_pct": target_gold_pct,
            "reduce_amount": round(excess_gold, 0),
            "add_amount": 0,
            "simulated_savings_1yr": round(excess_gold * 0.05, 0),
        })

    # 4. MF overconcentration
    if mf_pct > 40:
        target_mf_pct = 35
        excess_mf = mf_val - (current_value * target_mf_pct / 100)
        recs.append({
            "action": "rebalance",
            "title": "High Mutual Fund Concentration",
            "description": f"MFs are {mf_pct:.1f}% ({_fmt(mf_val)}). Recommended: 30-40%. Reduce by {_fmt(excess_mf)} and diversify into direct equity or ETFs for lower costs.",
            "priority": "medium",
            "impact": f"Reduce by {_fmt(excess_mf)}",
            "current_pct": round(mf_pct, 1),
            "target_pct": target_mf_pct,
            "reduce_amount": round(excess_mf, 0),
            "add_amount": 0,
            "simulated_savings_1yr": round(excess_mf * 0.008, 0),
        })

    # 5. Debt underexposure
    if debt_pct < 10 and current_value > 500000:
        target_debt_pct = 15
        add_debt = (current_value * target_debt_pct / 100) - debt_val
        recs.append({
            "action": "buy",
            "title": "Increase Debt Allocation",
            "description": f"Debt is only {debt_pct:.1f}% ({_fmt(debt_val)}). For stability, allocate 10-20%. Add {_fmt(add_debt)} in debt funds or FDs.",
            "priority": "high" if debt_pct < 5 else "medium",
            "impact": f"Add {_fmt(add_debt)}",
            "current_pct": round(debt_pct, 1),
            "target_pct": target_debt_pct,
            "reduce_amount": 0,
            "add_amount": round(add_debt, 0),
            "simulated_savings_1yr": round(add_debt * 0.07, 0),
        })

    # 6. High expense ratios (Regular plan MFs)
    regular_count = sum(1 for h in holdings if "regular" in h.get("name", "").lower() and h.get("asset_type") == "mutual_fund")
    mf_count = sum(1 for h in holdings if h.get("asset_type") == "mutual_fund")
    if mf_count > 0 and regular_count / mf_count > 0.3:
        avg_extra_expense = 0.018
        total_mf_val = sum(h["quantity"] * h["current_price"] for h in holdings if h.get("asset_type") == "mutual_fund")
        expense_leak = total_mf_val * avg_extra_expense
        recs.append({
            "action": "switch",
            "title": "High Expense Ratios",
            "description": f"{regular_count}/{mf_count} MFs are Regular plans with ~1.8% higher expense ratio. Annual cost leakage: ~{_fmt(expense_leak)}.",
            "priority": "high",
            "impact": f"Save {_fmt(expense_leak)}/yr",
            "current_pct": round(regular_count / mf_count * 100, 0),
            "target_pct": 0,
            "reduce_amount": 0,
            "add_amount": 0,
            "simulated_savings_1yr": round(expense_leak, 0),
        })

    # 7. Top losers
    losers = [(h, ((h["current_price"] - h["buy_price"]) / h["buy_price"] * 100) if h["buy_price"] > 0 else 0) for h in holdings]
    big_losers = [(h, pct) for h, pct in losers if pct < -30 and h["quantity"] * h["buy_price"] > 1000]
    if big_losers:
        names = ", ".join(h["name"][:20] for h, _ in big_losers[:3])
        loss_val = sum(abs(h["quantity"] * (h["current_price"] - h["buy_price"])) for h, _ in big_losers)
        recs.append({
            "action": "sell",
            "title": "Review Deep Loss Positions",
            "description": f"{len(big_losers)} holdings are down >30%: {names}. Total unrealized loss: {_fmt(loss_val)}. Consider tax loss harvesting.",
            "priority": "medium",
            "impact": f"Harvest {_fmt(loss_val * 0.15)} tax",
            "reduce_amount": round(loss_val, 0),
            "add_amount": 0,
            "simulated_savings_1yr": round(loss_val * 0.15, 0),
        })

    return recs[:8]


def simulate_optimized_portfolio(holdings: list, current_value: float, total_invested: float) -> dict:
    """Simulate portfolio if all recommendations are implemented. Returns projected returns."""
    recs = generate_recommendations(holdings, current_value, total_invested)
    if not recs:
        return {"current_returns_pct": 0, "optimized_returns_pct": 0, "additional_returns": 0, "actions": []}

    total_annual_savings = sum(r.get("simulated_savings_1yr", 0) for r in recs)
    current_returns = current_value - total_invested
    current_returns_pct = (current_returns / total_invested * 100) if total_invested > 0 else 0

    # Projected optimized returns = current returns + annual savings from all actions
    optimized_value = current_value + total_annual_savings
    optimized_returns = optimized_value - total_invested
    optimized_returns_pct = (optimized_returns / total_invested * 100) if total_invested > 0 else 0

    # Build ideal allocation
    ideal_allocation = {
        "equity": {"target_pct": 50, "current_pct": 0},
        "mutual_fund": {"target_pct": 25, "current_pct": 0},
        "gold": {"target_pct": 12, "current_pct": 0},
        "debt": {"target_pct": 10, "current_pct": 0},
        "other": {"target_pct": 3, "current_pct": 0},
    }
    asset_map = {}
    for h in holdings:
        at = h.get("asset_type", "other")
        asset_map[at] = asset_map.get(at, 0) + h["quantity"] * h["current_price"]
    for at, val in asset_map.items():
        key = at if at in ideal_allocation else "other"
        if at in ("bond", "fd"):
            key = "debt"
        ideal_allocation.setdefault(key, {"target_pct": 0, "current_pct": 0})
        ideal_allocation[key]["current_pct"] += round(val / current_value * 100, 1) if current_value > 0 else 0

    actions_summary = []
    for r in recs:
        actions_summary.append({
            "title": r["title"],
            "action": r["action"],
            "savings_1yr": r.get("simulated_savings_1yr", 0),
            "reduce": r.get("reduce_amount", 0),
            "add": r.get("add_amount", 0),
        })

    return {
        "current_value": round(current_value, 0),
        "current_returns": round(current_returns, 0),
        "current_returns_pct": round(current_returns_pct, 1),
        "optimized_value_1yr": round(optimized_value, 0),
        "optimized_returns": round(optimized_returns, 0),
        "optimized_returns_pct": round(optimized_returns_pct, 1),
        "additional_returns": round(total_annual_savings, 0),
        "additional_returns_pct": round(total_annual_savings / current_value * 100, 1) if current_value > 0 else 0,
        "actions": actions_summary,
        "ideal_allocation": {k: v for k, v in ideal_allocation.items() if v["current_pct"] > 0 or v["target_pct"] > 0},
    }


def _compute_risk_score(holdings: list, current_value: float) -> int:
    """Raw risk score 0-100 (higher = riskier)."""
    score = 0
    n = len(holdings)

    if n < 3:
        score += 30
    elif n < 5:
        score += 15

    if current_value == 0:
        return score

    # Concentration
    values = [h["quantity"] * h["current_price"] for h in holdings]
    values.sort(reverse=True)
    top_pct = values[0] / current_value * 100 if values else 0
    if top_pct > 30:
        score += 25
    elif top_pct > 20:
        score += 15
    elif top_pct > 10:
        score += 5

    # Sector concentration
    sector_map = {}
    for h in holdings:
        sec = h.get("sector", "Other")
        sector_map[sec] = sector_map.get(sec, 0) + h["quantity"] * h["current_price"]
    if sector_map:
        max_sec = max(sector_map.values()) / current_value * 100
        if max_sec > 50:
            score += 20
        elif max_sec > 30:
            score += 10

    # Equity overweight
    equity_val = sum(h["quantity"] * h["current_price"] for h in holdings if h.get("asset_type") in ("equity", "mutual_fund", "etf"))
    eq_pct = equity_val / current_value * 100
    if eq_pct > 90:
        score += 15
    elif eq_pct > 80:
        score += 8

    return min(100, score)


def _score_to_grade(score: int) -> str:
    if score >= 90:
        return "A+"
    if score >= 80:
        return "A"
    if score >= 70:
        return "B+"
    if score >= 60:
        return "B"
    if score >= 50:
        return "C"
    if score >= 35:
        return "D"
    return "F"


def _fmt(val: float) -> str:
    if abs(val) >= 10000000:
        return f"₹{val / 10000000:.2f} Cr"
    if abs(val) >= 100000:
        return f"₹{val / 100000:.2f} L"
    if abs(val) >= 1000:
        return f"₹{val / 1000:.1f}K"
    return f"₹{val:.0f}"
