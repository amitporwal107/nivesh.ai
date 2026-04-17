"""User profile, onboarding, risk profile routes."""
from fastapi import APIRouter, Request
from datetime import datetime, timezone
import logging

from deps import db, get_current_user
from models import JourneyInput, RiskProfileInput, QuickSetupInput

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


@router.get("/user/profile")
async def get_user_profile(request: Request):
    user = await get_current_user(request)
    profile = await db.user_profiles.find_one({"user_id": user["user_id"]}, {"_id": 0})
    holdings_count = await db.holdings.count_documents({"user_id": user["user_id"]})
    if not profile:
        return {"user_id": user["user_id"], "journey_type": None, "risk_profile": None, "onboarding_completed": False, "has_holdings": holdings_count > 0}
    profile["has_holdings"] = holdings_count > 0
    return profile


@router.post("/user/journey")
async def set_journey(request: Request, body: JourneyInput):
    user = await get_current_user(request)
    now = datetime.now(timezone.utc).isoformat()
    await db.user_profiles.update_one(
        {"user_id": user["user_id"]},
        {"$set": {
            "journey_type": body.journey_type,
            "updated_at": now,
        }, "$setOnInsert": {
            "user_id": user["user_id"],
            "risk_profile": None,
            "onboarding_completed": False,
            "created_at": now,
        }},
        upsert=True
    )
    profile = await db.user_profiles.find_one({"user_id": user["user_id"]}, {"_id": 0})
    return profile


@router.get("/user/risk-profile")
async def get_risk_profile(request: Request):
    user = await get_current_user(request)
    profile = await db.user_profiles.find_one({"user_id": user["user_id"]}, {"_id": 0})
    if not profile or not profile.get("risk_profile"):
        return {"risk_profile": None}
    return {"risk_profile": profile["risk_profile"]}


@router.post("/user/risk-profile")
async def save_risk_profile(request: Request, body: RiskProfileInput):
    user = await get_current_user(request)

    score_map = {
        "market_drop": {"hold": 30, "buy_more": 10, "sell_some": 60, "sell_all": 90},
        "investment_horizon": {"less_1yr": 80, "1_3yr": 60, "3_5yr": 40, "5_10yr": 20, "10yr_plus": 10},
        "loss_tolerance": {"none": 90, "up_to_10": 60, "up_to_25": 35, "up_to_50": 15},
        "income_stability": {"very_stable": 15, "stable": 30, "moderate": 50, "unstable": 75},
        "investment_knowledge": {"beginner": 60, "intermediate": 40, "advanced": 20, "expert": 10},
        "goal_priority": {"safety": 80, "income": 55, "growth": 30, "aggressive_growth": 10},
    }

    total = 0
    count = 0
    answers_dict = {}
    for a in body.answers:
        answers_dict[a.question_id] = a.answer
        if a.question_id in score_map and a.answer in score_map[a.question_id]:
            total += score_map[a.question_id][a.answer]
            count += 1

    risk_score = round(total / count) if count > 0 else 50

    if risk_score <= 25:
        category = "Aggressive"
    elif risk_score <= 45:
        category = "Moderately Aggressive"
    elif risk_score <= 60:
        category = "Moderate"
    elif risk_score <= 75:
        category = "Moderately Conservative"
    else:
        category = "Conservative"

    risk_profile = {
        "score": risk_score,
        "category": category,
        "answers": answers_dict,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }

    now = datetime.now(timezone.utc).isoformat()
    await db.user_profiles.update_one(
        {"user_id": user["user_id"]},
        {"$set": {
            "risk_profile": risk_profile,
            "onboarding_completed": True,
            "updated_at": now,
        }, "$setOnInsert": {
            "user_id": user["user_id"],
            "journey_type": None,
            "created_at": now,
        }},
        upsert=True
    )

    return {"risk_profile": risk_profile}


def _generate_allocation(age: int, risk_appetite: str, horizon: str) -> dict:
    base = {
        "aggressive": {"equity": 80, "debt": 10, "gold": 5, "cash": 5},
        "moderate": {"equity": 60, "debt": 25, "gold": 10, "cash": 5},
        "conservative": {"equity": 30, "debt": 45, "gold": 15, "cash": 10},
    }
    alloc = dict(base.get(risk_appetite, base["moderate"]))
    if age > 30:
        shift = min((age - 30) * 0.5, 25)
        alloc["equity"] -= shift
        alloc["debt"] += shift * 0.7
        alloc["gold"] += shift * 0.2
        alloc["cash"] += shift * 0.1
    elif age < 25:
        boost = min((25 - age) * 1, 10)
        alloc["equity"] = min(alloc["equity"] + boost, 90)
        alloc["debt"] = max(alloc["debt"] - boost, 5)
    h_adj = {"short": -15, "medium": -5, "long": 5, "very_long": 10}
    adj = h_adj.get(horizon, 0)
    alloc["equity"] = max(min(alloc["equity"] + adj, 90), 10)
    alloc["debt"] = max(alloc["debt"] - adj * 0.6, 5)
    alloc["gold"] = max(alloc["gold"] - adj * 0.2, 2)
    alloc["cash"] = max(alloc["cash"] - adj * 0.2, 2)
    total = sum(alloc.values())
    alloc = {k: round(v / total * 100) for k, v in alloc.items()}
    diff = 100 - sum(alloc.values())
    alloc["equity"] += diff
    return alloc


