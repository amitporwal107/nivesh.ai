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

from fastapi import APIRouter, Query, Request

from deps import db, get_current_user
import feature_flags as _ff

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


# Universal template catalog — shown to all personas. Each entry now carries:
#   personas:        None  → matches all personas (universal)
#                    list  → only included when the user's persona is in the list
#   intent_category: one of the 5 product taxonomy buckets:
#                    portfolio_health | performance | risk_diversification | tax | goal_planning
_PROMPT_TEMPLATES: List[Dict[str, Any]] = [
    {
        "id": "fix_portfolio",
        "personas": None,
        "intent_category": "portfolio_health",
        "bucket": "fix",
        "tier": "primary",
        "label": "Let's clean up my portfolio",
        "outcome": "Get 3 tax-smart actions to fix overlap, cost, and risk",
        "query": "Fix my portfolio. What are the top 3 actions I should take based on my current holdings? Include estimated tax impact and annual savings.",
        "icon": "Wrench",
        "color": "rose",
        "scorer": _score_fix_portfolio,
    },
    {
        "id": "overlap",
        "personas": None,
        "intent_category": "risk_diversification",
        "bucket": "fix",
        "tier": "secondary",
        "label": "Fix overlap in my funds",
        "outcome": "Find duplicate funds and which to exit with lowest tax hit",
        "query": "Which funds or stocks in my portfolio are overlapping the most, and which ones should I remove with minimal tax impact?",
        "icon": "Layers",
        "color": "purple",
        "scorer": _score_overlap,
    },
    {
        "id": "risk_allocation",
        "personas": None,
        "intent_category": "risk_diversification",
        "bucket": "risk",
        "tier": "secondary",
        "label": "Rebalance my risk",
        "outcome": "See equity/debt/gold mix and a rebalance plan",
        "query": "Is my portfolio properly balanced across equity, debt, and gold? What should I change to reduce volatility without hurting returns?",
        "icon": "Shield",
        "color": "sky",
        "scorer": _score_risk_alloc,
    },
    {
        "id": "exit_lowest_tax",
        "personas": None,
        "intent_category": "tax",
        "bucket": "exit",
        "tier": "secondary",
        "label": "Which fund should I exit first",
        "outcome": "Rank my funds by exit-priority and show tax savings",
        "query": "If I want to exit some investments, which ones should I sell first with the lowest tax impact? Show tax-aware analysis.",
        "icon": "ArrowRightCircle",
        "color": "amber",
        "scorer": _score_exit,
    },
    {
        "id": "where_to_invest",
        "personas": None,
        "intent_category": "portfolio_health",
        "bucket": "add",
        "tier": "secondary",
        "label": "Where should I invest ₹1L",
        "outcome": "Get a specific fund suggestion that fills my portfolio gaps",
        "query": "Based on my current portfolio gaps, where should I invest ₹1 lakh of fresh money to improve diversification?",
        "icon": "TrendingUp",
        "color": "emerald",
        "scorer": _score_add,
    },
    {
        "id": "performance",
        "personas": None,
        "intent_category": "performance",
        "bucket": "deep",
        "tier": "advanced",
        "label": "Find my weak performers",
        "outcome": "Spot funds lagging their benchmark and get replacements",
        "query": "Which investments in my portfolio are underperforming their benchmarks? Should I replace them?",
        "icon": "BarChart3",
        "color": "violet",
        "scorer": _score_performance,
    },
    {
        "id": "concentration",
        "personas": None,
        "intent_category": "risk_diversification",
        "bucket": "risk",
        "tier": "advanced",
        "label": "Check my concentration risk",
        "outcome": "See if any sector, stock, or AMC is eating too much of my portfolio",
        "query": "Am I overexposed to any single sector, stock, or fund house? Show me the concentration risk and how to reduce it.",
        "icon": "AlertTriangle",
        "color": "red",
        "scorer": _score_concentration,
    },
    {
        "id": "what_if",
        "personas": None,
        "intent_category": "portfolio_health",
        "bucket": "deep",
        "tier": "advanced",
        "label": "Simulate my plan",
        "outcome": "Preview how my portfolio changes if I follow every action",
        "query": "What happens if I follow your recommended actions? How will my portfolio look after — show before vs after allocation, risk, and expected returns.",
        "icon": "Zap",
        "color": "indigo",
        "scorer": _score_what_if,
    },
    {
        "id": "tax_optimize",
        "personas": None,
        "intent_category": "tax",
        "bucket": "deep",
        "tier": "advanced",
        "label": "Optimise my taxes",
        "outcome": "Minimise STCG/LTCG on any rebalance + surface 80C opportunities",
        "query": "How can I optimise taxes in my portfolio if I rebalance now? Include STCG/LTCG breakdown and 80C opportunities.",
        "icon": "Lightbulb",
        "color": "yellow",
        "scorer": _score_tax,
    },
    {
        "id": "long_term",
        "personas": None,
        "intent_category": "goal_planning",
        "bucket": "deep",
        "tier": "advanced",
        "label": "Am I on track for long-term wealth",
        "outcome": "Check if my mix fits a 10-year compounding goal",
        "query": "Is my portfolio aligned with long-term wealth creation (10+ year horizon)? What should I change today to get there?",
        "icon": "Target",
        "color": "teal",
        "scorer": _score_long_term,
    },
]


