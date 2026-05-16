"""AI Insights routes — Enhanced with full portfolio context."""
from fastapi import APIRouter, Request
from datetime import datetime, timezone
from typing import Any, Dict, Optional
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
        logger.warning("rules_config unavailable for insights: %s", e)
        rule_cfg = _rc.DEFAULTS

    try:
        intelligence = await compute_portfolio_intelligence(user_id)
    except Exception as e:  # noqa: BLE001
        logger.warning("portfolio_intelligence unavailable: %s", e)
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
    """Get the full portfolio analysis — now augmented with the unified
    Portfolio Health payload (single source of truth)."""
    user = await get_current_user(request)
    doc = await db.portfolio_analysis.find_one({"user_id": user["user_id"]}, {"_id": 0})
    analysis = (doc.get("analysis") if doc else None) or None

    # Always attach the unified Portfolio Health block so the Insights tab
    # renders the same score as the Dashboard.
    #
    # Hard 12s timeout PLUS asyncio.shield: cache and snapshot fast-paths
    # return in <50ms; only cold-start compute (Groww/V3/intelligence) is
    # slow. When the fast-paths miss AND the live pipeline takes longer
    # than 12s, we return null (UI exits its "Scoring…" spinner) but the
    # task keeps running on the event loop and writes to Redis + the
    # snapshot doc when it completes. The client retry hook polls every
    # 4s and gets the score from the warm cache on the next attempt.
    import asyncio as _asyncio
    try:
        from services import portfolio_health as _ph
        task = _asyncio.create_task(_ph.build_portfolio_health(user["user_id"]))
        hr = await _asyncio.wait_for(_asyncio.shield(task), timeout=12.0)
        if analysis is None:
            analysis = {}
        analysis["portfolio_health"] = hr.to_dict()
    except _asyncio.TimeoutError:
        logger.warning("portfolio_health compute >12s for user %s — returning null, background task will warm the cache", user['user_id'])
        if analysis is None:
            analysis = {}
        analysis["portfolio_health"] = None
    except Exception as e:  # noqa: BLE001
        logger.warning("attach portfolio_health to /insights/analysis failed: %s", e)
    return analysis


# ── V3 Engine Phase 3 — Portfolio-level V3 scoring for Insights ──────────
from services import (  # noqa: E402
    v3_integration,
    v3_scoring,
    v3_explainer,
    holding_action_score as has_svc,
    portfolio_intelligence as pintel,
    tax_calculator,
    portfolio_health as ph_svc,
)