def _generate_fund_recs(alloc: dict, risk_appetite: str) -> list:
    recs = []
    eq = alloc["equity"]
    if eq >= 50:
        recs.append({"category": "Nifty 50 Index Fund", "allocation_pct": round(eq * 0.4), "rationale": "Low-cost broad market exposure"})
        recs.append({"category": "Flexi Cap Fund", "allocation_pct": round(eq * 0.35), "rationale": "Diversified across market capitalizations"})
        recs.append({"category": "Mid Cap Fund", "allocation_pct": eq - round(eq * 0.4) - round(eq * 0.35), "rationale": "Higher growth potential"})
    elif eq >= 25:
        recs.append({"category": "Nifty 50 Index Fund", "allocation_pct": round(eq * 0.5), "rationale": "Stable large-cap exposure"})
        recs.append({"category": "Balanced Advantage Fund", "allocation_pct": eq - round(eq * 0.5), "rationale": "Dynamic equity-debt balance"})
    else:
        recs.append({"category": "Large Cap Index Fund", "allocation_pct": eq, "rationale": "Conservative equity allocation"})
    if alloc["debt"] > 5:
        recs.append({"category": "Short Duration Debt Fund", "allocation_pct": alloc["debt"], "rationale": "Stable returns with low volatility"})
    if alloc["gold"] > 3:
        recs.append({"category": "Sovereign Gold Bond / Gold ETF", "allocation_pct": alloc["gold"], "rationale": "Inflation hedge and portfolio diversifier"})
    if alloc["cash"] > 5:
        recs.append({"category": "Liquid Fund", "allocation_pct": alloc["cash"], "rationale": "High liquidity for emergencies"})
    return recs


@router.post("/user/quick-setup")
async def save_quick_setup(request: Request, body: QuickSetupInput):
    user = await get_current_user(request)
    alloc = _generate_allocation(body.age, body.risk_appetite, body.investment_horizon)
    fund_recs = _generate_fund_recs(alloc, body.risk_appetite)
    expected_return = (alloc["equity"] * 0.12 + alloc["debt"] * 0.07 + alloc["gold"] * 0.08 + alloc["cash"] * 0.04) / 100
    horizon_years = {"short": 3, "medium": 5, "long": 10, "very_long": 20}[body.investment_horizon]
    projection = None
    if body.monthly_investment and body.monthly_investment > 0:
        monthly_rate = expected_return / 12
        months = horizon_years * 12
        fv = body.monthly_investment * (((1 + monthly_rate) ** months - 1) / monthly_rate) * (1 + monthly_rate) if monthly_rate > 0 else body.monthly_investment * months
        projection = {
            "monthly_sip": body.monthly_investment,
            "years": horizon_years,
            "total_invested": round(body.monthly_investment * months),
            "projected_value": round(fv),
            "expected_annual_return": round(expected_return * 100, 1),
        }
    goal_labels = {"retirement": "retirement corpus", "house": "dream home", "education": "education fund", "travel": "travel goals", "wealth": "long-term wealth", "emergency": "emergency fund"}
    goal_label = goal_labels.get(body.goal, "financial goal")
    insights = []
    if body.risk_appetite == "aggressive":
        insights.append(f"Your aggressive risk profile allows higher equity allocation for maximum growth towards your {goal_label}.")
    elif body.risk_appetite == "moderate":
        insights.append(f"A balanced approach with steady growth towards your {goal_label}, mixing equity with stability instruments.")
    else:
        insights.append(f"Capital preservation with measured growth towards your {goal_label}, prioritizing safety.")
    if body.age < 30:
        insights.append("Your young age is your biggest advantage \u2014 time in the market beats timing the market.")
    elif body.age < 45:
        insights.append("At your age, a diversified approach balances growth with emerging responsibilities.")
    else:
        insights.append("Focus on capital preservation while maintaining some growth exposure to beat inflation.")
    if projection:
        insights.append(f"A monthly SIP of \u20b9{body.monthly_investment:,.0f} could grow to approximately \u20b9{projection['projected_value']:,.0f} in {horizon_years} years at ~{projection['expected_annual_return']}% p.a. returns.")
    quick_setup = {"age": body.age, "goal": body.goal, "risk_appetite": body.risk_appetite, "investment_horizon": body.investment_horizon, "monthly_investment": body.monthly_investment}
    starter_plan = {"allocation": alloc, "fund_recommendations": fund_recs, "projection": projection, "insights": insights, "expected_annual_return": round(expected_return * 100, 1), "horizon_years": horizon_years}
    now = datetime.now(timezone.utc).isoformat()
    await db.user_profiles.update_one(
        {"user_id": user["user_id"]},
        {"$set": {"quick_setup": quick_setup, "starter_plan": starter_plan, "updated_at": now},
         "$setOnInsert": {"user_id": user["user_id"], "created_at": now}},
        upsert=True
    )
    return {"quick_setup": quick_setup, "starter_plan": starter_plan}


@router.post("/user/complete-onboarding")
async def complete_onboarding(request: Request):
    user = await get_current_user(request)
    now = datetime.now(timezone.utc).isoformat()
    await db.user_profiles.update_one(
        {"user_id": user["user_id"]},
        {"$set": {"onboarding_completed": True, "updated_at": now}},
        upsert=True
    )
    return {"status": "ok", "onboarding_completed": True}
