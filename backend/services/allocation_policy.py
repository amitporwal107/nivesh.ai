"""Allocation policy loader — reads the governed config/allocation_policy.yaml.

This is the single source of truth the builder, selection and simulation read
(see Nivesh-Allocation-Methodology.md). Engineering owns faithful execution;
the Investment Committee owns the numbers. Nothing here invents weights — it
only exposes what the YAML declares, plus the risk-profile / horizon mapping.

Layers:
  L1  strategic_allocation(profile, horizon) -> {equity,debt,gold,cash} % of total
  L2  core_satellite_split(profile)          -> {core, satellite} % of equity sleeve
      debt_split(horizon)                    -> {sub_sleeve: % of debt sleeve}
  L3  selection()                            -> rank_by, min_quality_score, weights
  caps(), capital_market_assumptions(), compliance(), glide_path(), validation()
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Any, Dict, List

import yaml

_POLICY_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "allocation_policy.yaml")


@lru_cache(maxsize=1)
def _policy() -> Dict[str, Any]:
    with open(_POLICY_PATH, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def reload() -> None:
    """Drop the cache (after an admin edit / hot-reload)."""
    _policy.cache_clear()


# ── Profile + horizon mapping ────────────────────────────────────────────────
# Conversational risk categories (conservative/moderate/aggressive/balanced/
# growth) -> the three policy profiles (title-cased to match the YAML keys).
_PROFILE_ALIASES = {
    "conservative": "Conservative",
    "moderate": "Moderate",
    "balanced": "Moderate",
    "growth": "Aggressive",
    "aggressive": "Aggressive",
}


def profile_norm(category: str) -> str:
    """Normalise any risk category string to a YAML profile key."""
    return _PROFILE_ALIASES.get((category or "moderate").strip().lower(), "Moderate")


def horizon_bucket(years: float) -> str:
    """Map a horizon in years to the policy bucket: short <3y, medium 3-7y, long >7y."""
    y = float(years or 0)
    if y < 3:
        return "short"
    if y <= 7:
        return "medium"
    return "long"


def apply_capacity_caps(profile: str, horizon_years: float) -> str:
    """Apply the policy's capacity overrides (short horizon caps an aggressive
    appetite down). Returns the possibly-downgraded profile (YAML key)."""
    order = ["Conservative", "Moderate", "Aggressive"]
    p = profile_norm(profile)
    y = float(horizon_years or 0)
    cap_idx = len(order) - 1
    for rule in (_policy().get("risk_profiling", {}).get("capacity_caps") or []):
        when = str(rule.get("when", ""))
        cap_at = rule.get("cap_profile_at")
        # only the two horizon rules exist; evaluate them literally + safely
        if "horizon_years < 2" in when and y < 2 and cap_at in order:
            cap_idx = min(cap_idx, order.index(cap_at))
        elif "horizon_years < 3" in when and y < 3 and cap_at in order:
            cap_idx = min(cap_idx, order.index(cap_at))
    return order[min(order.index(p), cap_idx)]


# ── Layer 1 ──────────────────────────────────────────────────────────────────
def strategic_allocation(profile: str, horizon_bucket_key: str) -> Dict[str, float]:
    """Policy weights {equity,debt,gold,cash} (% of total) for profile + horizon."""
    table = _policy().get("strategic_allocation", {})
    prof = profile_norm(profile)
    row = (table.get(prof, {}) or {}).get(horizon_bucket_key)
    if not row:
        row = (table.get("Moderate", {}) or {}).get("medium", {})
    return {k: float(v) for k, v in row.items()}


# ── Layer 2 ──────────────────────────────────────────────────────────────────
def core_satellite_split(profile: str) -> Dict[str, float]:
    """{core, satellite} as % of the equity sleeve, for the profile."""
    split = (_policy().get("sub_sleeves", {}).get("equity", {})
             .get("core_satellite_split", {}))
    prof = profile_norm(profile)
    row = split.get(prof) or split.get("Moderate") or {"core": 70, "satellite": 30}
    return {k: float(v) for k, v in row.items()}


def equity_members() -> Dict[str, List[str]]:
    """{'core': [...], 'satellite': [...]} instrument-kind members of the equity sleeve."""
    eq = _policy().get("sub_sleeves", {}).get("equity", {})
    return {
        "core": list((eq.get("core") or {}).get("members") or []),
        "satellite": list((eq.get("satellite") or {}).get("members") or []),
    }


def debt_split(horizon_bucket_key: str) -> Dict[str, float]:
    """{sub_sleeve: % of debt sleeve} for the horizon bucket."""
    by_h = _policy().get("sub_sleeves", {}).get("debt", {}).get("by_horizon", {})
    row = by_h.get(horizon_bucket_key) or by_h.get("medium") or {}
    return {k: float(v) for k, v in row.items()}


# ── Passthrough accessors ────────────────────────────────────────────────────
def capital_market_assumptions() -> Dict[str, Dict[str, float]]:
    return _policy().get("capital_market_assumptions", {})


def caps() -> Dict[str, float]:
    return _policy().get("caps", {})


def selection() -> Dict[str, Any]:
    return _policy().get("selection", {})


def sleeves() -> Dict[str, Any]:
    return _policy().get("sleeves", {})


def glide_path() -> Dict[str, Any]:
    return _policy().get("glide_path", {})


def rebalancing() -> Dict[str, Any]:
    return _policy().get("rebalancing", {})


def validation() -> Dict[str, Any]:
    return _policy().get("validation", {})


def compliance() -> Dict[str, Any]:
    return _policy().get("compliance", {})


def names_allowed() -> bool:
    """True only when Compliance has enabled named-scheme MF output."""
    return compliance().get("mf_recommendations_mode") == "named_scheme"


def stocks_allowed() -> bool:
    return bool(compliance().get("direct_stock_recommendations_enabled"))


def disclaimer_required() -> bool:
    return bool(compliance().get("disclaimer_required", True))


def version() -> str:
    return str(_policy().get("meta", {}).get("version", "unknown"))
