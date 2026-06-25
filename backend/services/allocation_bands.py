"""Canonical asset-class allocation bands — single source of truth for target allocation.

Persisted in MongoDB (system_config.allocation_bands) so admins can tune via
the admin UI without a redeploy.  Follows the same in-memory-cache +
Mongo-persistence pattern as v3_weights.py.

Band format per risk tier and asset class:
    {"min": float, "target": float, "max": float}   (percentage points, 0–100)

The `target` value is the base allocation point used by target_allocator.py.
`min` / `max` define the band within which no rebalancing is triggered.

Rationale (2026-06-03): reconciles three previously-conflicting code paths:
  1. target_allocator._BASE_BY_RISK (3-tier point estimates)
  2. persona_config.PERSONA_PROFILES equity/debt ranges (5-tier)
  3. widget_builders.py hardcoded 65/35 (now removed)
Values are an engineering starting hypothesis pending advisory review.
"""
from __future__ import annotations

import logging
from copy import deepcopy
from typing import Dict

logger = logging.getLogger(__name__)

CONFIG_DOC_ID = "allocation_bands"

# ── Default band values (approved 2026-06-03) ────────────────────────────────
DEFAULT_BANDS: Dict[str, Dict[str, Dict[str, float]]] = {
    "conservative": {
        "equity": {"min": 20.0, "target": 35.0, "max": 45.0},
        "debt":   {"min": 45.0, "target": 55.0, "max": 65.0},
        "gold":   {"min":  5.0, "target": 10.0, "max": 12.0},
        "cash":   {"min":  3.0, "target":  5.0, "max":  8.0},
    },
    "moderate": {
        "equity": {"min": 40.0, "target": 55.0, "max": 65.0},
        "debt":   {"min": 25.0, "target": 35.0, "max": 45.0},
        "gold":   {"min":  5.0, "target": 10.0, "max": 12.0},
        "cash":   {"min":  3.0, "target":  5.0, "max":  8.0},
    },
    "balanced": {
        "equity": {"min": 55.0, "target": 62.0, "max": 72.0},
        "debt":   {"min": 20.0, "target": 28.0, "max": 35.0},
        "gold":   {"min":  3.0, "target":  8.0, "max": 10.0},
        "cash":   {"min":  2.0, "target":  3.0, "max":  5.0},
    },
    "growth": {
        "equity": {"min": 65.0, "target": 73.0, "max": 82.0},
        "debt":   {"min": 12.0, "target": 20.0, "max": 28.0},
        "gold":   {"min":  0.0, "target":  5.0, "max":  8.0},
        "cash":   {"min":  2.0, "target":  3.0, "max":  5.0},
    },
    "aggressive": {
        "equity": {"min": 75.0, "target": 82.0, "max": 90.0},
        "debt":   {"min":  5.0, "target": 10.0, "max": 18.0},
        "gold":   {"min":  0.0, "target":  3.0, "max":  8.0},
        "cash":   {"min":  2.0, "target":  3.0, "max":  5.0},
    },
}

# In-memory cache — hydrated from MongoDB on startup, updated via admin PUT
_bands_cache: Dict[str, Dict[str, Dict[str, float]]] = deepcopy(DEFAULT_BANDS)

TIERS = list(DEFAULT_BANDS.keys())
ASSETS = ("equity", "debt", "gold", "cash")


# ── Read API (synchronous — safe to call from any context) ───────────────────

def get_bands() -> Dict[str, Dict[str, Dict[str, float]]]:
    """Return the full current bands config (all tiers)."""
    return deepcopy(_bands_cache)


def get_tier_bands(tier: str) -> Dict[str, Dict[str, float]]:
    """Return bands for a single risk tier. Falls back to moderate."""
    return deepcopy(_bands_cache.get(tier) or _bands_cache["moderate"])


def get_target(tier: str, asset: str) -> float:
    """Return the target allocation % for a tier + asset class."""
    return float(
        (_bands_cache.get(tier) or _bands_cache["moderate"])
        .get(asset, {})
        .get("target", 0.0)
    )


def base_allocation(tier: str) -> Dict[str, float]:
    """Return {equity, debt, gold, cash} target percentages for a tier.

    Equivalent to the old _BASE_BY_RISK[tier] but from the live cache.
    """
    tier_bands = _bands_cache.get(tier) or _bands_cache["moderate"]
    return {asset: tier_bands[asset]["target"] for asset in ASSETS if asset in tier_bands}


# ── MongoDB persistence ──────────────────────────────────────────────────────

async def hydrate_from_db(db) -> None:
    """Load bands from system_config collection, falling back to defaults."""
    try:
        doc = await db["system_config"].find_one({"_id": CONFIG_DOC_ID})
    except Exception as e:  # noqa: BLE001
        logger.warning("allocation_bands hydrate failed: %s", e)
        return
    if not doc:
        logger.info("allocation_bands: no doc in Mongo — keeping defaults")
        return
    bands = doc.get("bands")
    if not isinstance(bands, dict):
        return
    for tier, assets in bands.items():
        if not isinstance(assets, dict):
            continue
        _bands_cache[tier] = {}
        for asset, b in assets.items():
            if isinstance(b, dict) and all(k in b for k in ("min", "target", "max")):
                _bands_cache[tier][asset] = {
                    "min":    float(b["min"]),
                    "target": float(b["target"]),
                    "max":    float(b["max"]),
                }
    logger.info("allocation_bands hydrated from Mongo — tiers: %s", list(_bands_cache))


async def save_to_db(db) -> None:
    """Persist the current in-memory cache to Mongo."""
    await db["system_config"].update_one(
        {"_id": CONFIG_DOC_ID},
        {"$set": {"bands": deepcopy(_bands_cache)}},
        upsert=True,
    )


def update_in_memory(bands: Dict[str, Dict[str, Dict[str, float]]]) -> None:
    """Replace the in-memory cache (called by admin PUT before save_to_db)."""
    global _bands_cache
    _bands_cache = deepcopy(bands)


def reset_to_defaults() -> None:
    """Restore defaults in-memory (admin reset)."""
    global _bands_cache
    _bands_cache = deepcopy(DEFAULT_BANDS)
    logger.info("allocation_bands reset to defaults")
