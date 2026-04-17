"""AI Insights routes."""
from fastapi import APIRouter, Request
from datetime import datetime, timezone
import uuid
import logging

from deps import db, get_current_user, ai_engine

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


@router.get("/insights")
async def get_insights(request: Request):
    user = await get_current_user(request)
    insights = await db.ai_insights.find(
        {"user_id": user["user_id"]}, {"_id": 0}
    ).sort("created_at", -1).to_list(20)
    return insights


@router.post("/insights/generate")
async def generate_insights(request: Request):
    user = await get_current_user(request)
    user_id = user["user_id"]

    holdings = await db.holdings.find({"user_id": user_id}, {"_id": 0}).to_list(500)
    if not holdings:
        return {"insights": [], "message": "Add holdings to generate insights"}

    total_inv = sum(h["quantity"] * h["buy_price"] for h in holdings)
    total_cur = sum(h["quantity"] * h["current_price"] for h in holdings)

    asset_map = {}
    sector_map = {}
    mf_names = []
    for h in holdings:
        cur = h["quantity"] * h["current_price"]
        at = h.get("asset_type", "other")
        asset_map[at] = asset_map.get(at, 0) + cur
        sec = h.get("sector", "Other")
        sector_map[sec] = sector_map.get(sec, 0) + cur
        if at == "mutual_fund":
            mf_names.append(h["name"])

    portfolio_text = f"Portfolio: \u20b9{total_inv:,.0f} invested, \u20b9{total_cur:,.0f} current ({((total_cur-total_inv)/total_inv*100) if total_inv > 0 else 0:.1f}% returns).\n"
    portfolio_text += f"Asset split: {', '.join(f'{k}={v/total_cur*100:.1f}%' for k,v in asset_map.items() if total_cur > 0)}\n"
    portfolio_text += f"Sectors: {', '.join(f'{k}={v/total_cur*100:.1f}%' for k,v in list(sector_map.items())[:10] if total_cur > 0)}\n"
    portfolio_text += f"Holdings ({len(holdings)}):\n"
    for h in holdings[:60]:
        ret_pct = ((h["current_price"] - h["buy_price"]) / h["buy_price"] * 100) if h["buy_price"] > 0 else 0
        portfolio_text += f"- {h['name']} ({h['asset_type']}, {h.get('sector','N/A')}): qty={h['quantity']}, \u20b9{h['buy_price']}->\u20b9{h['current_price']} ({ret_pct:.1f}%)\n"

    try:
        analysis = await ai_engine.analyze_portfolio(
            portfolio_text,
            f"insights_{user_id}_{uuid.uuid4().hex[:6]}"
        )
    except Exception as e:
        logger.error(f"Insights generation error: {e}")
        analysis = {
            "insights": [{"title": "Analysis Error", "description": "Could not generate insights. Try again.", "type": "info", "impact": "medium", "effort": "low", "category": "info", "current_value": "", "target_value": "", "progress": 0}],
            "problem_distribution": [],
            "before_after": {"before": {"return_pct": 0, "risk_label": "N/A", "risk_score": 0, "expense_ratio": 0}, "after": {"return_pct": 0, "risk_label": "N/A", "risk_score": 0, "expense_ratio": 0}},
            "action_funnel": [],
            "overlap_pairs": [],
            "cost_leakage": {"annual_loss": 0, "total_invested": 0, "loss_pct": 0, "detail": ""},
            "risk_gauge": {"current": 0, "target": 0, "current_label": "N/A", "target_label": "N/A"}
        }

    # Save insights
    await db.ai_insights.delete_many({"user_id": user_id})
    saved_insights = []
    for insight in analysis.get("insights", []):
        doc = {
            "insight_id": f"ins_{uuid.uuid4().hex[:12]}",
            "user_id": user_id,
            "title": insight.get("title", ""),
            "description": insight.get("description", ""),
            "type": insight.get("type", "info"),
            "priority": insight.get("impact", "medium"),
            "impact": insight.get("impact", "medium"),
            "effort": insight.get("effort", "medium"),
            "category": insight.get("category", "info"),
            "current_value": insight.get("current_value", ""),
            "target_value": insight.get("target_value", ""),
            "progress": insight.get("progress", 0),
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        await db.ai_insights.insert_one(doc)
        saved_insights.append({k: v for k, v in doc.items() if k != "_id"})

    analysis["insights"] = saved_insights
    await db.portfolio_analysis.delete_many({"user_id": user_id})
    await db.portfolio_analysis.insert_one({
        "user_id": user_id,
        "analysis": analysis,
        "created_at": datetime.now(timezone.utc).isoformat()
    })

    return analysis


@router.get("/insights/analysis")
async def get_analysis(request: Request):
    """Get the full portfolio analysis."""
    user = await get_current_user(request)
    doc = await db.portfolio_analysis.find_one({"user_id": user["user_id"]}, {"_id": 0})
    if doc and "analysis" in doc:
        return doc["analysis"]
    return None
