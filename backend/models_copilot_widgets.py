"""Widget envelope contracts — Doc 02 §2.3 + Doc 06 §6.8.

A widget envelope is what the frontend renders inside an assistant
chat bubble (or inside Dashboard / Insights / Holding drawer — same
component, same shape). Three rules govern this:

  1. Self-contained — never references surrounding conversation.
  2. Identical chrome — title + freshness + agent + CTA on every one.
  3. Two-tap depth — at most two interactions to detail or action.

The envelope's `data` payload is widget-specific (validated by the
matching Pydantic sub-model below). Optional `partial=True` on a
streaming chunk lets the frontend render a SkeletonCard with sections
filling in top-to-bottom; the final chunk flips `partial=False`.
"""
from __future__ import annotations

from typing import Any, List, Literal, Optional, Union
from pydantic import BaseModel, Field
from datetime import datetime


# ── Shared shape ──────────────────────────────────────────────

WidgetKind = Literal[
    "fund_card",
    "compare_table",
    "screener_results",
    "overlap_reveal",
    "sip_plan",
    "rebalance_plan",
    "tax_harvest",
    "tax_timing",
    "capital_gains_snapshot",
    "stress_test",
    "market_brief",
    "sector_rotation",
    "holding_insight",
    "alert_confirmation",
    "report_download",
    "action_card",
    "risk_suitability",
    "portfolio_var",
    "company_financials",
    "fd_comparison",
    "insight_card",
]

FreshnessState = Literal["live", "cached", "delayed", "eod", "stale"]


class FreshnessChip(BaseModel):
    state: FreshnessState
    last_updated: Optional[str] = None     # ISO-8601 string
    source: List[str] = Field(default_factory=list)
    age_seconds: Optional[int] = None
    confidence: Optional[float] = None     # 0..100 only for NIDP-derived


class AgentInfo(BaseModel):
    id: str
    label: str
    version: str = "v1"
    confidence: Optional[int] = None       # 0..100


class WidgetEnvelope(BaseModel):
    kind: WidgetKind
    title: str
    freshness: FreshnessChip
    agent: AgentInfo
    data: Any                              # validated by frontend per `kind`
    primary_cta: Optional[dict] = None     # {"label": "...", "action": "..."}
    suggestions: List[str] = Field(default_factory=list)
    partial: bool = False                  # true during streaming render


# ── Per-widget data payloads (minimum for Phase B critical 4) ──

class FundCardData(BaseModel):
    scheme_code: Optional[str] = None
    scheme_name: str
    category: Optional[str] = None
    plan_type: Optional[str] = None        # "Direct" | "Regular"
    nav: Optional[float] = None
    aum_cr: Optional[float] = None
    risk_label: Optional[str] = None
    verdict: Optional[str] = None          # "Strong Buy" | "Buy" | "Hold" | "Sell"
    verdict_score: Optional[int] = None    # 0..100
    why: List[str] = Field(default_factory=list)
    watch_outs: List[str] = Field(default_factory=list)
    returns: dict = Field(default_factory=dict)   # {"1Y": 28.2, "3Y": 19.4, ...}
    benchmark: Optional[str] = None
    alpha: Optional[float] = None
    expense_ratio: Optional[float] = None
    manager_tenure_years: Optional[float] = None
    # NIDP DaaS scorecard fields (populated when NIDP has data for this scheme)
    nidp_composite_score: Optional[float] = None    # 0–100
    nidp_quality_label: Optional[str] = None        # Elite | Good | Average | Below Average | Underperformer
    nidp_composite_rank: Optional[int] = None       # peer-group rank (1 = best)
    nidp_total_in_category: Optional[int] = None    # peer-group size
    nidp_top_position_pct: Optional[float] = None   # 0–1 (0.05 = top 5%)
    nidp_red_flags: List[str] = Field(default_factory=list)  # ⚠️ lifecycle event labels


class CompareRow(BaseModel):
    metric: str
    values: List[Optional[Union[str, float, int]]]
    best_index: Optional[int] = None
    worst_index: Optional[int] = None
    higher_is_better: bool = True


class CompareTableData(BaseModel):
    funds: List[str]                       # column headers (fund names)
    rows: List[CompareRow]
    verdict: Optional[str] = None
    differences_only_default: bool = False


class MarketBriefIndex(BaseModel):
    name: str
    value: float
    change_pct: float


