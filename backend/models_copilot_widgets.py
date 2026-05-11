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
    "capital_gains_snapshot",
    "stress_test",
    "market_brief",
    "sector_rotation",
    "holding_insight",
    "alert_confirmation",
    "report_download",
    "action_card",
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


__all__ = [
    "WidgetEnvelope", "FreshnessChip", "AgentInfo", "WidgetKind", "FreshnessState",
    "FundCardData", "CompareTableData", "CompareRow",
    "MarketBriefData", "MarketBriefIndex",
    "SipPlanData", "SipPlanAllocation",
    "ActionCardData",
]
