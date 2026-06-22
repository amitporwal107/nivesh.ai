"""Guided sleeve templates — risk sets the asset-class budget; quality+returns
set the sub-category split.

Two layers:
  1. ASSET_BUDGET[profile]   — how much equity / international / hybrid / gold /
     debt / cash (the RISK decision; sums to 100).
  2. ELIGIBLE_SLEEVES[profile][asset_class] — which sub-categories are allowed
     for this profile (e.g. conservative excludes small/mid cap).

The *weight within* each asset class is NOT hard-coded — sleeve_builder splits
the asset-class budget across its eligible sleeves in proportion to the avg V3
quality_score of each sleeve's top funds. V3 quality is a composite that is
~45% returns + risk-adjusted performance (Performance 25% + Risk-Adjusted 20% +
Consistency 20% + Drawdown 15% + Cost 10% + Size/Age 10%), so the split reflects
quality ranking AND returns, gated by the risk-driven budget + eligibility.

Sub-category names match nidp.v_v3_mf_scores_latest.sub_category. Budgets are an
engineering starting hypothesis (like allocation_bands) pending advisory review —
NOT investment advice.
"""
from __future__ import annotations

from typing import Any, Dict, List

# ── Sleeve catalogue: key → display + the NIDP V3 filter used to rank funds ───
SLEEVE_CATALOG: Dict[str, Dict[str, Any]] = {
    "large_cap":   {"label": "Large Cap",        "asset_class": "equity",        "fund_category": "equity", "sub_category": "Large Cap Fund"},
    "flexi_cap":   {"label": "Flexi Cap",        "asset_class": "equity",        "fund_category": "equity", "sub_category": "Flexi Cap Fund"},
    "large_mid":   {"label": "Large & Mid Cap",  "asset_class": "equity",        "fund_category": "equity", "sub_category": "Large & Mid Cap Fund"},
    "mid_cap":     {"label": "Mid Cap",          "asset_class": "equity",        "fund_category": "equity", "sub_category": "Mid Cap Fund"},
    "small_cap":   {"label": "Small Cap",        "asset_class": "equity",        "fund_category": "equity", "sub_category": "Small Cap Fund"},
    "international":{"label": "International",     "asset_class": "international",  "fund_category": "equity", "sub_category": "FoF Overseas"},
    "balanced_adv":{"label": "Balanced Advantage","asset_class": "hybrid",       "fund_category": "hybrid", "sub_category": "Balanced Advantage"},
    "aggr_hybrid": {"label": "Aggressive Hybrid", "asset_class": "hybrid",        "fund_category": "hybrid", "sub_category": "Aggressive Hybrid Fund"},
    "multi_asset": {"label": "Multi Asset",       "asset_class": "hybrid",        "fund_category": "hybrid", "sub_category": "Multi Asset Allocation"},
    "gold":        {"label": "Gold",              "asset_class": "gold",          "fund_category": None,     "sub_category": "Gold"},
    "corp_bond":   {"label": "Corporate Bond",    "asset_class": "debt",          "fund_category": "debt",   "sub_category": "Corporate Bond Fund"},
    "short_dur":   {"label": "Short Duration",    "asset_class": "debt",          "fund_category": "debt",   "sub_category": "Short Duration Fund"},
    "banking_psu": {"label": "Banking & PSU",     "asset_class": "debt",          "fund_category": "debt",   "sub_category": "Banking and PSU Fund"},
    "gilt":        {"label": "Gilt",              "asset_class": "debt",          "fund_category": "debt",   "sub_category": "Gilt Fund"},
    "liquid":      {"label": "Liquid / Cash",     "asset_class": "cash",          "fund_category": "liquid", "sub_category": "Liquid Fund"},
}

ASSET_ORDER = ["equity", "international", "hybrid", "gold", "debt", "cash"]

# ── Layer 1: risk-driven asset-class budget (sums to 100) ─────────────────────
ASSET_BUDGET: Dict[str, Dict[str, float]] = {
    "conservative": {"equity": 22, "international": 4, "hybrid": 12, "gold": 8, "debt": 42, "cash": 12},
    "moderate":     {"equity": 46, "international": 6, "hybrid": 10, "gold": 8, "debt": 24, "cash": 6},
    "aggressive":   {"equity": 62, "international": 10, "hybrid": 8, "gold": 8, "debt": 8, "cash": 4},
}

# ── Layer 2: which sleeves are eligible per profile + asset class ─────────────
ELIGIBLE_SLEEVES: Dict[str, Dict[str, List[str]]] = {
    "conservative": {
        "equity": ["large_cap", "flexi_cap"],
        "international": ["international"],
        "hybrid": ["balanced_adv", "multi_asset"],
        "gold": ["gold"],
        "debt": ["corp_bond", "short_dur", "gilt", "banking_psu"],
        "cash": ["liquid"],
    },
    "moderate": {
        "equity": ["large_cap", "flexi_cap", "large_mid", "mid_cap"],
        "international": ["international"],
        "hybrid": ["balanced_adv", "aggr_hybrid", "multi_asset"],
        "gold": ["gold"],
        "debt": ["corp_bond", "short_dur"],
        "cash": ["liquid"],
    },
    "aggressive": {
        "equity": ["flexi_cap", "large_cap", "mid_cap", "small_cap"],
        "international": ["international"],
        "hybrid": ["aggr_hybrid", "balanced_adv"],
        "gold": ["gold"],
        "debt": ["corp_bond"],
        "cash": ["liquid"],
    },
}

# Conversational risk categories → template tier.
_CATEGORY_TO_TEMPLATE = {
    "conservative": "conservative", "moderate": "moderate", "balanced": "moderate",
    "growth": "aggressive", "aggressive": "aggressive",
}


def _tier(risk_profile: str) -> str:
    return _CATEGORY_TO_TEMPLATE.get((risk_profile or "moderate").lower(), "moderate")


def asset_budget(risk_profile: str) -> Dict[str, float]:
    """Risk-driven asset-class budget for a profile (sums to 100)."""
    return dict(ASSET_BUDGET[_tier(risk_profile)])


def eligible_sleeves(risk_profile: str) -> Dict[str, List[Dict[str, Any]]]:
    """{asset_class: [sleeve catalog dicts]} eligible for this profile, ordered."""
    tier = _tier(risk_profile)
    out: Dict[str, List[Dict[str, Any]]] = {}
    for ac in ASSET_ORDER:
        keys = ELIGIBLE_SLEEVES[tier].get(ac, [])
        out[ac] = [{"key": k, **SLEEVE_CATALOG[k]} for k in keys]
    return out


def validate() -> Dict[str, float]:
    """Return {profile: sum(asset_budget)} — every profile must total 100."""
    return {p: round(sum(b.values()), 2) for p, b in ASSET_BUDGET.items()}