class MarketBriefData(BaseModel):
    indices: List[MarketBriefIndex] = Field(default_factory=list)
    sector_heatmap: List[dict] = Field(default_factory=list)   # [{name, change_pct, tone}]
    breadth: Optional[dict] = None                              # {"advancing": int, "declining": int, "unchanged": int}
    fii_dii: Optional[dict] = None                              # {"fii_cr": float, "dii_cr": float, "net_cr": float}
    summary_bullets: List[str] = Field(default_factory=list)
    portfolio_impact: Optional[dict] = None                     # {"day_pnl_rs": float, "day_pnl_pct": float, "top_gainers": [...], "top_detractors": [...]}


class SipPlanAllocation(BaseModel):
    scheme_name: str
    monthly_amount: float
    rationale: str


class SipPlanData(BaseModel):
    monthly_budget: float
    allocations: List[SipPlanAllocation]
    why_these: List[str] = Field(default_factory=list)
    counter_points: List[str] = Field(default_factory=list)


# Action card — used everywhere (Dashboard top-3, Insights, Chat)
class ActionCardData(BaseModel):
    priority: Literal["HIGH", "MED", "LOW"] = "MED"
    title: str
    impact_line: str
    effort_label: Optional[str] = None          # "5 min", "needs review"
    savings_rs_year: Optional[float] = None
    rationale_summary: Optional[str] = None
    cta_label: str = "Open in Chat"
    cta_action: str = "discuss_in_chat"


# ── Rebalance Plan ────────────────────────────────────────────────
class RebalanceAction(BaseModel):
    action: Literal["BUY", "SELL", "SWITCH", "HOLD"]
    fund_name: str
    current_pct: Optional[float] = None
    target_pct: Optional[float] = None
    amount_rs: Optional[float] = None
    reason: Optional[str] = None


class RebalancePlanData(BaseModel):
    current_value_rs: Optional[float] = None
    actions: List[RebalanceAction] = Field(default_factory=list)
    net_rebalance_rs: Optional[float] = None
    estimated_tax_rs: Optional[float] = None
    summary: Optional[str] = None


# ── Tax Harvest Plan ───────────────────────────────────────────────
class TaxHarvestCandidate(BaseModel):
    fund_name: str
    units: Optional[float] = None
    current_value_rs: Optional[float] = None
    cost_basis_rs: Optional[float] = None
    gain_rs: float
    gain_type: Literal["LTCG", "STCG"]
    days_held: Optional[int] = None
    eligible: bool = True
    wash_sale_risk: bool = False


class TaxHarvestData(BaseModel):
    fy: str                                          # e.g. "FY 2025-26"
    ltcg_used_rs: float = 0
    ltcg_limit_rs: float = 100000
    ltcg_remaining_rs: float = 100000
    candidates: List[TaxHarvestCandidate] = Field(default_factory=list)
    total_harvestable_rs: Optional[float] = None
    warning: Optional[str] = None


# ── Stress Test ───────────────────────────────────────────────────
class StressTestBreakdown(BaseModel):
    fund_name: str
    current_value_rs: Optional[float] = None
    stressed_value_rs: Optional[float] = None
    drop_pct: float


class StressTestData(BaseModel):
    scenario_name: str                               # "2020 COVID Crash", "2008 GFC", custom
    scenario_description: Optional[str] = None
    current_value_rs: Optional[float] = None
    stressed_value_rs: Optional[float] = None
    drop_pct: Optional[float] = None
    recovery_years: Optional[float] = None
    breakdown: List[StressTestBreakdown] = Field(default_factory=list)
    insight: Optional[str] = None


# ── Sector Rotation ───────────────────────────────────────────────
class SectorPoint(BaseModel):
    name: str
    quadrant: Literal["Leading", "Weakening", "Lagging", "Improving"]
    rs_score: Optional[float] = None               # relative strength 0..100
    week_change_pct: Optional[float] = None
    month_change_pct: Optional[float] = None


class SectorRotationData(BaseModel):
    horizon: str = "1M"                            # "1W" | "1M" | "3M" | "6M"
    sectors: List[SectorPoint] = Field(default_factory=list)
    as_of_date: Optional[str] = None


# ── Overlap Reveal ────────────────────────────────────────────────
class OverlapStock(BaseModel):
    stock_name: str
    funds: List[str]                               # fund names that hold this stock
    avg_weight_pct: Optional[float] = None


class OverlapRevealData(BaseModel):
    funds: List[str]                               # fund names being compared
    overlap_pct: Optional[float] = None            # pairwise if 2 funds
    overlap_matrix: Optional[List[List[float]]] = None  # NxN for >2 funds
    top_common_stocks: List[OverlapStock] = Field(default_factory=list)
    verdict: Optional[str] = None


