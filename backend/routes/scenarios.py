"""AI Copilot Scenario Engine — Phase 1 MVP.

Endpoints:
 - GET  /api/scenarios/suggest   → AI-picked 3-4 personalized scenario cards
 - POST /api/scenarios/simulate  → Before/After metrics for target allocation
"""
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
import json
import logging

from deps import db, get_current_user, ai_engine
from helpers.portfolio_utils import extract_fund_house

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


# ─── Static return assumptions (per PRD Phase 1 decision) ────────────────
ASSUMED_CAGR = {
    "equity": 12.0,
    "mutual_fund": 11.5,   # mixed average
    "etf": 11.0,
    "debt": 7.0,
    "gold": 8.0,
    "hybrid": 10.0,
    "cash": 6.0,
    "other": 8.0,
}

# Expense ratio assumption (regular vs direct)
REGULAR_EXPENSE = 1.8
DIRECT_EXPENSE = 0.8


# ─── Helpers ─────────────────────────────────────────────────────────────
def _compute_portfolio_context(holdings: List[Dict]) -> Dict[str, Any]:
    """Deterministic portfolio metrics used for both suggest + simulate."""
    total = sum(h["quantity"] * h["current_price"] for h in holdings) or 1
    invested = sum(h["quantity"] * h["buy_price"] for h in holdings) or 1

    asset_map: Dict[str, float] = {}
    amc_map: Dict[str, float] = {}
    regular_value = 0.0
    dead_positions: List[Dict] = []

    for h in holdings:
        val = h["quantity"] * h["current_price"]
        at = h.get("asset_type", "other")
        asset_map[at] = asset_map.get(at, 0) + val

        if at in ("mutual_fund", "etf"):
            fh = extract_fund_house(h["name"])
            amc_map[fh] = amc_map.get(fh, 0) + val
            name_lower = h["name"].lower()
            if "regular" in name_lower and "direct" not in name_lower:
                regular_value += val

        # "Dead position" = tiny value, < ₹500
        if val < 500:
            dead_positions.append({"name": h["name"][:40], "value": round(val, 2)})

    asset_pct = {k: round(v / total * 100, 1) for k, v in asset_map.items()}
    top_amc = max(amc_map.items(), key=lambda x: x[1]) if amc_map else ("", 0)
    top_amc_pct = round(top_amc[1] / total * 100, 1) if total else 0

    # Cost leakage: regular plans pay ~1% more/yr vs direct
    annual_cost_leak = round(regular_value * (REGULAR_EXPENSE - DIRECT_EXPENSE) / 100)

    # Deterministic risk score (0-100) based on concentration + missing debt
    equity_pct = asset_pct.get("equity", 0) + asset_pct.get("mutual_fund", 0) + asset_pct.get("etf", 0)
    debt_pct = asset_pct.get("debt", 0)
    risk_score = min(100, int(equity_pct * 0.6 + top_amc_pct * 0.5 + (100 if debt_pct < 5 else 0) * 0.2))

    return {
        "total_value": round(total),
        "total_invested": round(invested),
        "asset_pct": asset_pct,
        "equity_pct": round(equity_pct, 1),
        "debt_pct": round(debt_pct, 1),
        "top_amc": top_amc[0],
        "top_amc_pct": top_amc_pct,
        "regular_plan_value": round(regular_value),
        "annual_cost_leak": annual_cost_leak,
        "dead_position_count": len(dead_positions),
        "dead_position_value": round(sum(d["value"] for d in dead_positions)),
        "risk_score": risk_score,
        "holdings_count": len(holdings),
    }


def _risk_label(score: int) -> str:
    if score >= 75:
        return "High"
    if score >= 50:
        return "Moderate"
    if score >= 25:
        return "Low-Moderate"
    return "Low"


