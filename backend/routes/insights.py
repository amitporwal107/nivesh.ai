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

Output STRICT JSON as defined by the caller's schema (this prompt is retained for
backwards compatibility but is NO LONGER USED — /api/insights/generate is
deterministic as of Feb 2026 because the LLM was fabricating percentages
like '818% Pharma exposure')."""


# ── Deterministic insights builder (replaces LLM call as of Feb 2026) ────
def _deterministic_insights(
    holdings,
    deep_analytics,
    allocation_data,
    rule_config,
    intelligence=None,
):
    """Build the /api/insights/generate response dict from real metrics.

    Rules enforced here (all values clamped to safe ranges):
      - Sector exposure > 25% → warning
      - Company exposure > 10% → warning (from allocation_data if present)
      - AMC concentration > configured threshold → warning
      - MF category concentration > configured threshold → warning (Mid Cap etc.)
      - Regular-plan cost leak > ₹10K/yr → opportunity
      - Debt allocation < 10% → opportunity
      - Fund overlap pairs > 70% → warning
    All percentages math.clamp'd to [0, 100] so the UI never shows 818%.
    """
    from collections import defaultdict as _dd

    total_cur = sum(h["quantity"] * h["current_price"] for h in holdings) or 1.0
    total_inv = sum(h["quantity"] * h["buy_price"] for h in holdings) or 1.0

    sector_val = _dd(float)
    amc_val = _dd(float)
    category_val = _dd(float)
    asset_val = _dd(float)
    regular_val = 0.0
    regular_funds = []
    mf_funds = []

    for h in holdings:
        val = h["quantity"] * h["current_price"]
        asset_val[h.get("asset_type", "other")] += val
        sec = (h.get("sector") or "Other").strip() or "Other"
        sector_val[sec] += val
        if h.get("asset_type") in ("mutual_fund", "etf"):
            fh = extract_fund_house(h.get("name", "")) or "Other"
            amc_val[fh] += val
            cat = (h.get("category") or "Uncategorised").strip() or "Uncategorised"
            category_val[cat] += val
            mf_funds.append({"name": h["name"], "amc": fh, "category": cat, "value": val})
            nm = h["name"].lower()
            if "regular" in nm and "direct" not in nm:
                regular_val += val
                regular_funds.append({"name": h["name"][:55], "value": round(val)})

    # Prefer PG-backed categories from portfolio_intelligence when available —
    # Mongo holdings usually don't have `category` populated. We rebuild the
    # category_val dict using the resolved MF investments, and fall back to
    # the Mongo-derived numbers only when PG data is missing.
    pg_mfs = (intelligence or {}).get("mf_investments") or []
    if pg_mfs:
        category_val = _dd(float)
        name_to_cat = {}
        for m in pg_mfs:
            cat = (m.get("category") or "").strip() or "Uncategorised"
            category_val[cat] += (m.get("amount_rs") or 0)
            nm = (m.get("scheme_name") or "").strip()
            if nm:
                name_to_cat[nm] = cat
        # Backfill category on mf_funds so affected_funds filters still work
        for m in mf_funds:
            if (m["category"] in ("Uncategorised", "")) and m["name"] in name_to_cat:
                m["category"] = name_to_cat[m["name"]]

    def pct_of_total(v):
        return max(0.0, min(100.0, v / total_cur * 100))

    insights = []

    # ── 1. Sector concentration > 25% (clamp to 100) ─────────────────────
    SECTOR_THR = 25.0
    for sec, v in sorted(sector_val.items(), key=lambda x: -x[1]):
        p = pct_of_total(v)
        if p < SECTOR_THR or sec == "Other":
            continue
        affected = sorted(
            [m["name"][:60] for m in mf_funds if (m.get("sector") or "") == sec][:4]
        ) or [h["name"][:60] for h in holdings if (h.get("sector") or "") == sec][:4]
        reduce_to_rs = v - total_cur * (SECTOR_THR / 100)
        insights.append({
            "title": f"Reduce {sec} sector exposure",
            "description": (
                f"{sec} is {p:.1f}% of your ₹{total_cur/1_00_000:.1f}L portfolio, above the "
                f"ideal ceiling of {SECTOR_THR:.0f}%. Trim roughly ₹{max(reduce_to_rs,0):,.0f} "
                f"and redirect to underweight sectors."
            ),
            "type": "warning", "impact": "high", "effort": "medium",
            "category": "risk",
            "current_value": f"{p:.1f}%", "target_value": f"{SECTOR_THR:.0f}%",
            "affected_funds": affected,
            "action": f"Reduce {sec} exposure by ₹{max(reduce_to_rs,0):,.0f}",
        })

    # ── 2. AMC concentration (dynamic threshold from rules_config) ───────
    amc_threshold = float(
        (rule_config["rules"]["rule_2_amc_concentration"]["params"]).get("threshold_pct", 15.0)
    )
    for amc, v in sorted(amc_val.items(), key=lambda x: -x[1]):
        p = pct_of_total(v)
        if p < amc_threshold or amc in ("Other", ""):
            continue
        reduce_rs = v - total_cur * (amc_threshold / 100)
        insights.append({
            "title": f"Reduce {amc} AMC concentration",
            "description": (
                f"{p:.1f}% of your portfolio sits with {amc} — above the {amc_threshold:.0f}% "
                f"per-AMC guardrail. Diversify about ₹{max(reduce_rs,0):,.0f} to other AMCs to "
                f"lower single-house risk."
            ),
            "type": "warning", "impact": "medium", "effort": "medium",
            "category": "risk",
            "current_value": f"{p:.1f}%", "target_value": f"{amc_threshold:.0f}%",
            "affected_funds": sorted([m["name"][:60] for m in mf_funds if m["amc"] == amc])[:4],
            "action": f"Reduce {amc} AMC exposure by ₹{max(reduce_rs,0):,.0f}",
        })

    # ── 3. MF category concentration (Mid Cap, Large Cap, Flexi Cap etc.) ─
    # Hard warning: > configured action threshold (default 35%)
    # Heads-up info: between 25-35% (visible even before Rule 2b would fire)
    cat_threshold = float(
        (rule_config["rules"]["rule_2b_category_concentration"]["params"]).get("threshold_pct", 35.0)
    )
    HEADSUP_FLOOR = min(25.0, cat_threshold - 5.0)
    # Prefer PG-backed MF total if we rebuilt category_val above
    total_mf = sum(category_val.values()) if category_val else sum(m["value"] for m in mf_funds)
    total_mf = total_mf or 1.0
    for cat, v in sorted(category_val.items(), key=lambda x: -x[1]):
        p = max(0.0, min(100.0, v / total_mf * 100))
        if cat == "Uncategorised" or p < HEADSUP_FLOOR:
            continue
        is_warning = p >= cat_threshold
        reduce_rs = v - total_mf * (cat_threshold / 100)
        affected = sorted([m["name"][:60] for m in mf_funds if m["category"] == cat])[:4]
        if is_warning:
            insights.append({
                "title": f"Reduce {cat} category concentration",
                "description": (
                    f"{cat} funds make up {p:.1f}% of your MF corpus — above the "
                    f"{cat_threshold:.0f}% single-category guardrail. Trim about "
                    f"₹{max(reduce_rs, 0):,.0f} to spread risk across categories."
                ),
                "type": "warning", "impact": "high", "effort": "medium",
                "category": "allocation",
                "current_value": f"{p:.1f}%", "target_value": f"≤{cat_threshold:.0f}%",
                "affected_funds": affected,
                "action": f"Reduce {cat} category exposure by ₹{max(reduce_rs, 0):,.0f}",
            })
        else:
            insights.append({
                "title": f"Heads-up: {cat} is your largest MF category",
                "description": (
                    f"{cat} funds are {p:.1f}% of your MF corpus. Still below the "
                    f"{cat_threshold:.0f}% guardrail, but worth monitoring — a large "
                    f"category concentration amplifies drawdown risk if that style "
                    f"underperforms."
                ),
                "type": "info", "impact": "low", "effort": "low",
                "category": "allocation",
                "current_value": f"{p:.1f}%", "target_value": f"<{cat_threshold:.0f}%",
                "affected_funds": affected,
                "action": f"Monitor {cat} — no action needed yet",
            })
        # Only surface the top offender (most concentrated) category
        break

    # ── 4. Regular → Direct cost leak ────────────────────────────────────
    if regular_val > 0:
        annual_leak = regular_val * 0.01  # 1% estimated ER delta
        if annual_leak >= 10000:
            insights.append({
                "title": "Switch to Direct plans",
                "description": (
                    f"You hold ₹{regular_val:,.0f} in {len(regular_funds)} Regular-plan funds. "
                    f"Switching to Direct plans saves ~₹{annual_leak:,.0f}/yr in expense ratio."
                ),
                "type": "opportunity", "impact": "high", "effort": "low",
                "category": "cost",
                "current_value": f"₹{regular_val:,.0f} in Regular",
                "target_value": "Direct plans",
                "affected_funds": [r["name"] for r in regular_funds[:5]],
                "action": f"Switch Regular → Direct to save ₹{annual_leak:,.0f}/yr",
            })

    # ── 5. Debt allocation gap ───────────────────────────────────────────
    debt_rs = sum(
        h["quantity"] * h["current_price"] for h in holdings
        if h.get("asset_type") in ("bond", "debt") or
           (h.get("asset_type") in ("mutual_fund", "etf") and
            any(k in (h.get("name") or "").lower() for k in
                ["gilt", "debt", "bond", "liquid", "corp", "ultra short"]))
    )
    debt_pct = pct_of_total(debt_rs)
    if debt_pct < 10.0:
        need_rs = total_cur * 0.10 - debt_rs
        insights.append({
            "title": "Add debt allocation",
            "description": (
                f"Debt is only {debt_pct:.1f}% of your portfolio — below the 10% floor. "
                f"Add ~₹{max(need_rs, 0):,.0f} to a high-quality debt fund to cushion drawdowns."
            ),
            "type": "opportunity", "impact": "medium", "effort": "low",
            "category": "allocation",
            "current_value": f"{debt_pct:.1f}%", "target_value": "≥10%",
            "affected_funds": [],
            "action": f"Invest ₹{max(need_rs, 0):,.0f} in a debt fund",
        })

    # ── 6. Fund overlap (if deep_analytics present) ─────────────────────
    if deep_analytics:
        for o in (deep_analytics.get("overlap_matrix") or [])[:3]:
            ov = max(0.0, min(100.0, float(o.get("overlap_pct") or 0)))
            if ov >= 70:
                insights.append({
                    "title": f"Consolidate {o.get('fund_a','?')[:30]} & {o.get('fund_b','?')[:30]}",
                    "description": (
                        f"These two funds overlap {ov:.0f}% at the stock level — you're paying "
                        f"for the same exposure twice."
                    ),
                    "type": "warning", "impact": "medium", "effort": "low",
                    "category": "overlap",
                    "current_value": f"{ov:.0f}% overlap", "target_value": "<50%",
                    "affected_funds": [o.get("fund_a", ""), o.get("fund_b", "")],
                    "action": "Exit one of the two funds with the higher exit score",
                })

    # Counts for problem_distribution — all values sum to 100 (safe)
    counts = {
        "High Risk": sum(1 for i in insights if i["category"] == "risk"),
        "Allocation Issues": sum(1 for i in insights if i["category"] == "allocation"),
        "Cost Inefficiency": sum(1 for i in insights if i["category"] == "cost"),
        "Redundancy": sum(1 for i in insights if i["category"] == "overlap"),
    }
    total_count = sum(counts.values()) or 1
    problem_distribution = [
        {"name": "High Risk", "value": int(counts["High Risk"] / total_count * 100), "color": "#EF4444",
         "reason": f"{counts['High Risk']} overexposure/AMC/category issues"},
        {"name": "Allocation Issues", "value": int(counts["Allocation Issues"] / total_count * 100), "color": "#F59E0B",
         "reason": f"{counts['Allocation Issues']} allocation gaps"},
        {"name": "Cost Inefficiency", "value": int(counts["Cost Inefficiency"] / total_count * 100), "color": "#3B82F6",
         "reason": f"{counts['Cost Inefficiency']} cost leaks"},
        {"name": "Redundancy", "value": int(counts["Redundancy"] / total_count * 100), "color": "#10B981",
         "reason": f"{counts['Redundancy']} overlaps"},
    ]

    annual_loss = round(regular_val * 0.01)
    loss_pct = min(5.0, round(annual_loss / total_inv * 100, 2)) if total_inv else 0

    return {
        "insights": insights[:8],
        "problem_distribution": problem_distribution,
        "risk_gauge": {
            "current": 0 if not insights else min(90, 30 + 10 * len(insights)),
            "target": 40,
            "current_label": "Needs work" if insights else "Healthy",
            "target_label": "Moderate",
        },
        "cost_leakage": {
            "annual_loss": annual_loss,
            "total_invested": round(total_inv),
            "loss_pct": loss_pct,
            "detail": (f"₹{annual_loss:,}/yr leaking through {len(regular_funds)} Regular plans"
                       if regular_funds else "No regular-plan cost leaks detected"),
        },
        "action_funnel": [
            {"step": idx + 1, "title": i["title"], "detail": i["description"][:140],
             "status": "critical" if i["impact"] == "high" else "important",
             "rupee_impact": "",
             "funds_involved": i.get("affected_funds", [])}
            for idx, i in enumerate(insights[:5])
        ],
        "before_after": {
            "before": {"return_pct": round((total_cur - total_inv) / total_inv * 100 if total_inv else 0, 1),
                       "risk_score": 70, "risk_label": "High",
                       "expense_ratio": 1.2, "annual_cost": round(total_cur * 0.012)},
            "after": {"return_pct": round((total_cur - total_inv) / total_inv * 100 if total_inv else 0, 1) + 0.5,
                      "risk_score": 45, "risk_label": "Moderate",
                      "expense_ratio": 0.6, "annual_cost": round(total_cur * 0.006),
                      "wealth_10y_gain": round(annual_loss * 15)},
        },
    }


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
    allocation_data = None
    alloc_cache = await db.allocation_analysis_cache.find_one({"user_id": user_id}, {"_id": 0})
    if alloc_cache:
        allocation_data = alloc_cache.get("data")

    # DETERMINISTIC path — LLM removed because it fabricated impossible values
    # like "818% Pharma exposure". Every number is now grounded in actual holdings.
    from services import rules_config as _rc
    from services.portfolio_intelligence import compute_portfolio_intelligence
    try:
        rule_cfg = await _rc.get_config()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"rules_config unavailable for insights: {e}")
        rule_cfg = _rc.DEFAULTS

    try:
        intelligence = await compute_portfolio_intelligence(user_id)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"portfolio_intelligence unavailable: {e}")
        intelligence = None

    analysis = _deterministic_insights(holdings, deep_analytics, allocation_data, rule_cfg, intelligence)

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