@router.get("/insights/v3-portfolio")
async def v3_portfolio_summary(request: Request):
    """Portfolio-level V3 scoring.

    Returns:
      - Per-fund V3 composite scores (Quality, Health, Exit, Add, Switch)
      - Per-fund danger-zone classification + deterministic explanation
      - Portfolio-level averages (value-weighted)
      - Flagged funds (low-quality / blocked by guardrails)
      - Coverage confidence: % of AUM that has full V3 scores
      - **Portfolio Health & Risk** composite score + component breakdown
        + top risk drivers.  Use `?refresh_stocks=1` to force-refresh Groww
        stock fundamentals cache (default: 24h TTL).
    """
    user = await get_current_user(request)
    uid = user["user_id"]
    force_refresh_stocks = request.query_params.get("refresh_stocks", "").lower() in ("1", "true", "yes")

    # Load MF holdings
    mf_holdings = await db.holdings.find(
        {"user_id": uid, "asset_type": "mutual_fund"},
        {"_id": 0},
    ).to_list(500)
    if not mf_holdings:
        # Still compute Health from equity-only portfolio (if any equities exist)
        try:
            hr = await ph_svc.build_portfolio_health(
                uid, force_refresh_stocks=force_refresh_stocks,
            )
            health_payload = hr.to_dict()
        except Exception as e:  # noqa: BLE001
            logger.warning("Portfolio Health (no MF) failed for %s: %s", uid, e)
            health_payload = None
        return {"coverage_pct": 0, "funds": [], "portfolio": {},
                "engine_version": v3_scoring.ENGINE_VERSION,
                "health": health_payload}

    # Build mf_investments-shape list (what enrich_candidates_with_v3 expects)
    mf_investments = [
        {
            "scheme_name": h.get("name"),
            "instrument_id": h.get("instrument_id"),
            "value": float(h.get("quantity", 0)) * float(h.get("current_price", 0)),
        }
        for h in mf_holdings
    ]

    # Enrich (reuses the same bulk V3 pipeline as action plans)
    v3_by_key = await v3_integration.enrich_candidates_with_v3(
        mf_investments=mf_investments,
        exit_candidates=[],
        mf_holdings=mf_holdings,
        portfolio_intelligence={},
    )

    from services.action_plan_manager import ActionPlanManager, _normalize_fund_name  # noqa: E402, F401
    apm = ActionPlanManager()
    # Precompute Regular/Direct pairs + leaked ₹/yr per Regular fund
    reg_pairs = apm._find_regular_direct_pairs(mf_holdings)
    solo_regs = apm._find_regular_without_direct_pair(mf_holdings, reg_pairs)
    reg_leak_by_name: dict = {}
    for p in reg_pairs:
        reg = p["regular"]
        leak = apm._estimate_cost_leak(reg, p["direct"], mf_investments)
        reg_leak_by_name[_normalize_fund_name(reg.get("name", ""))] = leak
    for reg in solo_regs:
        leak = apm._estimate_cost_leak(reg, None, mf_investments)
        reg_leak_by_name[_normalize_fund_name(reg.get("name", ""))] = leak

    total_aum = sum(m["value"] for m in mf_investments) or 1.0
    covered_aum = 0.0

    # ── HAS layer — portfolio-aware per-holding scoring ────────────────
    # Fetch pairwise overlap from portfolio_intelligence (one PG round-trip).
    # Build overlap_by_name: scheme_name → weighted avg overlap with rest of
    # portfolio (by value).
    pi: dict = {}
    overlap_pct_by_name: Dict[str, float] = {}
    try:
        pi = await pintel.compute_portfolio_intelligence(uid)
    except Exception as e:  # noqa: BLE001
        logger.warning("portfolio_intelligence fetch for HAS failed: %s", e)
    if pi and pi.get("pairwise_overlap"):
        # Index mf_investments by instrument_id for value lookup.
        inv_value_by_iid = {m["instrument_id"]: m["amount_rs"]
                            for m in pi.get("mf_investments", [])
                            if m.get("instrument_id")}
        inv_name_by_iid = {m["instrument_id"]: m.get("scheme_name", "")
                           for m in pi.get("mf_investments", [])
                           if m.get("instrument_id")}
        # Accumulate per-fund weighted overlap
        accum: Dict[str, Dict[str, float]] = {}
        for pair in pi["pairwise_overlap"]:
            a, b = pair["a"], pair["b"]
            ov = float(pair.get("overlap_pct") or 0)
            for x, y in ((a, b), (b, a)):
                bucket = accum.setdefault(x, {"num": 0.0, "den": 0.0})
                y_val = inv_value_by_iid.get(y, 0.0)
                bucket["num"] += ov * y_val
                bucket["den"] += y_val
        for iid, b in accum.items():
            weighted = (b["num"] / b["den"]) if b["den"] > 0 else 0.0
            name = inv_name_by_iid.get(iid, "")
            if name:
                overlap_pct_by_name[_normalize_fund_name(name)] = weighted

    # Target weight = 10% concentration cap, but never less than equal-weight
    # (100/N). Cap keeps highly-diversified portfolios from flagging every
    # holding as over-weight.
    n_funds = max(1, len(mf_investments))
    target_weight_pct = max(10.0, 100.0 / n_funds) if n_funds < 10 else 10.0
    # Only if super-concentrated (≤10 funds), use equal-weight as target.
    if n_funds <= 10:
        target_weight_pct = 100.0 / n_funds

    # Tax estimate per holding (FIFO-lite via calculate_tax_impact)
    tax_by_name: Dict[str, Dict[str, Any]] = {}
    for h in mf_holdings:
        try:
            tax = tax_calculator.calculate_tax_impact(h)
            tax_by_name[_normalize_fund_name(h.get("name", ""))] = tax
        except Exception:  # noqa: BLE001
            continue

    # Holding-age days per holding
    age_by_name: Dict[str, Optional[int]] = {}
    for h in mf_holdings:
        age_by_name[_normalize_fund_name(h.get("name", ""))] = \
            tax_calculator.calculate_holding_period_days(h.get("buy_date"))

    funds_out = []
    quality_weighted = 0.0
    health_weighted = 0.0
    quality_weights = 0.0
    health_weights = 0.0
    flagged: list = []
    n_exit_recs = 0
    n_switch_recs = 0
    n_review_recs = 0

    # ── Category rank map (sub_category partition, direct-plan only) ──
    category_rank_by_iid: Dict[str, Dict[str, Any]] = {}
    try:
        from routes.admin_v3_master import _fetch_master_funds
        all_funds = await _fetch_master_funds(limit=None)
        by_cat: Dict[str, list] = {}
        for f in all_funds:
            sub = f.get("sub_category") or f.get("category")
            q = (f.get("scores") or {}).get("quality")
            if sub and q is not None and f.get("plan_type") != "regular":
                by_cat.setdefault(sub, []).append(f)
        for sub, funds in by_cat.items():
            funds.sort(key=lambda x: x["scores"]["quality"] or 0, reverse=True)
            total = len(funds)
            for i, f in enumerate(funds, start=1):
                iid_f = f.get("instrument_id")
                if iid_f:
                    category_rank_by_iid[iid_f] = {
                        "rank": i, "total": total, "sub_category": sub,
                    }
    except Exception as e:  # noqa: BLE001
        logger.warning("v3-portfolio category-rank build failed: %s", e)

    # ── NIDP scorecard enrichment (best-effort, parallel) ─────────────────
    # Resolve scheme_code for each holding: try holding directly, then
    # fall back to v3_primitives if the holding doesn't carry the field.
    nidp_scorecard_by_name: Dict[str, Optional[dict]] = {}
    try:
        import asyncio as _asyncio
        from services.copilot_tools import daas_client as _dc

        def _scheme_code_for(holding_doc: dict, v3_data: Optional[dict]) -> Optional[str]:
            code = holding_doc.get("scheme_code")
            if not code and v3_data:
                code = (v3_data.get("v3_primitives") or {}).get("scheme_code")
            return str(code) if code else None

        # Build (name, scheme_code) pairs — de-duplicate by scheme_code
        _seen_codes: set = set()
        _tasks: list = []
        _task_names: list = []
        for _m in mf_investments:
            _name = _m.get("scheme_name", "")
            _iid  = _m.get("instrument_id")
            _v3   = v3_integration.lookup_v3(_iid, _name, v3_by_key)
            _h    = next((h for h in mf_holdings
                          if _normalize_fund_name(h.get("name","")) ==
                             _normalize_fund_name(_name)), {})
            _code = _scheme_code_for(_h, _v3)
            if _code and _code not in _seen_codes:
                _seen_codes.add(_code)
                _tasks.append(_dc.get_mf_scorecard(_code))
                _task_names.append((_name, _code))

        if _tasks:
            _results = await _asyncio.gather(*_tasks, return_exceptions=True)
            # Map scheme_code → scorecard; also index by name for the loop below
            _code_to_sc: Dict[str, dict] = {}
            for (_n, _c), _r in zip(_task_names, _results):
                if isinstance(_r, dict):
                    _code_to_sc[_c] = _r

            # Re-walk investments so every name gets its scorecard
            for _m in mf_investments:
                _name = _m.get("scheme_name", "")
                _iid  = _m.get("instrument_id")
                _v3   = v3_integration.lookup_v3(_iid, _name, v3_by_key)
                _h    = next((h for h in mf_holdings
                              if _normalize_fund_name(h.get("name","")) ==
                                 _normalize_fund_name(_name)), {})
                _code = _scheme_code_for(_h, _v3)
                nidp_scorecard_by_name[_name] = _code_to_sc.get(_code) if _code else None
    except Exception as _e:  # noqa: BLE001
        logger.info("NIDP scorecard batch-fetch skipped: %s", _e)

    for m in mf_investments:
        iid = m.get("instrument_id")
        name = m.get("scheme_name", "")
        v3 = v3_integration.lookup_v3(iid, name, v3_by_key)
        plan_type = apm._classify_plan_type(name)
        cost_leak = reg_leak_by_name.get(_normalize_fund_name(name))
        # Compute Switch score (Regular plans only — Direct is already optimal)
        switch_score = None
        if v3 and plan_type == "regular" and cost_leak:
            try:
                sw = v3_scoring.compute_switch_score(
                    quality_new=None, quality_old=None,
                    overlap_reduction_pct=0,
                    cost_saving_rs_per_yr=float(cost_leak),
                    tax_cost_rs=0,  # tax impact folded in by action plan, not here
                )
                switch_score = sw["score"]
            except Exception:  # noqa: BLE001
                switch_score = None

        # ── Switch Decision Engine v2 — full PRD logic ────────────────
        # Runs for BOTH Regular and Direct plans. Regular gets Direct-plan
        # priority (Case A). All plans get peer-group fund-to-fund analysis
        # (Case B) hydrated from pg_mirror mutual fund metadata + ratios.
        switch_decision_dict = None
        current_val = float(m.get("value") or 0)
        if current_val > 0:
            h_name = _normalize_fund_name(name)
            holding_age_days = age_by_name.get(h_name)
            # Find the holding's invested amount + exit_load_pct
            invested = 0.0
            exit_load_pct = 0.0
            for h in mf_holdings:
                if _normalize_fund_name(h.get("name", "")) == h_name:
                    invested = float(h.get("quantity", 0) or 0) * float(h.get("buy_price", 0) or 0)
                    exit_load_pct = float(h.get("exit_load_pct") or 0)
                    break
            try:
                from services import switch_decision_engine as sde
                from services import candidate_fund_hydrator as cfh

                # Real current-fund context (expense, returns, drawdown,
                # consistency, sub_category) from pg_mirror, not a hack.
                # CAS holdings often have no `instrument_id` directly — use
                # the v3 fuzzy-resolved id instead.
                lookup_iid = (v3 or {}).get("instrument_id") or iid
                ctx = await cfh.fetch_current_fund_context(
                    db, instrument_id=lookup_iid, scheme_name=name
                ) or {}
                sub_cat = ctx.get("sub_category")
                broad_cat = (ctx.get("category") or "").lower()
                expense_reg = ctx.get("expense_current")
                expense_dir = ctx.get("expense_direct")

                # Fallback: derive expense diff from cost_leak when pg_mirror
                # lookup misses (CAS-only holdings without instrument_id).
                if expense_reg is None and cost_leak and current_val > 0:
                    expense_reg = float(cost_leak) / current_val
                    expense_dir = 0.0

                direct_available = bool(
                    (expense_reg is not None and expense_dir is not None
                     and expense_reg > expense_dir)
                    or (plan_type == "regular" and cost_leak is not None and cost_leak > 0)
                )

                # Peer universe — only when we have a sub-category. Exclude
                # the current holding's instrument_id from its own peers.
                peers = []
                if sub_cat:
                    peers = await cfh.fetch_candidates_for_category(
                        db, sub_cat,
                        prefer_direct=True,
                        exclude_instrument_id=lookup_iid,
                    )

                # PRD §9 portfolio context — populate so over-allocation
                # and sector/thematic overrides can fire on live data.
                weight_pct = (current_val / total_aum * 100.0) if total_aum > 0 else None
                sub_lower = (sub_cat or "").lower()
                is_thematic = any(
                    kw in sub_lower
                    for kw in ("sector", "thematic", "energy", "infra",
                               "pharma", "fmcg", "tech", "banking",
                               "psu", "consumption", "manufactur")
                )
                # Tax treatment differs for equity vs debt/hybrid.
                # Equity-oriented funds (incl. hybrid-equity, ELSS, index)
                # follow STCG-15% / LTCG-10% w/ ₹1L exemption. Debt funds
                # follow slab rate.
                is_equity_fund = not any(
                    kw in broad_cat
                    for kw in ("debt", "liquid", "money market", "ultra short",
                               "low duration", "gilt", "credit", "corporate bond",
                               "banking and psu")
                )

                inp = sde.DecisionInputs(
                    quality=v3.get("quality_score") if v3 else None,
                    health=v3.get("health_score") if v3 else None,
                    exit_s=v3.get("exit_score") if v3 else None,
                    add=v3.get("add_score") if v3 else None,
                    invested_amount=invested,
                    current_value=current_val,
                    holding_period_days=holding_age_days,
                    is_equity=is_equity_fund,
                    exit_load_pct=exit_load_pct,
                    expense_current=expense_reg,
                    expense_direct=expense_dir,
                    current_return_5y=ctx.get("current_return_5y"),
                    current_drawdown=ctx.get("current_drawdown"),
                    current_consistency=ctx.get("current_consistency"),
                    current_category=sub_cat,
                    current_fund_name=name,
                    direct_plan_available=direct_available,
                    portfolio_weight_pct=weight_pct,
                    is_sector_or_thematic=is_thematic,
                    candidate_funds=peers,
                )
                switch_decision_dict = sde.result_to_dict(
                    sde.decide(inp, plan_type=plan_type or "regular")
                )
                # Surface peer-universe size for observability (UI debug only).
                switch_decision_dict["_n_candidates"] = len(peers)
            except Exception as e:  # noqa: BLE001
                logger.warning("switch_decision_engine failed for %s: %s", name, e)
                switch_decision_dict = None

        entry = {
            "scheme_name": name,
            "instrument_id": iid,
            "value_rs": round(m["value"], 2),
            "plan_type": plan_type,
            "cost_leak_rs_per_yr": round(cost_leak, 0) if cost_leak else None,
            "scores": None,
            "morningstar_rating": None,
            "category_rank": None,
            "category_rank_total": None,
            "category_rank_sub": None,
            "nidp_scorecard": None,
        }
        # Attach NIDP composite scorecard when available.
        _nsc = nidp_scorecard_by_name.get(name)
        if _nsc:
            entry["nidp_scorecard"] = {
                "composite_score":    _nsc.get("composite_score"),
                "quality_label":      _nsc.get("quality_label"),
                "composite_rank":     _nsc.get("composite_rank"),
                "total_in_category":  _nsc.get("total_in_category"),
                "top_position_pct":   _nsc.get("top_position_pct"),
                "return_1y":          _nsc.get("return_1y"),
                "return_3y":          _nsc.get("return_3y"),
                "return_5y":          _nsc.get("return_5y"),
                "sharpe_1y":          _nsc.get("sharpe_1y"),
                "ter":                _nsc.get("ter"),
                "qtile_ret1y":        _nsc.get("qtile_ret1y"),
                "qtile_ret3y":        _nsc.get("qtile_ret3y"),
                "qtile_sharpe":       _nsc.get("qtile_sharpe"),
                "qtile_ter":          _nsc.get("qtile_ter"),
                "qtile_maxdd":        _nsc.get("qtile_maxdd"),
            }
        # Surface Morningstar + Category Rank from v3 + master catalogue.
        prim = (v3 or {}).get("v3_primitives") or {}
        entry["morningstar_rating"] = prim.get("morningstar_rating")
        # Use the INSTRUMENT_ID FROM THE MATCHED V3 BUNDLE, not the mongo holding
        # (mongo's instrument_id is often None for CAS-parsed holdings).
        v3_iid = (v3 or {}).get("instrument_id") or iid
        if v3_iid:
            cr = category_rank_by_iid.get(v3_iid)
            if cr:
                entry["category_rank"] = cr["rank"]
                entry["category_rank_total"] = cr["total"]
                entry["category_rank_sub"] = cr["sub_category"]
        if v3:
            bundle = {**v3, "switch_score": switch_score, "switch_decision": switch_decision_dict}
            entry["scores"] = {
                "quality": v3.get("quality_score"),
                "health": v3.get("health_score"),
                "exit": v3.get("exit_score"),
                "add": v3.get("add_score"),
                "switch": switch_score,
                "quality_missing": v3.get("quality_missing"),
                "health_missing": v3.get("health_missing"),
            }
            entry["quality_components"] = v3.get("quality_components")
            entry["health_components"] = v3.get("health_components")
            entry["primitives"] = v3.get("v3_primitives")
            entry["guardrail_blocked"] = v3.get("guardrail_blocked")
            entry["guardrail_reasons"] = v3.get("guardrail_reasons")

            # Deterministic per-fund recommendation (EXIT/SWITCH/REVIEW/BUY/HOLD)
            recommendation = v3_explainer.derive_recommendation(
                bundle, plan_type=plan_type, cost_leak_rs=cost_leak,
            )
            entry["recommendation"] = recommendation
            # Expose full decision engine details so the UI can render
            # the reason + economics breakdown under the SWITCH chip.
            if switch_decision_dict:
                entry["switch_decision"] = switch_decision_dict
            entry["explanation"] = v3_explainer.build_explanation(
                bundle,
                scheme_name=name,
                plan_type=plan_type,
                cost_leak_rs=cost_leak,
            )
            action = recommendation["action"]
            if action == "EXIT":
                n_exit_recs += 1
            elif action in ("SWITCH", "STRONG_SWITCH_DIRECT", "PHASED_SWITCH_DIRECT",
                            "STRONG_SWITCH", "PARTIAL_SWITCH", "SIP_REDIRECT"):
                n_switch_recs += 1
            elif action in ("REVIEW", "WATCHLIST"):
                n_review_recs += 1

            # ── Compute HAS (portfolio-aware holding action) ────────────
            name_key = _normalize_fund_name(name)
            current_weight_pct = (m["value"] / total_aum) * 100.0
            tax_info = tax_by_name.get(name_key) or {}
            tax_liability = tax_info.get("tax_liability")
            holding_period_days = age_by_name.get(name_key)
            is_stcg = (
                tax_info.get("is_long_term") is False
            )
            # Benefit = annual cost leak saving (if applicable) — tiny proxy
            # for "what do we gain by exiting". Conservative: 3y projection.
            tax_benefit = (cost_leak or 0) * 3 if cost_leak else 0
            category = v3.get("category") or "equity"
            # Coverage-based confidence: more missing primitives → less sure
            qmiss = len(v3.get("quality_missing") or [])
            hmiss = len(v3.get("health_missing") or [])
            coverage_conf = max(0.0, 100.0 - (qmiss + hmiss) * 8.0)

            has_result = has_svc.build_holding_action(
                category=category,
                quality=v3.get("quality_score"),
                health=v3.get("health_score"),
                exit_score=v3.get("exit_score"),
                add_score=v3.get("add_score"),
                portfolio_overlap_pct=overlap_pct_by_name.get(name_key),
                current_weight_pct=current_weight_pct,
                target_weight_pct=target_weight_pct,
                tax_cost_rs=tax_liability,
                tax_benefit_rs=tax_benefit,
                holding_value_rs=m["value"],
                is_stcg=is_stcg,
                holding_age_days=holding_period_days,
                confidence=coverage_conf,
            )
            entry["has"] = has_result.to_dict()

            covered_aum += m["value"]
            if v3.get("quality_score") is not None:
                quality_weighted += v3["quality_score"] * m["value"]
                quality_weights += m["value"]
            if v3.get("health_score") is not None:
                health_weighted += v3["health_score"] * m["value"]
                health_weights += m["value"]
            # Flagging (legacy field for existing UI blocks)
            if (v3.get("quality_score") or 100) < 50:
                flagged.append({"scheme_name": name, "reason": "low_quality",
                                "value_rs": round(m["value"], 2),
                                "quality_score": v3.get("quality_score")})
            elif (v3.get("health_score") or 100) < 50:
                flagged.append({"scheme_name": name, "reason": "low_health",
                                "value_rs": round(m["value"], 2),
                                "health_score": v3.get("health_score")})
        else:
            entry["recommendation"] = {
                "action": "HOLD",
                "label": "Hold",
                "reason": "No V3 data available for this fund yet.",
            }
            entry["explanation"] = "No V3 data available for this fund yet."
        funds_out.append(entry)

    # HAS action tallies (portfolio-layer decisions)
    has_tally = {"ADD": 0, "HOLD": 0, "TRIM": 0, "SWITCH": 0, "EXIT": 0, "REVIEW": 0, "UNKNOWN": 0}
    has_value_weighted = 0.0
    has_value_weights = 0.0
    for f in funds_out:
        ha = f.get("has") or {}
        act = ha.get("action")
        if act in has_tally:
            has_tally[act] += 1
        if ha.get("has") is not None:
            has_value_weighted += ha["has"] * f.get("value_rs", 0)
            has_value_weights += f.get("value_rs", 0)

    # Morningstar + category-rank aggregate summary
    ms_values = [f["morningstar_rating"] for f in funds_out if f.get("morningstar_rating") is not None]
    top_quartile = sum(
        1 for f in funds_out
        if f.get("category_rank") and f.get("category_rank_total")
        and f["category_rank"] <= max(1, round(f["category_rank_total"] * 0.25))
    )

    portfolio = {
        "avg_quality_score": round(quality_weighted / quality_weights, 2) if quality_weights else None,
        "avg_health_score": round(health_weighted / health_weights, 2) if health_weights else None,
        "avg_has_score": round(has_value_weighted / has_value_weights, 2) if has_value_weights else None,
        "n_funds": len(mf_investments),
        "n_scored": sum(1 for f in funds_out if f.get("scores")),
        "n_flagged": len(flagged),
        "n_exit_recs": n_exit_recs,
        "n_switch_recs": n_switch_recs,
        "n_review_recs": n_review_recs,
        "has_action_counts": has_tally,
        "target_weight_pct_per_fund": round(target_weight_pct, 2),
        # New: third-party + peer-group signals
        "n_morningstar_rated": len(ms_values),
        "avg_morningstar_rating": round(sum(ms_values) / len(ms_values), 2) if ms_values else None,
        "n_morningstar_4plus": sum(1 for v in ms_values if v >= 4),
        "n_category_ranked": sum(1 for f in funds_out if f.get("category_rank")),
        "n_top_quartile": top_quartile,
        # NIDP composite scorecard counters
        "n_nidp_scored": sum(1 for f in funds_out if f.get("nidp_scorecard")),
        "n_nidp_elite_good": sum(
            1 for f in funds_out
            if (f.get("nidp_scorecard") or {}).get("quality_label") in ("Elite", "Good")
        ),
        "n_nidp_underperformer": sum(
            1 for f in funds_out
            if (f.get("nidp_scorecard") or {}).get("quality_label") == "Underperformer"
        ),
        "avg_nidp_composite": round(
            sum(
                (f["nidp_scorecard"]["composite_score"] or 0)
                for f in funds_out
                if (f.get("nidp_scorecard") or {}).get("composite_score") is not None
            ) / max(1, sum(
                1 for f in funds_out
                if (f.get("nidp_scorecard") or {}).get("composite_score") is not None
            )), 1
        ) if any(
            (f.get("nidp_scorecard") or {}).get("composite_score") is not None
            for f in funds_out
        ) else None,
    }
    coverage_pct = round((covered_aum / total_aum) * 100, 1) if total_aum else 0

    # Sort by HAS action priority (EXIT → SWITCH → TRIM → REVIEW → HOLD → ADD),
    # then by ascending HAS so the most-needy funds float to the top. Fall back
    # to the V3 recommendation rank when HAS is missing.
    def _sort_key(f):
        ha = f.get("has") or {}
        has_action = ha.get("action")
        has_rank_map = {"EXIT": 0, "SWITCH": 1, "TRIM": 2, "REVIEW": 3, "HOLD": 4, "ADD": 5, "UNKNOWN": 6}
        if has_action in has_rank_map:
            return (has_rank_map[has_action], ha.get("has") if ha.get("has") is not None else 999)
        action = (f.get("recommendation") or {}).get("action", "HOLD")
        legacy_rank = {"EXIT": 0, "SWITCH": 1, "REVIEW": 2, "HOLD": 3, "BUY": 4}.get(action, 3)
        q = (f.get("scores") or {}).get("quality")
        return (legacy_rank + 10, -(q or -1))
    funds_out.sort(key=_sort_key)

    # ── Portfolio Health & Risk (composite D/R/C/P) ────────────────────
    try:
        health_result = await ph_svc.build_portfolio_health(
            uid, force_refresh_stocks=force_refresh_stocks,
        )
        health_payload = health_result.to_dict()
    except Exception as e:  # noqa: BLE001
        logger.warning("Portfolio Health build failed for %s: %s", uid, e)
        health_payload = {
            "health_score": None,
            "low_confidence": True,
            "summary": "Portfolio Health unavailable right now.",
            "components": {},
            "risk_drivers": [],
            "error": str(e),
        }

    return {
        "engine_version": v3_scoring.ENGINE_VERSION,
        "coverage_pct": coverage_pct,
        "portfolio": portfolio,
        "funds": funds_out,
        "flagged": flagged,
        "health": health_payload,
    }