# ─── /scenarios/suggest ──────────────────────────────────────────────────
@router.get("/scenarios/suggest")
async def suggest_scenarios(request: Request):
    """Generate 3-4 personalized scenario cards based on portfolio context."""
    user = await get_current_user(request)
    holdings = await db.holdings.find({"user_id": user["user_id"]}, {"_id": 0}).to_list(500)
    if not holdings:
        return {"scenarios": [], "context": None}

    ctx = _compute_portfolio_context(holdings)

    # Deterministic candidate scenarios based on flags
    candidates: List[Dict] = []

    if ctx["debt_pct"] < 10:
        target_debt = 15 if ctx["equity_pct"] > 80 else 10
        candidates.append({
            "id": "add_debt",
            "title": "Add Debt Allocation",
            "subtitle": "Lower volatility, preserve capital",
            "category": "risk",
            "icon": "shield",
            "current_value": f"{ctx['debt_pct']}%",
            "target_value": f"{target_debt}%",
            "target_allocation": {
                "equity": max(0, 100 - target_debt - ctx["asset_pct"].get("gold", 0)),
                "debt": target_debt,
                "gold": ctx["asset_pct"].get("gold", 0),
            },
            "impact": {"risk": -18, "stability": "up", "return": "neutral"},
            "reason": f"Your portfolio has only {ctx['debt_pct']}% in debt. Adding 15% debt will reduce volatility meaningfully with minimal return impact.",
            "recommended": True,
        })

    if ctx["top_amc_pct"] > 25 and ctx["top_amc"]:
        candidates.append({
            "id": "reduce_top_amc",
            "title": f"Reduce {ctx['top_amc']} Exposure",
            "subtitle": "Diversify across fund houses",
            "category": "allocation",
            "icon": "pie",
            "current_value": f"{ctx['top_amc_pct']}%",
            "target_value": "20%",
            "target_allocation": {"amc_cap": 20},
            "impact": {"diversification": "up", "concentration_risk": "down", "return": "neutral"},
            "reason": f"{ctx['top_amc']} makes up {ctx['top_amc_pct']}% of your portfolio. Capping at 20% reduces single-AMC risk.",
            "recommended": ctx["top_amc_pct"] > 35,
        })

    if ctx["annual_cost_leak"] > 5000:
        candidates.append({
            "id": "switch_to_direct",
            "title": "Switch to Direct Plans",
            "subtitle": f"Save ₹{ctx['annual_cost_leak']:,}/yr in costs",
            "category": "cost",
            "icon": "savings",
            "current_value": f"₹{ctx['regular_plan_value']:,} in Regular",
            "target_value": "₹0 in Regular",
            "target_allocation": {"plan_type": "direct"},
            "impact": {"cost_saving": ctx["annual_cost_leak"], "return": "+1.0%", "risk": "neutral"},
            "reason": f"Regular plans charge ~1% extra vs Direct. Switching saves ~₹{ctx['annual_cost_leak']:,}/yr and compounds meaningfully.",
            "recommended": True,
        })

    if ctx["dead_position_count"] >= 3:
        candidates.append({
            "id": "clean_dead_positions",
            "title": f"Clean {ctx['dead_position_count']} Dead Positions",
            "subtitle": "Simplify portfolio tracking",
            "category": "optimization",
            "icon": "broom",
            "current_value": f"{ctx['dead_position_count']} tiny holdings",
            "target_value": "0 dead positions",
            "target_allocation": {"remove_dead": True},
            "impact": {"simplification": "up", "return": "neutral"},
            "reason": f"{ctx['dead_position_count']} holdings below ₹500 (total ₹{ctx['dead_position_value']}) clutter reports without meaningful return.",
            "recommended": False,
        })

    # Small-cap reduction
    small_cap_pct = ctx["asset_pct"].get("small_cap", 0)
    if small_cap_pct > 20:
        candidates.append({
            "id": "reduce_small_cap",
            "title": "Reduce Small Cap Risk",
            "subtitle": "Lower drawdown in corrections",
            "category": "risk",
            "icon": "trending-down",
            "current_value": f"{small_cap_pct}%",
            "target_value": "15%",
            "target_allocation": {"small_cap": 15},
            "impact": {"risk": -12, "return": "-0.8%"},
            "reason": f"Small-cap at {small_cap_pct}% amplifies drawdowns. Capping at 15% preserves upside with less volatility.",
            "recommended": False,
        })

    # Take top 4 — prioritize recommended
    candidates.sort(key=lambda x: (not x.get("recommended"), x["id"]))
    scenarios = candidates[:4]

    return {"scenarios": scenarios, "context": ctx}


# ─── /scenarios/simulate ─────────────────────────────────────────────────
class SimulateRequest(BaseModel):
    scenario_id: Optional[str] = None
    # Target allocation overrides (any subset)
    target_equity: Optional[float] = None
    target_debt: Optional[float] = None
    target_gold: Optional[float] = None
    target_amc_cap: Optional[float] = None
    target_small_cap: Optional[float] = None
    switch_to_direct: bool = False
    remove_dead: bool = False


