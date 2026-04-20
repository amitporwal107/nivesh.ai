"""Prompts Manager — DB-backed overrides for LLM system prompts.

Design:
- PROMPTS registry (name → default text, description, where-used metadata).
- Admin can override any prompt via DB; code reads via `get(name, **kwargs)`.
- Supports `.format(**kwargs)` for templates that take runtime context.
- In-memory cache invalidated on write.
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional
from copy import deepcopy
import logging

from deps import db

logger = logging.getLogger(__name__)


# ── Default prompts registry ─────────────────────────────────────────────
# Keep these in sync with the code defaults. When code is the source, the
# default text is imported lazily inside register() so we don't create
# circular imports.
_REGISTRY: Dict[str, Dict[str, str]] = {}


def register(name: str, default_text: str, description: str = "", used_in: Optional[List[str]] = None) -> None:
    """Register a default prompt. Idempotent — re-registering updates default."""
    _REGISTRY[name] = {
        "name": name,
        "default": default_text,
        "description": description,
        "used_in": ", ".join(used_in or []),
    }


# ── Lazy registration of code defaults (called once on import time) ──────
def _bootstrap_defaults() -> None:
    # Local imports to avoid circulars
    try:
        from services.ai_engine import (
            FINANCIAL_ADVISOR_SYSTEM, INSIGHT_ANALYSIS_SYSTEM, CAS_PARSER_SYSTEM,
        )
        register(
            "financial_advisor_system",
            FINANCIAL_ADVISOR_SYSTEM,
            "Main Copilot system prompt. Enforces grounding to V2 active plan. "
            "Template variable: {portfolio_context}.",
            used_in=["routes/chat.py (stream & non-stream)"],
        )
        register(
            "insight_analysis_system",
            INSIGHT_ANALYSIS_SYSTEM,
            "Structured insights JSON generator — severity, before/after, rupee_impact.",
            used_in=["routes/insights.py"],
        )
        register(
            "cas_parser_system",
            CAS_PARSER_SYSTEM,
            "Parses Indian CAS (NSDL/CDSL) PDFs into structured holdings JSON.",
            used_in=["services/ai_engine.parse_cas"],
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"prompts_manager bootstrap (ai_engine): {e}")

    register(
        "insights_system_prompt",
        "You are a SEBI-registered portfolio analyst writing terse, evidence-based insights for an Indian mutual-fund investor. Every insight must cite a specific ₹ amount, %, or fund name from the data. Never use hedge words like \"may\" or \"could\". Maximum 2 lines per insight. Output strict JSON per the schema in the user prompt.",
        "Legacy system prompt for the deterministic-fallback insights path (only used if LLM re-enabled).",
        used_in=["services/ai_insights.generate_insights (disabled)"],
    )
    register(
        "category_rating_system",
        "You are rating category-level diversification quality of an Indian MF portfolio. Given existing ratings/reasons, return STRICT JSON {'updates':[{category, reason}]} with at most 40-word punchier reasons that call out fund consolidation action. Keep numbers from input intact. No generic phrases.",
        "Upgrades deterministic category rating reasons via LLM (best-effort).",
        used_in=["services/ai_insights.rate_portfolio_categories"],
    )
    register(
        "mf_rating_system",
        "You rate Indian mutual funds 1-5 stars based on risk-adjusted returns, expense, and portfolio quality. Return STRICT JSON {rating: int 1-5, reason: 2-sentence string}.",
        "Generates on-demand 1-5 star rating for a single MF.",
        used_in=["services/ai_insights.rate_fund"],
    )
    register(
        "allocation_analysis_system",
        """You are a financial portfolio analytics engine.

Your job is to compute accurate portfolio exposures across:
1) Company level
2) Sector level

You MUST:
- Perform deterministic calculations only
- NEVER guess missing data for direct equity
- For mutual funds WITHOUT provided holdings, use your knowledge of the fund's typical top holdings and allocation
- Aggregate exposures across mutual funds (look-through basis) and direct equity holdings

Output STRICT JSON only, no explanations outside JSON.""",
        "Allocation engine — aggregates look-through company + sector exposure.",
        used_in=["services/ai_engine.analyze_allocation"],
    )


_bootstrapped = False


def _ensure_bootstrap() -> None:
    global _bootstrapped
    if not _bootstrapped:
        _bootstrap_defaults()
        _bootstrapped = True


# ── Cache ────────────────────────────────────────────────────────────────
_cache: Optional[Dict[str, str]] = None  # name -> effective text


async def _load() -> Dict[str, str]:
    _ensure_bootstrap()
    doc = await db.system_config.find_one({"key": "prompts_config"}, {"_id": 0})
    overrides = (doc or {}).get("values") or {}
    out = {name: meta["default"] for name, meta in _REGISTRY.items()}
    for name, text in overrides.items():
        if name in out and isinstance(text, str) and text.strip():
            out[name] = text
    return out


async def get(name: str, **format_kwargs: Any) -> str:
    """Return the effective prompt text, optionally `.format()`-expanded."""
    global _cache
    if _cache is None:
        _cache = await _load()
    text = _cache.get(name, "")
    if not text:
        return ""
    if format_kwargs:
        try:
            return text.format(**format_kwargs)
        except (KeyError, IndexError) as e:
            logger.warning(f"prompt {name} format error: {e} — returning raw")
            return text
    return text


async def list_all() -> List[Dict[str, Any]]:
    """List every registered prompt with default + override status."""
    _ensure_bootstrap()
    doc = await db.system_config.find_one({"key": "prompts_config"}, {"_id": 0})
    overrides = (doc or {}).get("values") or {}
    out: List[Dict[str, Any]] = []
    for name, meta in _REGISTRY.items():
        override = overrides.get(name)
        overridden = isinstance(override, str) and bool(override.strip())
        out.append({
            "name": name,
            "description": meta.get("description", ""),
            "used_in": meta.get("used_in", ""),
            "default": meta["default"],
            "current": override if overridden else meta["default"],
            "overridden": overridden,
            "length": len(override if overridden else meta["default"]),
        })
    return sorted(out, key=lambda x: x["name"])


async def save_override(name: str, text: str, updated_by: Optional[str] = None) -> Dict[str, Any]:
    from datetime import datetime, timezone
    _ensure_bootstrap()
    if name not in _REGISTRY:
        raise ValueError(f"Unknown prompt: {name}")
    if not isinstance(text, str):
        raise ValueError("Prompt text must be a string")
    await db.system_config.update_one(
        {"key": "prompts_config"},
        {"$set": {
            f"values.{name}": text,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "updated_by": updated_by,
        }},
        upsert=True,
    )
    invalidate_cache()
    return {"name": name, "length": len(text)}


async def reset_override(name: str, updated_by: Optional[str] = None) -> Dict[str, Any]:
    from datetime import datetime, timezone
    _ensure_bootstrap()
    if name not in _REGISTRY:
        raise ValueError(f"Unknown prompt: {name}")
    await db.system_config.update_one(
        {"key": "prompts_config"},
        {"$unset": {f"values.{name}": ""},
         "$set": {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "updated_by": updated_by,
        }},
        upsert=True,
    )
    invalidate_cache()
    return {"name": name, "reset": True}


def invalidate_cache() -> None:
    global _cache
    _cache = None