# ── Insight Card (unified 9-section conversational response) ──────
#
# The InsightCard is the forward-looking response shape for every
# Copilot tool. It standardises the mobile-first card layout with a
# fixed information architecture so users always know where to look:
#
#   1. Hero        — the headline number + severity tag
#   2. KPIs        — supporting metrics, swipeable on mobile
#   3. Findings    — prioritised list of specific issues
#   4. Recommendation — what the AI suggests in one paragraph
#   5. Impact      — optional before/after preview
#   6. Actions     — checklist of one-tap next steps
#   7. Education   — optional "why this matters" explainer
#   8. Suggested questions — follow-up chips
#   9. Sticky CTA  — derived from actions[0] on mobile
#
# Tools opt in by emitting `kind="insight_card"` with this payload.
# Sections are individually optional — only the populated ones render.

InsightSeverity = Literal["critical", "high", "medium", "info", "healthy"]
ActionStyle = Literal["primary", "secondary", "tertiary"]
Trend = Literal["up", "down", "flat"]


class InsightHero(BaseModel):
    """The single most important takeaway. Big number + short label."""
    severity: InsightSeverity = "info"
    eyebrow: Optional[str] = None              # "Top Priority", "Healthy", etc.
    headline: str                              # short title (≤ 60 chars)
    primary_value: Optional[str] = None        # rendered as-is (e.g. "₹8,400/yr", "97%")
    primary_label: Optional[str] = None        # subtitle under the value
    subtitle: Optional[str] = None             # one-sentence explanation
    trend: Optional[Trend] = None


class InsightKpi(BaseModel):
    """A single metric card in the swipeable carousel."""
    label: str                                 # "Funds Analysed"
    value: str                                 # rendered as-is — formatter is server-side
    sublabel: Optional[str] = None             # "out of 14"
    trend: Optional[Trend] = None
    tone: Optional[InsightSeverity] = None     # tints background


class InsightFinding(BaseModel):
    """A specific issue or observation, ranked by priority."""
    priority: Literal["high", "medium", "low"] = "medium"
    title: str                                 # "Axis Bluechip vs Mirae Largecap"
    detail: Optional[str] = None               # "97% portfolio overlap"
    impact_value: Optional[str] = None         # "Save ₹8,400/yr"
    impact_label: Optional[str] = None         # "Estimated annual savings"
    confidence_pct: Optional[int] = None       # 0..100


class InsightRecommendation(BaseModel):
    """The AI's narrative recommendation — kept short for mobile."""
    summary: str                               # 2–3 lines max
    rationale: Optional[str] = None            # expanded reasoning, shown on tap
    confidence_pct: Optional[int] = None


class InsightImpact(BaseModel):
    """Optional before/after preview of acting on the recommendation."""
    before_label: str = "Today"
    before_value: str
    after_label: str = "After"
    after_value: str
    delta_label: Optional[str] = None          # "Save ₹8,400/yr"
    delta_tone: Optional[InsightSeverity] = None


class InsightAction(BaseModel):
    """A single one-tap action. Rendered as a chip or sticky CTA."""
    label: str                                 # "Review findings"
    action_id: str                             # routed to onAction() callback
    style: ActionStyle = "secondary"
    icon: Optional[str] = None                 # lucide icon name; optional


class InsightEducation(BaseModel):
    """Optional 'why this matters' block, collapsed by default on mobile."""
    heading: str = "Why this matters"
    body: str


class InsightCardData(BaseModel):
    hero: InsightHero
    kpis: List[InsightKpi] = Field(default_factory=list)
    findings: List[InsightFinding] = Field(default_factory=list)
    recommendation: Optional[InsightRecommendation] = None
    impact: Optional[InsightImpact] = None
    actions: List[InsightAction] = Field(default_factory=list)
    education: Optional[InsightEducation] = None
    # NOTE: suggested_questions live on the envelope's `suggestions` field
    # — reusing the existing channel keeps the dispatcher uniform.


__all__ = [
    "WidgetEnvelope", "FreshnessChip", "AgentInfo", "WidgetKind", "FreshnessState",
    "FundCardData", "CompareTableData", "CompareRow",
    "MarketBriefData", "MarketBriefIndex",
    "SipPlanData", "SipPlanAllocation",
    "ActionCardData",
    "RebalancePlanData", "RebalanceAction",
    "TaxHarvestData", "TaxHarvestCandidate",
    "StressTestData", "StressTestBreakdown",
    "SectorRotationData", "SectorPoint",
    "OverlapRevealData", "OverlapStock",
    "InsightCardData", "InsightHero", "InsightKpi", "InsightFinding",
    "InsightRecommendation", "InsightImpact", "InsightAction", "InsightEducation",
    "InsightSeverity", "ActionStyle", "Trend",
]