@router.post("/scenarios/simulate")
async def simulate_scenario(payload: SimulateRequest, request: Request):
    """Run a what-if simulation and return Before/After metrics."""
    user = await get_current_user(request)
    holdings = await db.holdings.find({"user_id": user["user_id"]}, {"_id": 0}).to_list(500)
    if not holdings:
        raise HTTPException(status_code=400, detail="No holdings to simulate")

    before = _compute_portfolio_context(holdings)

    # Build "after" by applying target allocations deterministically
    # Weighted CAGR — BEFORE
    before_cagr = 0.0
    for at, pct in before["asset_pct"].items():
        before_cagr += (pct / 100) * ASSUMED_CAGR.get(at, 8.0)

    # Determine target allocation
    after_alloc = dict(before["asset_pct"])  # start from current

    if payload.target_debt is not None and payload.target_equity is not None:
        after_alloc = {
            "equity": payload.target_equity,
            "debt": payload.target_debt,
            "gold": payload.target_gold or after_alloc.get("gold", 0),
        }
        # Normalize if not 100
        total_pct = sum(after_alloc.values())
        if total_pct > 0:
            after_alloc = {k: round(v * 100 / total_pct, 1) for k, v in after_alloc.items()}
    elif payload.target_debt is not None:
        # Pull from equity
        delta = payload.target_debt - after_alloc.get("debt", 0)
        after_alloc["debt"] = payload.target_debt
        after_alloc["equity"] = max(0, after_alloc.get("equity", 0) - delta)
    elif payload.target_small_cap is not None:
        # Adjust small cap within equity
        cur = after_alloc.get("small_cap", 0)
        delta = payload.target_small_cap - cur
        after_alloc["small_cap"] = payload.target_small_cap
        after_alloc["equity"] = max(0, after_alloc.get("equity", 0) - delta)

    # Weighted CAGR — AFTER
    after_cagr = 0.0
    for at, pct in after_alloc.items():
        after_cagr += (pct / 100) * ASSUMED_CAGR.get(at, 8.0)

    # Risk score after
    after_equity = after_alloc.get("equity", 0) + after_alloc.get("mutual_fund", 0) + after_alloc.get("etf", 0)
    after_debt = after_alloc.get("debt", 0)
    after_amc_cap = payload.target_amc_cap or before["top_amc_pct"]
    after_risk = min(100, int(after_equity * 0.6 + after_amc_cap * 0.5 + (100 if after_debt < 5 else 0) * 0.2))

    # Cost savings
    cost_saving = 0
    after_cost_leak = before["annual_cost_leak"]
    if payload.switch_to_direct:
        cost_saving = before["annual_cost_leak"]
        after_cost_leak = 0
        after_cagr += 1.0  # ~1% direct plan uplift

    # Portfolio value after 5 years (projection)
    def _projected_value(principal: float, cagr: float, years: int = 5) -> float:
        return principal * ((1 + cagr / 100) ** years)

    before_5y = _projected_value(before["total_value"], before_cagr)
    after_5y = _projected_value(before["total_value"], after_cagr)

    result = {
        "before": {
            "equity_pct": before["equity_pct"],
            "debt_pct": before["debt_pct"],
            "risk_score": before["risk_score"],
            "risk_label": _risk_label(before["risk_score"]),
            "expected_cagr": round(before_cagr, 2),
            "top_amc_pct": before["top_amc_pct"],
            "annual_cost": before["annual_cost_leak"],
            "projected_5y": round(before_5y),
        },
        "after": {
            "equity_pct": round(after_alloc.get("equity", 0), 1),
            "debt_pct": round(after_alloc.get("debt", 0), 1),
            "gold_pct": round(after_alloc.get("gold", 0), 1),
            "risk_score": after_risk,
            "risk_label": _risk_label(after_risk),
            "expected_cagr": round(after_cagr, 2),
            "top_amc_pct": round(after_amc_cap, 1),
            "annual_cost": after_cost_leak,
            "projected_5y": round(after_5y),
        },
        "delta": {
            "risk": after_risk - before["risk_score"],
            "cagr": round(after_cagr - before_cagr, 2),
            "cost_saving_yearly": cost_saving,
            "value_5y": round(after_5y - before_5y),
        },
        "top_changes": _build_top_changes(payload, before, after_alloc, cost_saving),
        "scenario_id": payload.scenario_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    # Persist
    await db.scenario_simulations.insert_one({
        "user_id": user["user_id"],
        "scenario_id": payload.scenario_id,
        "payload": payload.dict(),
        "result": result,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })

    return result


def _build_top_changes(payload: SimulateRequest, before: Dict, after: Dict, cost_saving: int) -> List[str]:
    changes: List[str] = []
    if payload.target_debt is not None and payload.target_debt != before["debt_pct"]:
        changes.append(f"Debt: {before['debt_pct']}% → {after.get('debt', 0)}%")
    if payload.target_equity is not None and payload.target_equity != before["equity_pct"]:
        changes.append(f"Equity: {before['equity_pct']}% → {after.get('equity', 0)}%")
    if payload.target_amc_cap is not None:
        changes.append(f"Top AMC cap: {before['top_amc_pct']}% → {payload.target_amc_cap}%")
    if payload.switch_to_direct:
        changes.append(f"Switched Regular → Direct (save ₹{cost_saving:,}/yr)")
    if payload.remove_dead and before["dead_position_count"]:
        changes.append(f"Cleaned {before['dead_position_count']} dead positions")
    if not changes:
        changes.append("No changes applied")
    return changes
