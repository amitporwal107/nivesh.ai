"""V2 Rules Config — DB-backed overrides for rule thresholds + custom rules.

Design:
- `DEFAULTS` defines the canonical config shape + values as of V2.5.
- Overrides live in `db.system_config` under `key="rules_config"` as
  `{rules: {...}, custom_rules: [...]}`.
- In-memory cache with explicit invalidation on writes (fast reads, no races).
- `get_config()` is the single read path used by the engine.
- Custom rules (Phase 2) use a safe AST-based expression evaluator.
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional
from copy import deepcopy
import logging

from deps import db

logger = logging.getLogger(__name__)

# ── Default rule parameters ──────────────────────────────────────────────
# Every numeric threshold in _apply_action_rules MUST be sourced from here
# so admins can tune it live without code changes.
DEFAULTS: Dict[str, Any] = {
    "rules": {
        "rule_1_regular_to_direct": {
            "enabled": True,
            "label": "Rule 1 · Regular → Direct consolidation",
            "description": "When a Direct plan of the same fund exists in the portfolio, exit the Regular plan.",
            "params": {},
        },
        "rule_2_amc_concentration": {
            "enabled": True,
            "label": "Rule 2 · AMC concentration",
            "description": "Exit highest-exit-score funds of an AMC whose exposure exceeds the threshold, until below threshold.",
            "params": {
                "threshold_pct": 15.0,  # 0–100, exclusive trigger
            },
        },
        "rule_2b_category_concentration": {
            "enabled": True,
            "label": "Rule 2b · MF category concentration",
            "description": "Trim funds in a single category whose total exposure exceeds the threshold (e.g. Mid Cap > 35%).",
            "params": {
                "threshold_pct": 35.0,
            },
        },
        "rule_3_underperformer_replacement": {
            "enabled": True,
            "label": "Rule 3 · Underperformer replacement",
            "description": "Exit underperformers and add the top ADD-score fund in the same category. Cap on actions per plan.",
            "params": {
                "max_replacements": 2,
            },
        },
        "rule_4_different_fund_overlap": {
            "enabled": True,
            "label": "Rule 4 · Different-fund overlap",
            "description": "When two different funds overlap above threshold, exit the fund with the higher exit score (subject to positive switch score).",
            "params": {
                "overlap_threshold_pct": 60.0,
                "max_overlap_exits": 2,
            },
        },
        "rule_5_debt_allocation": {
            "enabled": True,
            "label": "Rule 5 · Debt allocation (dynamic target)",
            "description": "Add debt fund when current debt % is below the risk-based target. Conservative=30, Medium=20, Aggressive=10.",
            "params": {
                "debt_target_conservative_pct": 30.0,
                "debt_target_medium_pct": 20.0,
                "debt_target_aggressive_pct": 10.0,
            },
        },
        "rule_6_cost_leak_switch": {
            "enabled": True,
            "label": "Rule 6 · Regular → Direct cost-leak switch",
            "description": "Switch Regular funds (no Direct twin) to Direct when aggregate annual cost leak exceeds threshold.",
            "params": {
                "total_leak_threshold_rs": 10000.0,
                "max_switches": 3,
            },
        },
        "rule_7_do_nothing": {
            "enabled": True,
            "label": "Rule 7 · Do-Nothing (portfolio healthy)",
            "description": "When portfolio score exceeds threshold and no high-priority actions exist, return a celebratory HOLD.",
            "params": {
                "portfolio_score_threshold": 75.0,
            },
        },
    },
    "plan_limits": {
        "max_actions_per_plan": 6,
    },
    "custom_rules": [],   # Phase 2 — user-defined rules
}


# ── Cache ────────────────────────────────────────────────────────────────
_cache: Optional[Dict[str, Any]] = None


def _merge_defaults(stored: Dict[str, Any]) -> Dict[str, Any]:
    """Deep-merge stored overrides onto defaults so new defaults appear."""
    out = deepcopy(DEFAULTS)
    if not stored:
        return out
    for rid, cfg in (stored.get("rules") or {}).items():
        if rid not in out["rules"]:
            continue
        if isinstance(cfg.get("enabled"), bool):
            out["rules"][rid]["enabled"] = cfg["enabled"]
        for pk, pv in (cfg.get("params") or {}).items():
            if pk in out["rules"][rid]["params"]:
                out["rules"][rid]["params"][pk] = pv
    if isinstance(stored.get("plan_limits"), dict):
        for k, v in stored["plan_limits"].items():
            if k in out["plan_limits"]:
                out["plan_limits"][k] = v
    if isinstance(stored.get("custom_rules"), list):
        out["custom_rules"] = stored["custom_rules"]
    return out


async def _load() -> Dict[str, Any]:
    doc = await db.system_config.find_one({"key": "rules_config"}, {"_id": 0})
    stored = (doc or {}).get("values") or {}
    return _merge_defaults(stored)


async def get_config(refresh: bool = False) -> Dict[str, Any]:
    """Return the effective rules config. Cached in memory."""
    global _cache
    if refresh or _cache is None:
        _cache = await _load()
    return _cache


async def get_rule(rule_id: str) -> Dict[str, Any]:
    cfg = await get_config()
    return cfg["rules"].get(rule_id) or {}


async def get_param(rule_id: str, param_name: str, default: Any = None) -> Any:
    rule = await get_rule(rule_id)
    return (rule.get("params") or {}).get(param_name, default)


async def is_enabled(rule_id: str) -> bool:
    rule = await get_rule(rule_id)
    return bool(rule.get("enabled", True))


def invalidate_cache() -> None:
    global _cache
    _cache = None


# ── Writer (admin-only) ──────────────────────────────────────────────────
async def save_overrides(overrides: Dict[str, Any], updated_by: Optional[str] = None) -> Dict[str, Any]:
    """Persist overrides and invalidate cache. Only shape-valid keys are stored."""
    from datetime import datetime, timezone
    safe: Dict[str, Any] = {"rules": {}, "plan_limits": {}, "custom_rules": []}

    for rid, cfg in (overrides.get("rules") or {}).items():
        if rid not in DEFAULTS["rules"]:
            continue
        entry: Dict[str, Any] = {}
        if isinstance(cfg.get("enabled"), bool):
            entry["enabled"] = cfg["enabled"]
        params_out: Dict[str, Any] = {}
        for pk, pv in (cfg.get("params") or {}).items():
            if pk in DEFAULTS["rules"][rid]["params"]:
                try:
                    params_out[pk] = float(pv)
                except (TypeError, ValueError):
                    continue
        if params_out:
            entry["params"] = params_out
        if entry:
            safe["rules"][rid] = entry

    for k, v in (overrides.get("plan_limits") or {}).items():
        if k in DEFAULTS["plan_limits"]:
            try:
                safe["plan_limits"][k] = int(v)
            except (TypeError, ValueError):
                continue

    if isinstance(overrides.get("custom_rules"), list):
        safe["custom_rules"] = overrides["custom_rules"]

    await db.system_config.update_one(
        {"key": "rules_config"},
        {"$set": {
            "key": "rules_config",
            "values": safe,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "updated_by": updated_by,
        }},
        upsert=True,
    )
    invalidate_cache()
    return await get_config(refresh=True)


async def reset_to_defaults(updated_by: Optional[str] = None) -> Dict[str, Any]:
    from datetime import datetime, timezone
    await db.system_config.update_one(
        {"key": "rules_config"},
        {"$set": {
            "key": "rules_config",
            "values": {"rules": {}, "plan_limits": {}, "custom_rules": []},
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "updated_by": updated_by,
            "reset": True,
        }},
        upsert=True,
    )
    invalidate_cache()
    return await get_config(refresh=True)
