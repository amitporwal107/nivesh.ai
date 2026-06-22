"""Guided sleeve templates — category/sub-category allocation per risk profile.

The asset-class allocator (allocation_bands / target_allocator) answers
"how much equity vs debt vs gold vs cash". This module goes one level deeper:
WITHIN each asset class, which sub-categories (Large Cap, Flexi Cap, Balanced
Advantage, Corporate Bond, FoF Overseas / international, Gold ETF, …) and at
what target weight. That is what the in-chat Portfolio Builder needs to fill
each sleeve with the right ranked funds instead of one undifferentiated bucket.

Sub-category names match the NIDP V3 MF scores catalogue
(nidp.v_v3_mf_scores_latest.sub_category) so a sleeve maps 1:1 to a real,
scorable fund universe. Verified present (scored counts, 2026-06-03):
  Large Cap 235 · Flexi Cap 265 · Large & Mid 212 · Mid Cap 193 · Small Cap 201
  ELSS 239 · FoF Overseas (international) 252 · Gold ETF 26
  Balanced Advantage 219 · Aggressive Hybrid 279 · Multi Asset 196
  Corporate Bond 289 · Short Duration 322 · Banking & PSU 238 · Gilt 208
  Liquid 517

Weights are an engineering starting hypothesis (like allocation_bands) pending
advisory review — NOT investment advice. Each profile sums to exactly 100.
"""
from __future__ import annotations

from typing import Any, Dict, List

# ── Sleeve catalogue ─────────────────────────────────────────────────────────
# key → display + the NIDP V3 filter used to rank its funds. `sub_category` is
# matched ILIKE on the scores view; `fund_category` narrows it (equity/debt/
# hybrid/liquid) where helpful. `asset_class` groups sleeves in the UI.
SLEEVE_CATALOG: Dict[str, Dict[str, Any]] = {
    # Equity
    "large_cap":   {"label": "Large Cap",        "asset_class": "equity", "fund_category": "equity", "sub_category": "Large Cap Fund"},
    "flexi_cap":   {"label": "Flexi Cap",        "asset_class": "equity", "fund_category": "equity", "sub_category": "Flexi Cap Fund"},
    "large_mid":   {"label": "Large & Mid Cap",  "asset_class": "equity", "fund_category": "equity", "sub_category": "Large & Mid Cap Fund"},
    "mid_cap":     {"label": "Mid Cap",          "asset_class": "equity", "fund_category": "equity", "sub_category": "Mid Cap Fund"},
    "small_cap":   {"label": "Small Cap",        "asset_class": "equity", "fund_category": "equity", "sub_category": "Small Cap Fund"},
    "elss":        {"label": "ELSS (tax-saver)", "asset_class": "equity", "fund_category": "equity", "sub_category": "ELSS"},
    # International (a distinct sleeve, sourced from overseas FoFs)
    "international":{"label": "International",     "asset_class": "international", "fund_category": "equity", "sub_category": "FoF Overseas"},
    # Hybrid
    "balanced_adv":{"label": "Balanced Advantage","asset_class": "hybrid", "fund_category": "hybrid", "sub_category": "Balanced Advantage"},
    "aggr_hybrid": {"label": "Aggressive Hybrid", "asset_class": "hybrid", "fund_category": "hybrid", "sub_category": "Aggressive Hybrid Fund"},
    "multi_asset": {"label": "Multi Asset",       "asset_class": "hybrid", "fund_category": "hybrid", "sub_category": "Multi Asset Allocation"},
    # Gold
    "gold":        {"label": "Gold",              "asset_class": "gold",   "fund_category": None,     "sub_category": "Gold"},
    # Debt
    "corp_bond":   {"label": "Corporate Bond",    "asset_class": "debt",   "fund_category": "debt",   "sub_category": "Corporate Bond Fund"},
    "short_dur":   {"label": "Short Duration",    "asset_class": "debt",   "fund_category": "debt",   "sub_category": "Short Duration Fund"},
    "banking_psu": {"label": "Banking & PSU",     "asset_class": "debt",   "fund_category": "debt",   "sub_category": "Banking and PSU Fund"},
    "gilt":        {"label": "Gilt",              "asset_class": "debt",   "fund_category": "debt",   "sub_category": "Gilt Fund"},
    # Cash
    "liquid":      {"label": "Liquid / Cash",     "asset_class": "cash",   "fund_category": "liquid", "sub_category": "Liquid Fund"},
}

# ── Per-profile templates: {sleeve_key: target_pct}, each summing to 100 ──────
PROFILE_TEMPLATES: Dict[str, Dict[str, float]] = {
    "conservative": {
        "large_cap": 14, "flexi_cap": 8, "international": 4,        # equity 26
        "balanced_adv": 12,                                          # hybrid 12
        "corp_bond": 20, "short_dur": 14, "gilt": 8,                 # debt 42
        "gold": 8,                                                   # gold 8
        "liquid": 12,                                                # cash 12
    },
    "moderate": {
        "flexi_cap": 16, "large_cap": 14, "large_mid": 8, "mid_cap": 8, "international": 6,  # equity 52
        "balanced_adv": 10,                                          # hybrid 10
        "corp_bond": 14, "short_dur": 10,                            # debt 24
        "gold": 8,                                                   # gold 8
        "liquid": 6,                                                 # cash 6
    },
    "aggressive": {
        "flexi_cap": 22, "large_cap": 14, "mid_cap": 14, "small_cap": 12, "international": 10,  # equity 72
        "aggr_hybrid": 8,                                            # hybrid 8
        "corp_bond": 8,                                              # debt 8
        "gold": 8,                                                   # gold 8
        "liquid": 4,                                                 # cash 4
    },
}

# Map the conversational risk categories onto a template (3 tiers today; the
# extra allocation_bands tiers fall back to the nearest).
_CATEGORY_TO_TEMPLATE = {
    "conservative": "conservative",
    "moderate": "moderate",
    "balanced": "moderate",
    "growth": "aggressive",
    "aggressive": "aggressive",
}


def sleeves_for(risk_profile: str) -> List[Dict[str, Any]]:
    """Return the ordered sleeve list for a risk profile.

    Each item: {key, label, asset_class, fund_category, sub_category, target_pct}.
    Ordered by asset class (equity → international → hybrid → gold → debt → cash)
    then target weight, so the UI renders a sensible tree.
    """
    tmpl_key = _CATEGORY_TO_TEMPLATE.get((risk_profile or "moderate").lower(), "moderate")
    weights = PROFILE_TEMPLATES[tmpl_key]
    order = ["equity", "international", "hybrid", "gold", "debt", "cash"]
    out: List[Dict[str, Any]] = []
    for key, pct in weights.items():
        cat = SLEEVE_CATALOG[key]
        out.append({"key": key, "target_pct": float(pct), **cat})
    out.sort(key=lambda s: (order.index(s["asset_class"]), -s["target_pct"]))
    return out


def validate_templates() -> Dict[str, float]:
    """Return {profile: sum_of_weights} — every profile must total 100."""
    return {p: round(sum(w.values()), 2) for p, w in PROFILE_TEMPLATES.items()}
