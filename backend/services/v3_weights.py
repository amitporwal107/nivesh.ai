"""V3.1 Category-aware weight configuration.

Stores per-category weight profiles for Quality, Health, Exit, Add composites.
Weights are persisted in MongoDB (`system_config.v3_weights`) so that admins
can tune them via the admin UI without a redeploy.

Three categories are scored differently today:
  - equity  : the default V3.0 Phase-1 profile (Performance-heavy).
  - hybrid  : Risk-adjusted & drawdown-heavy.
  - debt    : Credit quality & yield-heavy.

Liquid is currently classified but NOT scored via a custom profile — it
falls through to the equity profile with partial primitives. This matches
the user decision to defer Liquid scoring.
"""
from __future__ import annotations
import logging
import re
from copy import deepcopy
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

CONFIG_DOC_ID = "v3_weights"

# ── Default weight profiles (from PRD) ───────────────────────────────────
DEFAULT_WEIGHTS: Dict[str, Dict[str, Dict[str, int]]] = {
    "equity": {
        "quality": {
            "performance": 25, "risk_adjusted": 20, "consistency": 20,
            "drawdown": 15, "cost": 10, "aum_age": 10,
        },
        "health": {
            "manager_tenure": 25, "aum_stability": 20, "turnover": 15,
            "concentration": 15, "downside_protection": 15, "expense_trend": 10,
        },
    },
    "hybrid": {
        "quality": {
            "risk_adjusted": 30, "downside_capture": 20, "performance": 20,
            "allocation_stability": 15, "cost": 10, "aum_age": 5,
        },
        "health": {
            "allocation_consistency": 25, "downside_protection": 20,
            "manager_tenure": 15, "aum_stability": 15, "concentration": 15,
            "expense_trend": 10,
        },
    },
    "debt": {
        "quality": {
            "credit_quality": 30, "yield_vs_category": 25, "duration_risk": 20,
            "risk_adjusted": 15, "cost": 10,
        },
        "health": {
            "credit_concentration": 30, "liquidity": 20, "aum_stability": 20,
            "manager_tenure": 15, "expense_trend": 15,
        },
    },
}

# In-memory cache (hydrated from MongoDB on startup)
_weights_cache: Dict[str, Dict[str, Dict[str, int]]] = deepcopy(DEFAULT_WEIGHTS)


# ── Classification ───────────────────────────────────────────────────────
_DEBT_PATTERNS = re.compile(
    r"(debt|bond|gilt|credit|duration|dynamic bond|floating|income|corporate bond|"
    r"short term|medium term|long term|banking|psu|treasury|money market|overnight)",
    re.IGNORECASE,
)
_LIQUID_PATTERNS = re.compile(r"(liquid|overnight|ultra short|money market)", re.IGNORECASE)
_HYBRID_PATTERNS = re.compile(
    r"(hybrid|balanced|multi[- ]?asset|aggressive|conservative|dynamic asset|"
    r"arbitrage|equity savings)",
    re.IGNORECASE,
)


def classify_fund_category(fund: Dict[str, Any]) -> str:
    """Classify into 'equity' | 'hybrid' | 'debt' | 'liquid'.

    Uses fund's `category` / `sub_category` fields (from Groww or Tickertape).
    Liquid is reported separately but currently shares equity weights (user
    deferred Liquid scoring).
    """
    cat = (fund.get("category") or "").strip()
    sub = (fund.get("sub_category") or "").strip()
    combined = f"{cat} {sub}".strip() or ""
    if not combined:
        return "equity"  # conservative default
    # Order matters: liquid is checked first, then hybrid (because "aggressive
    # hybrid" might also match debt via "hybrid" token), then debt.
    if _LIQUID_PATTERNS.search(combined):
        return "liquid"
    if _HYBRID_PATTERNS.search(combined):
        return "hybrid"
    if _DEBT_PATTERNS.search(combined):
        return "debt"
    return "equity"


# ── Weight access ────────────────────────────────────────────────────────
def get_weights(
    category: str,
    dimension: str,  # 'quality' or 'health'
) -> Dict[str, int]:
    """Return the currently-cached weight map for a category+dimension.
    Returns equity's weights as fallback for 'liquid' and unknown categories.
    """
    cat = category if category in _weights_cache else "equity"
    return deepcopy(_weights_cache.get(cat, {}).get(dimension) or {})


def get_full_config() -> Dict[str, Dict[str, Dict[str, int]]]:
    """Return the entire current weights config (for admin UI / export)."""
    return deepcopy(_weights_cache)


def set_weights(
    category: str, dimension: str, weights: Dict[str, int]
) -> None:
    """Replace an in-memory weights map. Persistence happens elsewhere."""
    if category not in _weights_cache:
        _weights_cache[category] = {}
    _weights_cache[category][dimension] = {k: int(v) for k, v in weights.items()}


# ── MongoDB persistence ──────────────────────────────────────────────────
async def hydrate_from_db(db) -> None:
    """Load weights from `system_config` collection, falling back to defaults."""
    try:
        doc = await db["system_config"].find_one({"_id": CONFIG_DOC_ID})
    except Exception as e:  # noqa: BLE001
        logger.warning(f"v3_weights hydrate failed: {e}")
        return
    if not doc:
        logger.info("v3_weights: no doc in Mongo — keeping defaults")
        return
    weights = doc.get("weights")
    if not isinstance(weights, dict):
        return
    # Shallow-validate shape (categories × dimensions × weight-map)
    for cat, dims in weights.items():
        if not isinstance(dims, dict):
            continue
        _weights_cache[cat] = {}
        for dim, w_map in dims.items():
            if isinstance(w_map, dict):
                _weights_cache[cat][dim] = {k: int(v) for k, v in w_map.items() if isinstance(v, (int, float))}
    logger.info(f"v3_weights hydrated from Mongo — categories: {list(_weights_cache)}")


async def save_to_db(db) -> None:
    """Persist the current in-memory cache back to Mongo (upsert)."""
    await db["system_config"].update_one(
        {"_id": CONFIG_DOC_ID},
        {"$set": {"weights": deepcopy(_weights_cache)}},
        upsert=True,
    )


def reset_to_defaults() -> None:
    """Restore defaults in-memory (admin 'reset' button)."""
    global _weights_cache
    _weights_cache = deepcopy(DEFAULT_WEIGHTS)