# Merge persona-specific templates from the catalog module so the routing logic
# below sees one unified list. The persona catalog adds 99 entries covering the
# 10 product personas × 5 holdings + 5 general questions each (active_trader
# Q5 is hidden until P3 ships the win-rate / risk-reward primitive).
try:
    from .copilot_prompt_catalog import PERSONA_TEMPLATES as _PERSONA_TEMPLATES
    _PROMPT_TEMPLATES.extend(_PERSONA_TEMPLATES)
except Exception as _persona_import_err:  # noqa: BLE001
    logger.warning("persona prompt catalog unavailable: %s", _persona_import_err)
    _PERSONA_TEMPLATES = []


# ──────────────────────────────────────────────────────────────────────────
# Portfolio context builder
# ──────────────────────────────────────────────────────────────────────────

async def _build_context(user_id: str) -> Dict[str, Any]:
    """Collect all the signals we score prompts against for this user."""
    ctx: Dict[str, Any] = {
        "total_value": 0,
        "equity_pct": 0,
        "debt_pct": 0,
        "gold_pct": 0,
        "other_pct": 0,
        "max_overlap_pct": 0,
        "overlap_pair_count": 0,
        "top_overlaps": [],         # [{a, b, overlap_pct}, ...] top 3
        "top_amc_name": None,
        "top_amc_pct": 0,
        "top_amcs": [],             # [{name, pct}, ...] top 3
        "action_count": 0,
        "has_exit_actions": False,
        "plan_tax_liability": 0,
        "underperformer_count": 0,
        "fund_count": 0,
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
            ctx["gold_pct"] = alloc.get("gold_pct", 0) or 0
            # Derive other_pct as the residual if not explicitly returned
            explicit_other = alloc.get("other_pct")
            if explicit_other is not None:
                ctx["other_pct"] = explicit_other
            elif alloc:
                ctx["other_pct"] = max(0, round(
                    100 - ctx["equity_pct"] - ctx["debt_pct"] - ctx["gold_pct"], 1
                ))
            else:
                # intel didn't give allocation — leave 0; fallback block will recompute
                ctx["other_pct"] = 0
            # Overlap — keep top pairs for viz
            pairs = intel.get("pairwise_overlap") or []
            if pairs:
                ctx["overlap_pair_count"] = len(pairs)
                sorted_pairs = sorted(pairs, key=lambda p: p.get("overlap_pct", 0), reverse=True)
                ctx["max_overlap_pct"] = sorted_pairs[0].get("overlap_pct", 0) if sorted_pairs else 0
                ctx["top_overlaps"] = [
                    {
                        "a": (p.get("fund_a") or p.get("a") or "Fund A")[:28],
                        "b": (p.get("fund_b") or p.get("b") or "Fund B")[:28],
                        "overlap_pct": round(p.get("overlap_pct", 0) or 0, 1),
                    }
                    for p in sorted_pairs[:3]
                ]
            # AMC concentration — pick top 3
            amc_exposure = intel.get("amc_exposure") or {}
            if amc_exposure:
                sorted_amcs = sorted(amc_exposure.items(), key=lambda x: x[1], reverse=True)
                ctx["top_amc_name"] = sorted_amcs[0][0]
                ctx["top_amc_pct"] = round(sorted_amcs[0][1] or 0, 1)
                ctx["top_amcs"] = [
                    {"name": name[:20], "pct": round(pct or 0, 1)}
                    for name, pct in sorted_amcs[:3]
                ]
            ctx["fund_count"] = len(intel.get("dedup_holdings") or intel.get("holdings") or [])
    except Exception as e:
        logger.debug("portfolio_intelligence unavailable: %s", e)

    # If intelligence didn't give allocation, fall back to holdings-based calc
    if ctx["total_value"] <= 0:
        holdings = await db.holdings.find({"user_id": user_id}, {"_id": 0}).to_list(2000)
        if not holdings:
            from services.pi_bridge import pi_holdings_for_user  # noqa: WPS433
            holdings = await pi_holdings_for_user(user_id)
        total = 0.0
        equity = 0.0
        debt = 0.0
        gold = 0.0
        other = 0.0
        for h in holdings:
            val = float(h.get("quantity", 0) or 0) * float(h.get("current_price", 0) or 0)
            if val <= 0:
                continue
            total += val
            at = (h.get("asset_type") or "").lower()
            name = (h.get("name") or "").lower()
            # ── Gold bucket (SGBs, gold ETFs, gold MF) ──
            if at == "gold" or "gold" in name or "sgb" in name or "sovereign gold" in name:
                gold += val
                continue
            # ── Debt bucket (bonds, debt MF/ETF, FDs) ──
            is_debt_mf_or_etf = at in ("mutual_fund", "etf") and any(
                k in name for k in [
                    "liquid", "gilt", "bond", "corporate bond", "short term",
                    "overnight", "banking & psu", "low duration", "ultra short",
                    "medium duration", "long duration", "credit risk",
                    "floater", "dynamic bond", "debt",
                ]
            )
            if at in ("bond", "debt", "fd", "deposit") or is_debt_mf_or_etf:
                debt += val
                continue
            # ── Equity bucket (equity MF, stocks, equity ETFs) ──
            if at in ("equity", "stock", "mutual_fund", "mutual fund", "etf"):
                equity += val
                continue
            # ── Everything else (NPS, cash, REITs, AIFs) ──
            other += val
        ctx["total_value"] = total
        if total > 0:
            ctx["equity_pct"] = round(equity / total * 100, 1)
            ctx["debt_pct"] = round(debt / total * 100, 1)
            ctx["gold_pct"] = round(gold / total * 100, 1)
            ctx["other_pct"] = round(other / total * 100, 1)

    # Active plan — actions count, exit flag, tax liability
    try:
        plan = await db.action_plans.find_one(
            {"user_id": user_id, "status": "active"},
            {"_id": 0, "actions": 1, "total_tax_impact": 1, "tax_impact": 1},
            sort=[("created_at", -1)],
        )
        if plan:
            actions = plan.get("actions") or []
            ctx["action_count"] = len(actions)
            ctx["has_exit_actions"] = any((a.get("type") == "EXIT") for a in actions)
            tax = plan.get("total_tax_impact") or plan.get("tax_impact") or {}
            ctx["plan_tax_liability"] = tax.get("total_tax_liability") or tax.get("total_tax") or 0
            # Underperformer count from action reason codes
            ctx["underperformer_count"] = sum(
                1 for a in actions
                if "UNDERPERFORMER_REPLACEMENT" in (a.get("reason_codes") or [])
            )
    except Exception as e:
        logger.debug("active plan read failed: %s", e)

    return ctx


# ──────────────────────────────────────────────────────────────────────────
# API
# ──────────────────────────────────────────────────────────────────────────

# Color palette — mirrors frontend Insights Dashboard theme (emerald/sky/amber/rose…)
_VIZ_PALETTE = {
    "equity": "#10b981",    # emerald-500
    "debt":   "#0ea5e9",    # sky-500
    "gold":   "#f59e0b",    # amber-500
    "other":  "#94a3b8",    # slate-400
    "danger": "#ef4444",    # red-500
    "warn":   "#f97316",    # orange-500
    "accent": "#8b5cf6",    # violet-500
    "pos":    "#10b981",
    "neg":    "#ef4444",
    "muted":  "#cbd5e1",
}


def _build_viz_for_prompt(prompt_id: str, ctx: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return a compact viz payload for a prompt card.

    Schema:
      { "kind": "donut"|"bar"|"gauge"|"stat"|"split",
        "series": [ {"label":str, "value":float, "color":str} ],
        "headline": str,             # large number shown on the card
        "caption": str }             # tiny descriptor
    Returns None when no portfolio data is available to visualise.
    """
    total = ctx.get("total_value", 0) or 0
    if total <= 0:
        return None

    eq = ctx.get("equity_pct", 0) or 0
    dt = ctx.get("debt_pct", 0) or 0
    gd = ctx.get("gold_pct", 0) or 0
    ot = ctx.get("other_pct", 0) or max(0, 100 - eq - dt - gd)

    # Defensive rounding for display
    eq_r, dt_r, gd_r, ot_r = round(eq, 1), round(dt, 1), round(gd, 1), round(ot, 1)

    if prompt_id == "fix_portfolio":
        # Donut of current asset-mix with action_count as headline
        actions = ctx.get("action_count", 0) or 0
        return {
            "kind": "donut",
            "series": [
                {"label": "Equity", "value": eq_r, "color": _VIZ_PALETTE["equity"]},
                {"label": "Debt",   "value": dt_r, "color": _VIZ_PALETTE["debt"]},
                {"label": "Gold",   "value": gd_r, "color": _VIZ_PALETTE["gold"]},
                {"label": "Other",  "value": ot_r, "color": _VIZ_PALETTE["other"]},
            ],
            "headline": f"{actions}" if actions else f"{eq_r:.0f}%",
            "caption": f"{actions} actions pending" if actions else "Asset mix today",
        }

    if prompt_id == "risk_allocation":
        return {
            "kind": "donut",
            "series": [
                {"label": "Equity", "value": eq_r, "color": _VIZ_PALETTE["equity"]},
                {"label": "Debt",   "value": dt_r, "color": _VIZ_PALETTE["debt"]},
                {"label": "Gold",   "value": gd_r, "color": _VIZ_PALETTE["gold"]},
                {"label": "Other",  "value": ot_r, "color": _VIZ_PALETTE["other"]},
            ],
            "headline": f"{eq_r:.0f}%",
            "caption": "Equity share",
        }

    if prompt_id == "overlap":
        pairs = ctx.get("top_overlaps") or []
        if not pairs:
            return None
        return {
            "kind": "bar",
            "series": [
                {
                    "label": f"{p['a']} × {p['b']}",
                    "value": p["overlap_pct"],
                    "color": _VIZ_PALETTE["accent"] if p["overlap_pct"] >= 60 else _VIZ_PALETTE["muted"],
                }
                for p in pairs
            ],
            "headline": f"{ctx.get('max_overlap_pct', 0):.0f}%",
            "caption": f"{len(pairs)} overlapping pairs",
        }

    if prompt_id == "concentration":
        amcs = ctx.get("top_amcs") or []
        if not amcs:
            return None
        return {
            "kind": "bar",
            "series": [
                {
                    "label": a["name"],
                    "value": a["pct"],
                    "color": _VIZ_PALETTE["danger"] if a["pct"] >= 25 else (_VIZ_PALETTE["warn"] if a["pct"] >= 15 else _VIZ_PALETTE["muted"]),
                }
                for a in amcs
            ],
            "headline": f"{ctx.get('top_amc_pct', 0):.0f}%",
            "caption": f"in {ctx.get('top_amc_name') or 'top AMC'}",
        }

    if prompt_id == "where_to_invest":
        # Gauge: debt gap vs target 25%
        target = 25.0
        gap = max(0, target - dt_r)
        return {
            "kind": "gauge",
            "series": [
                {"label": "Debt today", "value": dt_r, "color": _VIZ_PALETTE["debt"]},
                {"label": "Gap to target", "value": gap, "color": _VIZ_PALETTE["muted"]},
            ],
            "headline": f"{dt_r:.0f}%",
            "caption": f"Debt today · target {target:.0f}%",
        }

    if prompt_id == "exit_lowest_tax":
        actions = ctx.get("action_count", 0) or 0
        if not actions:
            return None
        return {
            "kind": "stat",
            "series": [],
            "headline": f"{actions}",
            "caption": "Tax-smart exits ready",
        }

    if prompt_id == "performance":
        underp = ctx.get("underperformer_count", 0) or 0
        return {
            "kind": "split",
            "series": [
                {"label": "Weak",   "value": underp,                       "color": _VIZ_PALETTE["neg"]},
                {"label": "Strong", "value": max(0, (ctx.get('fund_count', 0) or 0) - underp), "color": _VIZ_PALETTE["pos"]},
            ],
            "headline": f"{underp}",
            "caption": "Underperforming funds",
        }

    if prompt_id == "what_if":
        actions = ctx.get("action_count", 0) or 0
        return {
            "kind": "stat",
            "series": [],
            "headline": f"{actions}",
            "caption": "Actions to simulate",
        }

    if prompt_id == "tax_optimize":
        tax = ctx.get("plan_tax_liability", 0) or 0
        return {
            "kind": "stat",
            "series": [],
            "headline": f"₹{tax/1000:.0f}k" if tax >= 1000 else f"₹{int(tax)}",
            "caption": "Est. tax liability",
        }

    if prompt_id == "long_term":
        # A simple progress — equity share as a proxy for long-term alignment
        return {
            "kind": "gauge",
            "series": [
                {"label": "Equity",  "value": eq_r,          "color": _VIZ_PALETTE["equity"]},
                {"label": "Non-equity", "value": max(0, 100 - eq_r), "color": _VIZ_PALETTE["muted"]},
            ],
            "headline": f"{eq_r:.0f}%",
            "caption": "Equity tilt (10y)",
        }

    return None


def _advisor_prompts() -> Dict[str, Any]:
    """Curated cross-client prompts for advisors viewing the workspace
    dashboard (i.e. NOT impersonating a single client). Surfaced on the
    floating Nivesh Copilot in MFD/advisory mode."""
    primary = [{
        "id": "advisor_call_today", "tier": "primary", "bucket": "advisor_today",
        "label": "Which clients should I call today?",
        "outcome": "Top 10 high-priority clients with the recommended action for each.",
        "query": "Give me my top 10 high-priority clients today — for each, name, the issue, and the recommended action.",
        "icon": "Phone", "color": "indigo", "badge": "Daily brief",
    }]
    secondary = [
        {"id": "advisor_top_aum", "tier": "secondary", "bucket": "advisor_aum",
         "label": "Who are my top clients by AUM?",
         "outcome": "Ranked AUM list with month-over-month change.",
         "query": "Rank my clients by AUM. Show their name, AUM, and how it moved this month.",
         "icon": "TrendingUp", "color": "emerald", "badge": None},
        {"id": "advisor_underperformers", "tier": "secondary", "bucket": "advisor_perf",
         "label": "Which clients are underperforming the benchmark?",
         "outcome": "Clients lagging NIFTY 50 by >5% with the size of the gap.",
         "query": "Show clients whose portfolios are lagging NIFTY 50 by more than 5%. Include AUM and gap size.",
         "icon": "TrendingDown", "color": "rose", "badge": None},
        {"id": "advisor_rebalance", "tier": "secondary", "bucket": "advisor_rebalance",
         "label": "Who needs rebalancing now?",
         "outcome": "Clients deviating >10% from their target allocation.",
         "query": "Which clients are deviating more than 10% from their target allocation? List the bucket that is off.",
         "icon": "Scale", "color": "amber", "badge": None},
    ]
    advanced = [
        {"id": "advisor_concentration", "tier": "advanced", "bucket": "advisor_risk",
         "label": "Who has >40% in a single fund or stock?",
         "outcome": "Concentration risk — clients with one position dominating their book.",
         "query": "List clients with more than 40% of their portfolio in a single fund or stock. Show the position and weight.",
         "icon": "AlertTriangle", "color": "rose", "badge": None},
        {"id": "advisor_idle_cash", "tier": "advanced", "bucket": "advisor_opp",
         "label": "Where can I generate additional investments today?",
         "outcome": "Clients with idle cash > ₹2L or surplus capacity.",
         "query": "Which clients have idle cash above ₹2 lakh or capacity to add to their SIP today?",
         "icon": "Sparkles", "color": "indigo", "badge": None},
        {"id": "advisor_stopped_sips", "tier": "advanced", "bucket": "advisor_churn",
         "label": "Which clients stopped their SIPs recently?",
         "outcome": "Churn-risk signal — recent SIP drop-offs need a touchpoint.",
         "query": "Which of my clients have stopped or paused SIPs in the last 3 months? Show last contribution date.",
         "icon": "AlertTriangle", "color": "amber", "badge": None},
    ]
    return {
        "mode": "advisor",
        "prompts": primary + secondary + advanced,
        "primary": primary,
        "secondary": secondary,
        "advanced": advanced,
        "journey": "advisor",
        "context_summary": {},
    }


def _investor_prompts_curated() -> List[Dict[str, Any]]:
    """Always-on investor prompts as a base layer. Returned alongside the
    portfolio-context-driven scored prompts so a brand-new individual user
    has something useful to click even before holdings are scored."""
    return [
        {"id": "investor_health_drop", "tier": "secondary", "bucket": "investor",
         "label": "Why is my health score where it is?",
         "outcome": "Plain-English breakdown of the 4 health components.",
         "query": "Why is my portfolio health score what it is? Walk me through each component.",
         "icon": "ShieldCheck", "color": "indigo"},
        {"id": "investor_biggest_risk", "tier": "secondary", "bucket": "investor",
         "label": "What's the single biggest risk in my portfolio?",
         "outcome": "The one issue most worth fixing first.",
         "query": "What is the single biggest risk in my portfolio right now and how do I fix it?",
         "icon": "AlertTriangle", "color": "rose"},
        {"id": "investor_tax_moves", "tier": "advanced", "bucket": "investor_tax",
         "label": "What tax moves should I consider this FY?",
         "outcome": "LTCG/STCG-aware suggestions tied to my actual holdings.",
         "query": "What tax moves should I consider this financial year given my current holdings?",
         "icon": "Receipt", "color": "emerald"},
    ]


async def _is_advisor_mode(session_user_id: str, calling_user_id: str) -> bool:
    """True when the caller's session belongs to an ADVISORY workspace
    AND they are NOT currently impersonating a specific client (i.e. the
    caller's user_id matches their own session_user_id)."""
    if session_user_id != calling_user_id:
        return False
    try:
        ws = await db.workspaces.find_one(
            {"owner_user_id": session_user_id}, {"_id": 0, "type": 1},
        )
    except Exception:  # noqa: BLE001
        return False
    return bool(ws and (ws.get("type") or "").upper() == "ADVISORY")


_PERSONA_PROMPTS_FLAG = "copilot_persona_prompts_enabled"
_DEFAULT_PERSONA = "retail_investor"
_VALID_CATEGORIES = {
    "portfolio_health", "performance", "risk_diversification", "tax", "goal_planning",
}


async def _resolve_persona(user_id: str, override: Optional[str]) -> str:
    """Pick the persona to use for prompt filtering.

    Priority:
      1. Explicit `persona` query param (override — used by the welcome screen
         when it has already inferred a persona from the upload signal).
      2. The persona persisted on `user_profiles.persona.persona` by the
         persona_engine.
      3. Fallback to `retail_investor`.
    """
    if override:
        return override
    try:
        prof = await db.user_profiles.find_one({"user_id": user_id}, {"_id": 0, "persona": 1})
        if prof:
            block = prof.get("persona") or {}
            if isinstance(block, dict) and block.get("persona"):
                return block["persona"]
            if isinstance(block, str) and block:
                return block
    except Exception as e:  # noqa: BLE001
        logger.debug("persona lookup failed for %s: %s", user_id, e)
    return _DEFAULT_PERSONA


def _matches_persona(tpl: Dict[str, Any], persona: str) -> bool:
    """A template is shown to a persona when its `personas` field is None
    (universal) or contains the user's persona code."""
    personas = tpl.get("personas")
    if not personas:
        return True
    return persona in personas


def _matches_category(tpl: Dict[str, Any], category: Optional[str]) -> bool:
    if not category:
        return True
    return tpl.get("intent_category") == category


@router.get("/copilot/suggested-prompts")
async def suggested_prompts(
    request: Request,
    persona: Optional[str] = Query(default=None, description="Persona override (PersonaType.value). Defaults to user's stored persona."),
    category: Optional[str] = Query(default=None, description="Filter to one of: portfolio_health|performance|risk_diversification|tax|goal_planning"),
) -> Dict[str, Any]:
    """Return the top 5 most relevant prompts for this user right now,
    grouped into 3 tiers: primary (1) · secondary (2-3) · advanced (collapsed).

    Two modes:
      • Advisor (ADVISORY workspace, not impersonating) → cross-client
        prompts (top AUM, who needs a call, underperformers, …).
      • Individual investor (or advisor while impersonating a client) →
        portfolio-context-driven prompts based on the actual holdings,
        filtered by persona and (optional) intent category.
    """
    user = await get_current_user(request)
    session_uid = user.get("_session_user_id") or user["user_id"]
    if await _is_advisor_mode(session_uid, user["user_id"]):
        return _advisor_prompts()

    # Validate category param early — silently ignore unknowns so the UI can
    # send anything without breaking the response.
    if category and category not in _VALID_CATEGORIES:
        category = None

    persona_prompts_on = _ff.is_enabled(_PERSONA_PROMPTS_FLAG, user.get("email"))
    resolved_persona = await _resolve_persona(user["user_id"], persona) if persona_prompts_on else None

    ctx = await _build_context(user["user_id"])

    # User-journey awareness — affects which prompt becomes "primary"
    total_value = ctx.get("total_value", 0)
    action_count = ctx.get("action_count", 0)
    try:
        chat_sessions = await db.chat_sessions.count_documents({"user_id": user["user_id"]})
    except Exception:
        chat_sessions = 0
    is_first_time = (chat_sessions == 0 and total_value > 0)
    has_active_plan = action_count > 0
    if is_first_time:
        journey = "first_time"
    elif has_active_plan:
        journey = "post_action"   # user has an existing plan → nudge them to act
    else:
        journey = "returning"

    scored = []
    for tpl in _PROMPT_TEMPLATES:
        # Persona filter — only applied when the persona feature flag is on.
        # When off, the original universal behaviour is preserved (persona-tagged
        # templates are skipped so we don't accidentally surface them).
        if persona_prompts_on:
            if not _matches_persona(tpl, resolved_persona):
                continue
        else:
            if tpl.get("personas"):
                continue

        # Category filter (optional)
        if not _matches_category(tpl, category):
            continue

        score, badge = tpl["scorer"](ctx)
        if score <= 0:
            continue
        # Journey boost — primary prompt stays primary, but first-time users
        # get an explicit "Start here" nudge on fix_portfolio
        if journey == "first_time" and tpl["id"] == "fix_portfolio":
            score += 20  # lock it to the very top
        # Persona-match boost — without this, universal templates with rich
        # portfolio-signal scorers (overlap %, AMC concentration, etc.) sweep
        # every tier slot and no persona-tagged prompts ever surface. The
        # boost lets persona templates compete on equal footing while still
        # allowing a strong universal signal (e.g. 100% fund overlap) to win.
        if (
            persona_prompts_on
            and tpl.get("personas")
            and resolved_persona in tpl["personas"]
        ):
            score += 35
        scored.append({
            "id": tpl["id"],
            "bucket": tpl["bucket"],
            "tier": tpl.get("tier", "secondary"),
            "intent_category": tpl.get("intent_category"),
            "personas": tpl.get("personas"),
            "label": tpl["label"],
            "outcome": tpl.get("outcome", ""),
            "query": tpl["query"],
            "icon": tpl["icon"],
            "color": tpl["color"],
            "badge": badge,
            "score": score,
            "viz": _build_viz_for_prompt(tpl["id"], ctx),
        })
    scored.sort(key=lambda p: p["score"], reverse=True)

    # Enforce tier shape: 1 primary · 2-3 secondary · up to 3 advanced (collapsed)
    primary = [p for p in scored if p["tier"] == "primary"][:1]
    secondary = [p for p in scored if p["tier"] == "secondary"][:3]
    advanced = [p for p in scored if p["tier"] == "advanced"][:3]

    # Persona-floor — guarantee at least one persona-tagged prompt is visible
    # in the secondary tier whenever the user has a recognised persona and
    # persona templates exist for them. Without this floor, an extreme universal
    # signal (e.g. 100% fund overlap or a flagged sector concentration) can
    # still sweep all three secondary slots even after the +35 score boost.
    if persona_prompts_on and resolved_persona and resolved_persona != _DEFAULT_PERSONA:
        has_persona_in_secondary = any(p.get("personas") for p in secondary)
        if not has_persona_in_secondary:
            top_persona_secondary = next(
                (p for p in scored if p["tier"] == "secondary" and p.get("personas")),
                None,
            )
            if top_persona_secondary:
                # drop the lowest-scoring universal secondary, insert persona at end
                secondary = [p for p in secondary if not p.get("personas")][:2]
                secondary.append(top_persona_secondary)

    # If no primary slot filled, elevate the top secondary
    if not primary and secondary:
        promoted = secondary.pop(0)
        promoted["tier"] = "primary"
        primary = [promoted]

    ordered = primary + secondary + advanced
    top = ordered[:_MAX_PROMPTS + 3]  # primary(1) + secondary(up to 3) + advanced(up to 3) → ~7 max
    return {
        "mode": "investor",
        "prompts": top,
        "journey": journey,
        "persona": resolved_persona,
        "persona_prompts_enabled": persona_prompts_on,
        "category_filter": category,
        "primary": primary,
        "secondary": secondary,
        "advanced": advanced,
        "context_summary": {
            "total_value": ctx["total_value"],
            "equity_pct": ctx["equity_pct"],
            "debt_pct": ctx["debt_pct"],
            "gold_pct": ctx["gold_pct"],
            "other_pct": ctx["other_pct"],
            "top_amc_name": ctx["top_amc_name"],
            "top_amc_pct": ctx["top_amc_pct"],
            "top_amcs": ctx["top_amcs"],
            "max_overlap_pct": ctx["max_overlap_pct"],
            "top_overlaps": ctx["top_overlaps"],
            "action_count": ctx["action_count"],
            "has_exit_actions": ctx["has_exit_actions"],
            "plan_tax_liability": ctx["plan_tax_liability"],
            "underperformer_count": ctx["underperformer_count"],
            "fund_count": ctx["fund_count"],
        },
    }
