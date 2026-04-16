"""Portfolio Intelligence Service — health score, risk analysis, recommendations."""
from typing import List
import math


def compute_health_score(holdings: list, total_invested: float, current_value: float) -> dict:
    """Compute composite portfolio health score (0-100) with breakdown."""
    if not holdings or total_invested == 0:
        return {"diversification": 0, "risk": 0, "cost_efficiency": 0, "performance": 0, "overall": 0, "grade": "N/A"}

    returns_pct = ((current_value - total_invested) / total_invested * 100) if total_invested > 0 else 0

    # ── Diversification Score (0-100) ──
    asset_types = set(h.get("asset_type") for h in holdings)
    sectors = set(h.get("sector", "Other") for h in holdings)
    values = [h["quantity"] * h["current_price"] for h in holdings if h["quantity"] * h["current_price"] > 0]

    # HHI (Herfindahl-Hirschman Index) for concentration
    if values and current_value > 0:
        shares = [v / current_value for v in values]
        hhi = sum(s ** 2 for s in shares)
        hhi_score = max(0, min(100, int((1 - hhi) * 120)))  # Lower HHI = better diversification
    else:
        hhi_score = 0

    asset_type_score = min(100, len(asset_types) * 25)  # Up to 4 types = 100
    sector_score = min(100, len(sectors) * 12)  # Up to ~8 sectors = 100
    diversification = int((hhi_score * 0.5 + asset_type_score * 0.25 + sector_score * 0.25))

    # ── Risk Score (inverted — lower risk = higher score) ──
    risk_raw = _compute_risk_score(holdings, current_value)
    risk_score = max(0, 100 - risk_raw)

    # ── Cost Efficiency (0-100) ──
    # Penalize regular plans, high expense ratios (proxy: mutual funds that are "Regular")
    regular_count = sum(1 for h in holdings if "regular" in h.get("name", "").lower() and h.get("asset_type") == "mutual_fund")
    mf_count = sum(1 for h in holdings if h.get("asset_type") == "mutual_fund")
    if mf_count > 0:
        direct_ratio = 1 - (regular_count / mf_count)
        cost_efficiency = int(direct_ratio * 80 + 20)  # Baseline 20
    else:
        cost_efficiency = 80  # No MFs = decent by default

    # ── Performance Score (0-100) ──
    if returns_pct >= 15:
        performance = 95
    elif returns_pct >= 10:
        performance = 80
    elif returns_pct >= 5:
        performance = 65
    elif returns_pct >= 0:
        performance = 50
    elif returns_pct >= -5:
        performance = 35
    else:
        performance = max(10, 35 + int(returns_pct * 2))

    overall = int(diversification * 0.30 + risk_score * 0.25 + cost_efficiency * 0.20 + performance * 0.25)
    overall = max(0, min(100, overall))

    grade = _score_to_grade(overall)

    return {
        "diversification": diversification,
        "risk": risk_score,
        "cost_efficiency": cost_efficiency,
        "performance": performance,
        "overall": overall,
        "grade": grade,
    }


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
        # Add top 5 holdings as risk factor detail
        risk_factors.append({
            "factor": "Concentration Risk",
            "severity": "high" if top_pct > 30 else "medium",
            "description": f"Top holding is {top_pct:.1f}% of portfolio",
            "holdings": [{"name": n[:40], "value": round(v, 0), "pct": round(v / current_value * 100, 1)} for n, v, _ in values[:5]],
        })
    
    if len(asset_types) < 3:
        warnings.append(f"Only {len(asset_types)} asset types — consider diversifying across equity, debt, gold")
        risk_factors.append({
            "factor": "Low Diversification",
            "severity": "medium",
            "description": f"Only {len(asset_types)} asset types: {', '.join(sorted(asset_types))}",
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
        risk_factors.append({
            "factor": "Equity Overweight",
            "severity": "high" if equity_pct > 90 else "medium",
            "description": f"Equity/MF/ETF is {equity_pct:.0f}% of portfolio. Recommended: 60-80%.",
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
    """Generate rule-based recommendations."""
    if not holdings:
        return []

    recs = []
    asset_map = {}
    for h in holdings:
        at = h.get("asset_type", "other")
        asset_map[at] = asset_map.get(at, 0) + h["quantity"] * h["current_price"]

    # 1. Regular → Direct switch
    regular_mfs = [h for h in holdings if "regular" in h.get("name", "").lower() and h.get("asset_type") == "mutual_fund"]
    if regular_mfs:
        total_regular = sum(h["quantity"] * h["current_price"] for h in regular_mfs)
        est_savings = total_regular * 0.01  # ~1% expense savings
        recs.append({
            "action": "switch",
            "title": f"Switch {len(regular_mfs)} funds to Direct Plans",
            "description": f"You have {len(regular_mfs)} mutual funds in Regular plans worth {_fmt(total_regular)}. Switching to Direct plans could save ~{_fmt(est_savings)}/year in commissions.",
            "priority": "high",
            "impact": f"Save ~{_fmt(est_savings)}/yr",
        })

    # 2. Clean dead positions
    dead = [h for h in holdings if h["quantity"] * h["current_price"] < 50]
    if dead:
        recs.append({
            "action": "sell",
            "title": f"Clean up {len(dead)} dead positions",
            "description": f"You have {len(dead)} holdings with near-zero value. These add noise and complexity. Consider selling or redeeming.",
            "priority": "medium",
            "impact": "Simplify portfolio",
        })

    # 3. Asset allocation
    debt_pct = (asset_map.get("bond", 0) + asset_map.get("fd", 0)) / current_value * 100 if current_value > 0 else 0
    gold_pct = asset_map.get("gold", 0) / current_value * 100 if current_value > 0 else 0

    if debt_pct < 10 and current_value > 500000:
        recs.append({
            "action": "buy",
            "title": "Increase debt allocation",
            "description": f"Debt is only {debt_pct:.1f}% of your portfolio. For a balanced portfolio, consider allocating 10-20% to debt funds or FDs for stability.",
            "priority": "high" if debt_pct < 5 else "medium",
            "impact": "Reduce volatility",
        })

    if gold_pct > 20:
        recs.append({
            "action": "rebalance",
            "title": "Reduce gold overweight",
            "description": f"Gold is {gold_pct:.1f}% of your portfolio. Consider capping at 10-15% and redirecting to equity/debt.",
            "priority": "medium",
            "impact": "Better long-term returns",
        })

    # 4. Top losers
    losers = [(h, ((h["current_price"] - h["buy_price"]) / h["buy_price"] * 100) if h["buy_price"] > 0 else 0) for h in holdings]
    big_losers = [(h, pct) for h, pct in losers if pct < -30 and h["quantity"] * h["buy_price"] > 1000]
    if big_losers:
        names = ", ".join(h["name"][:20] for h, _ in big_losers[:3])
        recs.append({
            "action": "sell",
            "title": "Review deep loss positions",
            "description": f"{len(big_losers)} holdings are down >30%: {names}. Evaluate if the thesis still holds or book losses for tax harvesting.",
            "priority": "medium",
            "impact": "Tax loss harvesting",
        })

    return recs[:8]


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
