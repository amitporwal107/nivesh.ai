"""AI Insights routes — Enhanced with full portfolio context."""
from fastapi import APIRouter, Request
from datetime import datetime, timezone
import uuid
import json
import logging

from deps import db, get_current_user, ai_engine
from services.equity_sectors import enrich_holdings_with_sectors
from helpers.portfolio_utils import extract_fund_house

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


@router.get("/insights")
async def get_insights(request: Request):
    user = await get_current_user(request)
    insights = await db.ai_insights.find(
        {"user_id": user["user_id"]}, {"_id": 0}
    ).sort("created_at", -1).to_list(20)
    return insights


def _build_comprehensive_prompt(holdings, deep_analytics, allocation_data):
    """Build a comprehensive data-driven prompt for OpenAI insights generation.
    Only includes actual portfolio data — NO assumptions or hallucinations."""

    total_inv = sum(h["quantity"] * h["buy_price"] for h in holdings)
    total_cur = sum(h["quantity"] * h["current_price"] for h in holdings)
    returns_pct = ((total_cur - total_inv) / total_inv * 100) if total_inv > 0 else 0

    # Asset allocation
    asset_map = {}
    sector_map = {}
    fund_house_map = {}
    regular_plans = []
    direct_plans = []
    equity_holdings = []
    mf_holdings = []

    for h in holdings:
        val = h["quantity"] * h["current_price"]
        inv = h["quantity"] * h["buy_price"]
        at = h.get("asset_type", "other")
        asset_map[at] = asset_map.get(at, 0) + val

        sec = h.get("sector", "Other")
        sector_map[sec] = sector_map.get(sec, 0) + val

        if at in ("mutual_fund", "etf"):
            name_lower = h["name"].lower()
            fh = extract_fund_house(h["name"])
            fund_house_map.setdefault(fh, {"value": 0, "count": 0, "funds": []})
            fund_house_map[fh]["value"] += val
            fund_house_map[fh]["count"] += 1
            fund_house_map[fh]["funds"].append(h["name"][:40])

            if "regular" in name_lower and "direct" not in name_lower:
                regular_plans.append({"name": h["name"][:50], "value": round(val), "return_pct": round(((h["current_price"] - h["buy_price"]) / h["buy_price"] * 100) if h["buy_price"] > 0 else 0, 1)})
            elif "direct" in name_lower:
                direct_plans.append(h["name"][:50])

            mf_holdings.append({"name": h["name"][:50], "sector": sec, "value": round(val), "invested": round(inv)})
        elif at == "equity":
            ret = ((h["current_price"] - h["buy_price"]) / h["buy_price"] * 100) if h["buy_price"] > 0 else 0
            equity_holdings.append({"name": h["name"][:40], "sector": sec, "value": round(val), "return_pct": round(ret, 1)})

    # Build prompt sections
    prompt = f"""=== PORTFOLIO SUMMARY (ALL DATA FROM USER'S ACTUAL HOLDINGS) ===
Total Invested: ₹{total_inv:,.0f}
Current Value: ₹{total_cur:,.0f}
Returns: {returns_pct:.1f}%
Total Holdings: {len(holdings)}

=== ASSET ALLOCATION ===
"""
    for at, val in sorted(asset_map.items(), key=lambda x: -x[1]):
        pct = val / total_cur * 100 if total_cur > 0 else 0
        prompt += f"- {at}: ₹{val:,.0f} ({pct:.1f}%)\n"

    # Ideal ranges
    prompt += """
=== IDEAL ALLOCATION RANGES (SEBI/industry standard) ===
- Equity (direct stocks): 20-40% for moderate risk
- Mutual Funds: 30-60%
- Debt/Bonds: 10-25% (CRITICAL for stability)
- Gold: 5-10% (hedge, NOT core holding)
- Cash/Liquid: 5-10% (emergency)

=== SECTOR EXPOSURE ===
"""
    for sec, val in sorted(sector_map.items(), key=lambda x: -x[1])[:12]:
        pct = val / total_cur * 100 if total_cur > 0 else 0
        prompt += f"- {sec}: ₹{val:,.0f} ({pct:.1f}%)\n"

    # Fund house concentration
    prompt += "\n=== FUND HOUSE (AMC) CONCENTRATION ===\n"
    for fh, data in sorted(fund_house_map.items(), key=lambda x: -x[1]["value"])[:8]:
        pct = data["value"] / total_cur * 100 if total_cur > 0 else 0
        prompt += f"- {fh}: {data['count']} funds, ₹{data['value']:,.0f} ({pct:.1f}%) — funds: {', '.join(data['funds'][:3])}\n"
    prompt += "IDEAL: No single AMC >25% of portfolio\n"

    # Regular vs Direct
    if regular_plans:
        prompt += "\n=== REGULAR PLANS (HIGHER EXPENSE RATIO ~1-2% vs Direct ~0.3-1%) ===\n"
        prompt += f"Count: {len(regular_plans)} regular plan funds\n"
        total_regular = sum(r["value"] for r in regular_plans)
        prompt += f"Total in regular plans: ₹{total_regular:,.0f}\n"
        prompt += f"Estimated annual cost leakage: ₹{total_regular * 0.01:,.0f} (assuming 1% extra expense ratio)\n"
        for r in regular_plans[:5]:
            prompt += f"- {r['name']}: ₹{r['value']:,} ({r['return_pct']}%)\n"

    # Overexposure from deep analytics
    if deep_analytics:
        dup = deep_analytics.get("duplication", {})
        if dup.get("score"):
            prompt += "\n=== FUND OVERLAP / DUPLICATION ===\n"
            prompt += f"Duplication Score: {dup['score']}% ({dup['level']})\n"
            prompt += f"Overlapping allocation: ₹{dup.get('overlapping_value', 0):,.0f}\n"
            for cat in (dup.get("category_detail") or [])[:5]:
                if cat["fund_count"] >= 2:
                    prompt += f"- {cat['category']}: {cat['fund_count']} funds (overlap: ₹{cat.get('overlap_value', 0):,.0f})\n"

        overlaps = deep_analytics.get("overlap_matrix", [])
        if overlaps:
            prompt += "\nTop fund-to-fund overlaps:\n"
            for o in overlaps[:5]:
                prompt += f"- {o['fund_a'][:30]} ↔ {o['fund_b'][:30]}: {o['overlap_pct']}%\n"

    # AI allocation analysis (true sector/company exposure)
    if allocation_data and not allocation_data.get("error"):
        prompt += "\n=== AI LOOK-THROUGH ANALYSIS (True underlying exposure) ===\n"
        for sec in (allocation_data.get("top_5_sectors") or [])[:5]:
            prompt += f"- {sec['sector']}: {sec['weight']*100:.1f}%\n"
        for comp in (allocation_data.get("top_10_companies") or [])[:5]:
            prompt += f"- Company: {comp['name']} at {comp['weight']*100:.1f}% ({comp.get('sector','')})\n"
        for flag in (allocation_data.get("concentration_flags") or []):
            prompt += f"- FLAG: {flag['name']} ({flag['type']}) at {flag['weight']*100:.1f}% — threshold: {flag['threshold']*100}%\n"

    # Equity detail
    if equity_holdings:
        prompt += f"\n=== DIRECT EQUITY ({len(equity_holdings)} stocks) ===\n"
        for e in sorted(equity_holdings, key=lambda x: -abs(x["value"]))[:10]:
            prompt += f"- {e['name']} ({e['sector']}): ₹{e['value']:,} ({e['return_pct']}%)\n"

    return prompt


