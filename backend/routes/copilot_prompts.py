"""Context-aware AI Copilot prompt suggestions.

Takes the user's portfolio signals (overlap, AMC concentration, asset mix,
cost-leak, action-plan state, under-performers) and returns the TOP 5 most
relevant prompt templates — with context-enriched badges — so the user can
ask the "right" financial question without typing.

Grouped into 5 buckets:
  1. Fix my portfolio      (highest-intent, maps to Plan Board)
  2. Risk & allocation
  3. Exit decisions
  4. Add / investment decisions
  5. Deep insights
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request

from deps import db, get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

_MAX_PROMPTS = 5


# ──────────────────────────────────────────────────────────────────────────
# Prompt catalog — 10 templates across 5 buckets, each with a scorer.
# Each scorer returns: (score, badge_text_or_None).
# Higher score = more relevant to this user.
# ──────────────────────────────────────────────────────────────────────────

def _score_fix_portfolio(ctx: Dict[str, Any]) -> tuple:
    """'Fix my portfolio' — always high priority if user has holdings."""
    total = ctx.get("total_value", 0)
    action_count = ctx.get("action_count", 0)
    if total <= 0:
        return (0, None)
    # Boost when there are active actions
    base = 100 if action_count > 0 else 80
    badge = f"{action_count} actions pending" if action_count else None
    return (base, badge)


def _score_overlap(ctx: Dict[str, Any]) -> tuple:
    max_overlap = ctx.get("max_overlap_pct", 0)
    overlap_pairs = ctx.get("overlap_pair_count", 0)
    if max_overlap < 40:
        return (0, None)
    # 40-59% → 40-59 pts; 60-79 → 70-90; 80+ → 95+
    score = min(100, int(max_overlap))
    badge = f"Top pair {max_overlap:.0f}% overlap" if overlap_pairs else None
    return (score, badge)


def _score_risk_alloc(ctx: Dict[str, Any]) -> tuple:
    equity_pct = ctx.get("equity_pct", 0)
    debt_pct = ctx.get("debt_pct", 0)
    if equity_pct > 85 or debt_pct < 10:
        badge = f"Equity {equity_pct:.0f}% · Debt {debt_pct:.0f}%"
        return (90, badge)
    if equity_pct > 75:
        return (60, f"Equity {equity_pct:.0f}%")
    return (30, None)


def _score_exit(ctx: Dict[str, Any]) -> tuple:
    has_exit_actions = ctx.get("has_exit_actions", False)
    total = ctx.get("total_value", 0)
    if total <= 0:
        return (0, None)
    if has_exit_actions:
        return (80, "Tax-optimised exits available")
    return (40, None)


def _score_add(ctx: Dict[str, Any]) -> tuple:
    debt_pct = ctx.get("debt_pct", 0)
    if debt_pct < 10:
        return (75, f"Debt gap — only {debt_pct:.0f}%")
    return (45, None)


def _score_performance(ctx: Dict[str, Any]) -> tuple:
    underperformers = ctx.get("underperformer_count", 0)
    if underperformers >= 2:
        return (80, f"{underperformers} underperformers")
    if underperformers == 1:
        return (60, "1 underperformer")
    return (25, None)


def _score_concentration(ctx: Dict[str, Any]) -> tuple:
    top_amc_pct = ctx.get("top_amc_pct", 0)
    top_amc = ctx.get("top_amc_name")
    if top_amc_pct >= 25 and top_amc:
        return (85, f"{top_amc} {top_amc_pct:.0f}%")
    if top_amc_pct >= 15:
        return (55, f"{top_amc} {top_amc_pct:.0f}%")
    return (20, None)


def _score_what_if(ctx: Dict[str, Any]) -> tuple:
    action_count = ctx.get("action_count", 0)
    if action_count >= 3:
        return (70, f"Simulate {action_count} actions")
    return (30, None)


def _score_tax(ctx: Dict[str, Any]) -> tuple:
    total = ctx.get("total_value", 0)
    tax_liability = ctx.get("plan_tax_liability", 0)
    if tax_liability and tax_liability > 0:
        return (65, f"Est. tax ₹{tax_liability:,.0f}")
    if total > 500000:
        return (45, None)
    return (20, None)


def _score_long_term(ctx: Dict[str, Any]) -> tuple:
    total = ctx.get("total_value", 0)
    if total > 0:
        return (35, None)
    return (0, None)


# Template catalog
_PROMPT_TEMPLATES: List[Dict[str, Any]] = [
    {
        "id": "fix_portfolio",
        "bucket": "fix",
        "label": "Fix My Portfolio",
        "query": "Fix my portfolio. What are the top 3 actions I should take based on my current holdings?",
        "icon": "Wrench",
        "color": "rose",
        "scorer": _score_fix_portfolio,
    },
    {
        "id": "overlap",
        "bucket": "fix",
        "label": "Reduce Overlap",
        "query": "Which funds or stocks in my portfolio are overlapping the most, and which ones should I remove with minimal tax impact?",
        "icon": "Layers",
        "color": "purple",
        "scorer": _score_overlap,
    },
    {
        "id": "risk_allocation",
        "bucket": "risk",
        "label": "Rebalance Risk",
        "query": "Is my portfolio properly balanced across equity, debt, and gold? What should I change to reduce volatility without hurting returns?",
        "icon": "Shield",
        "color": "sky",
        "scorer": _score_risk_alloc,
    },
    {
        "id": "exit_lowest_tax",
        "bucket": "exit",
        "label": "What to Sell First",
        "query": "If I want to exit some investments, which ones should I sell first with the lowest tax impact? Show tax-aware analysis.",
        "icon": "ArrowRightCircle",
        "color": "amber",
        "scorer": _score_exit,
    },
    {
        "id": "where_to_invest",
        "bucket": "add",
        "label": "Where to Invest ₹1L",
        "query": "Based on my current portfolio gaps, where should I invest ₹1 lakh of fresh money to improve diversification?",
        "icon": "TrendingUp",
        "color": "emerald",
        "scorer": _score_add,
    },
    {
        "id": "performance",
        "bucket": "deep",
        "label": "Find Underperformers",
        "query": "Which investments in my portfolio are underperforming their benchmarks? Should I replace them?",
        "icon": "BarChart3",
        "color": "violet",
        "scorer": _score_performance,
    },
    {
        "id": "concentration",
        "bucket": "risk",
        "label": "Concentration Risk",
        "query": "Am I overexposed to any single sector, stock, or fund house? Show me the concentration risk and how to reduce it.",
        "icon": "AlertTriangle",
        "color": "red",
        "scorer": _score_concentration,
    },
    {
        "id": "what_if",
        "bucket": "deep",
        "label": "What If I Follow The Plan",
        "query": "What happens if I follow your recommended actions? How will my portfolio look after — show before vs after allocation, risk, and expected returns.",
        "icon": "Zap",
        "color": "indigo",
        "scorer": _score_what_if,
    },
    {
        "id": "tax_optimize",
        "bucket": "deep",
        "label": "Optimise Taxes",
        "query": "How can I optimise taxes in my portfolio if I rebalance now? Include STCG/LTCG breakdown and 80C opportunities.",
        "icon": "Lightbulb",
        "color": "yellow",
        "scorer": _score_tax,
    },
    {
        "id": "long_term",
        "bucket": "deep",
        "label": "Long-Term Strategy",
        "query": "Is my portfolio aligned with long-term wealth creation (10+ year horizon)? What should I change today to get there?",
        "icon": "Target",
        "color": "teal",
        "scorer": _score_long_term,
    },
]


# ──────────────────────────────────────────────────────────────────────────
# Portfolio context builder
# ──────────────────────────────────────────────────────────────────────────

async def _build_context(user_id: str) -> Dict[str, Any]:
    """Collect all the signals we score prompts against for this user."""
    ctx: Dict[str, Any] = {
        "total_value": 0,
        "equity_pct": 0,
        "debt_pct": 0,
        "max_overlap_pct": 0,
        "overlap_pair_count": 0,
        "top_amc_name": None,
        "top_amc_pct": 0,
        "action_count": 0,
        "has_exit_actions": False,
        "plan_tax_liability": 0,
        "underperformer_count": 0,
    }

    # Portfolio intelligence — gives overlap, AMC, asset allocation
    try:
        from services import portfolio_intelligence as pi
        intel = await pi.compute_portfolio_intelligence(user_id)
        if intel:
            ctx["total_value"] = intel.get("total_value", 0) or 0
            # Asset allocation — sum MF+equity as "equity-like"
            alloc = intel.get("asset_allocation") or {}
            ctx["equity_pct"] = alloc.get("equity_pct", 0) or 0
            ctx["debt_pct"] = alloc.get("debt_pct", 0) or 0
            # Overlap
            pairs = intel.get("pairwise_overlap") or []
            if pairs:
                ctx["overlap_pair_count"] = len(pairs)
                ctx["max_overlap_pct"] = max((p.get("overlap_pct", 0) for p in pairs), default=0)
            # AMC concentration — pick top
            amc_exposure = intel.get("amc_exposure") or {}
            if amc_exposure:
                top = max(amc_exposure.items(), key=lambda x: x[1])
                ctx["top_amc_name"] = top[0]
                ctx["top_amc_pct"] = top[1]
    except Exception as e:
        logger.debug(f"portfolio_intelligence unavailable: {e}")

    # If intelligence didn't give allocation, fall back to holdings-based calc
    if ctx["total_value"] <= 0:
        holdings = await db.holdings.find({"user_id": user_id}, {"_id": 0}).to_list(2000)
        total = 0.0
        equity = 0.0
        debt = 0.0
        for h in holdings:
            val = float(h.get("quantity", 0) or 0) * float(h.get("current_price", 0) or 0)
            total += val
            at = (h.get("asset_type") or "").lower()
            if at in ("equity", "stock", "mutual_fund", "mutual fund"):
                equity += val
            elif "debt" in at or at == "bond":
                debt += val
        ctx["total_value"] = total
        if total > 0:
            ctx["equity_pct"] = round(equity / total * 100, 1)
            ctx["debt_pct"] = round(debt / total * 100, 1)

    # Active plan — actions count, exit flag, tax liability
    try:
        plan = await db.action_plans.find_one(
            {"user_id": user_id, "status": "active"},
            {"_id": 0, "actions": 1, "tax_impact": 1},
            sort=[("created_at", -1)],
        )
        if plan:
            actions = plan.get("actions") or []
            ctx["action_count"] = len(actions)
            ctx["has_exit_actions"] = any((a.get("type") == "EXIT") for a in actions)
            tax = plan.get("tax_impact") or {}
            ctx["plan_tax_liability"] = tax.get("total_tax_liability", 0) or 0
            # Underperformer count from action reason codes
            ctx["underperformer_count"] = sum(
                1 for a in actions
                if "UNDERPERFORMER_REPLACEMENT" in (a.get("reason_codes") or [])
            )
    except Exception as e:
        logger.debug(f"active plan read failed: {e}")

    return ctx


# ──────────────────────────────────────────────────────────────────────────
# API
# ──────────────────────────────────────────────────────────────────────────

@router.get("/copilot/suggested-prompts")
async def suggested_prompts(request: Request) -> Dict[str, Any]:
    """Return the top 5 most relevant prompts for this user right now."""
    user = await get_current_user(request)
    ctx = await _build_context(user["user_id"])

    scored = []
    for tpl in _PROMPT_TEMPLATES:
        score, badge = tpl["scorer"](ctx)
        if score <= 0:
            continue
        scored.append({
            "id": tpl["id"],
            "bucket": tpl["bucket"],
            "label": tpl["label"],
            "query": tpl["query"],
            "icon": tpl["icon"],
            "color": tpl["color"],
            "badge": badge,
            "score": score,
        })
    scored.sort(key=lambda p: p["score"], reverse=True)
    top = scored[:_MAX_PROMPTS]

    return {
        "prompts": top,
        "context_summary": {
            "total_value": ctx["total_value"],
            "equity_pct": ctx["equity_pct"],
            "debt_pct": ctx["debt_pct"],
            "top_amc_pct": ctx["top_amc_pct"],
            "max_overlap_pct": ctx["max_overlap_pct"],
            "action_count": ctx["action_count"],
        },
    }