ENHANCED_INSIGHT_SYSTEM = """You are a SEBI-compliant Indian portfolio analysis engine. Generate data-driven insights.

CRITICAL RULES:
1. ONLY use data provided in the input. NEVER hallucinate or guess.
2. Every insight MUST cite specific numbers (₹ amounts, percentages, fund names)
3. Include ideal ranges and thresholds for context
4. If data is missing, say "Data not available" — do NOT estimate
5. Cover ALL of: overexposure, overlap, cost leakage, risk concentration, allocation gaps

Output STRICT JSON:
{
  "insights": [
    {
      "title": "Short title",
      "description": "Detailed explanation with numbers. WHY this is an issue, WHAT the ideal range is, WHICH holdings are affected, HOW MUCH to reduce/increase",
      "type": "warning|opportunity|info",
      "impact": "high|medium|low",
      "effort": "low|medium|high",
      "category": "risk|allocation|cost|overlap|performance",
      "current_value": "Current state with number",
      "target_value": "Ideal state with number",
      "affected_funds": ["Fund Name 1", "Fund Name 2"],
      "action": "Specific action: 'Reduce X by Y%' or 'Switch from A to B'"
    }
  ],
  "problem_distribution": [
    {"name": "High Risk", "value": 0, "color": "#EF4444", "reason": "Why this score"},
    {"name": "Allocation Issues", "value": 0, "color": "#F59E0B", "reason": "Why this score"},
    {"name": "Cost Inefficiency", "value": 0, "color": "#3B82F6", "reason": "Why this score"},
    {"name": "Redundancy", "value": 0, "color": "#10B981", "reason": "Why this score"}
  ],
  "risk_gauge": {"current": 0, "target": 0, "current_label": "", "target_label": ""},
  "cost_leakage": {"annual_loss": 0, "total_invested": 0, "loss_pct": 0, "detail": "explanation"},
  "action_funnel": [
    {"step": 1, "title": "", "detail": "with specific fund names and amounts", "status": "critical|important|moderate|recommended", "rupee_impact": "₹X/year", "funds_involved": ["Fund1"]}
  ],
  "before_after": {
    "before": {"return_pct": 0, "risk_score": 0, "risk_label": "", "expense_ratio": 0, "annual_cost": 0},
    "after": {"return_pct": 0, "risk_score": 0, "risk_label": "", "expense_ratio": 0, "annual_cost": 0, "wealth_10y_gain": 0}
  }
}

INSIGHT CATEGORIES TO COVER:
1. OVEREXPOSURE: Sector >25%, Company >10%, AMC >25% — cite exact % and ideal
2. FUND OVERLAP: Funds in same category, duplication score — suggest which to consolidate
3. COST LEAKAGE: Regular plans → Direct plans — cite exact expense ratio difference
4. ALLOCATION GAPS: Missing debt (ideal 10-25%), gold overweight (ideal 5-10%), no international
5. RISK CONCENTRATION: Small cap >15%, single stock risk, volatility exposure
6. PERFORMANCE: Underperforming funds (below category average)

For problem_distribution values: must sum to 100. Base on ACTUAL issues found:
- High Risk: concentration, volatility, single-stock exposure
- Allocation Issues: missing asset classes, overweight categories
- Cost Inefficiency: regular plans, high expense ratios
- Redundancy: overlapping funds, duplicate categories"""


@router.post("/insights/generate")
async def generate_insights(request: Request):
    user = await get_current_user(request)
    user_id = user["user_id"]

    holdings = await db.holdings.find({"user_id": user_id}, {"_id": 0}).to_list(500)
    if not holdings:
        return {"insights": [], "message": "Add holdings to generate insights"}

    holdings = enrich_holdings_with_sectors(holdings)

    # Gather ALL available analysis data
    deep_analytics = await db.portfolio_analysis_deep.find_one({"user_id": user_id}, {"_id": 0})
    if not deep_analytics:
        # Try to compute on-the-fly from deep-analytics cache
        from routes.analytics import get_deep_analytics as _deep
        try:
            # Use cached deep analytics if available
            deep_doc = None
        except Exception:
            deep_doc = None
        deep_analytics = deep_doc

    allocation_data = None
    alloc_cache = await db.allocation_analysis_cache.find_one({"user_id": user_id}, {"_id": 0})
    if alloc_cache:
        allocation_data = alloc_cache.get("data")

    # Build comprehensive prompt
    prompt = _build_comprehensive_prompt(holdings, deep_analytics, allocation_data)

    try:
        response = await ai_engine.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": ENHANCED_INSIGHT_SYSTEM},
                {"role": "user", "content": f"Analyze this portfolio and generate insights:\n\n{prompt}"},
            ],
            max_tokens=4000,
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        text = response.choices[0].message.content
        analysis = json.loads(text)

        if not analysis.get("insights"):
            raise ValueError("No insights generated")

    except Exception as e:
        logger.error(f"Enhanced insights generation error: {e}")
        analysis = {
            "insights": [{"title": "Analysis Error", "description": f"Could not generate insights: {str(e)[:100]}. Try again.", "type": "info", "impact": "medium", "effort": "low", "category": "info", "current_value": "", "target_value": "", "action": ""}],
            "problem_distribution": [],
            "before_after": {"before": {"return_pct": 0, "risk_label": "N/A", "risk_score": 0, "expense_ratio": 0}, "after": {"return_pct": 0, "risk_label": "N/A", "risk_score": 0, "expense_ratio": 0}},
            "action_funnel": [],
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
            "affected_funds": insight.get("affected_funds", []),
            "action": insight.get("action", ""),
            "progress": insight.get("progress", 0),
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        await db.ai_insights.insert_one(doc)
        saved_insights.append({k: v for k, v in doc.items() if k != "_id"})

    analysis["insights"] = saved_insights

    # Add reason text to problem_distribution
    for pd_item in analysis.get("problem_distribution", []):
        if not pd_item.get("reason"):
            pd_item["reason"] = ""

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
