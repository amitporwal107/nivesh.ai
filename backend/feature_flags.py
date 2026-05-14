"""DB-backed feature flags with per-user allowlists.

Modes:
  - "off"       → disabled for everyone
  - "allowlist" → enabled only for emails in allowlist
  - "everyone"  → enabled for all authenticated users
"""
from __future__ import annotations
from typing import Dict, List, Optional


KNOWN_FEATURES: Dict[str, Dict] = {
    "ai_copilot": {
        "display_name": "AI Copilot (Scenario Engine)",
        "description": "Simulate scenarios, rebalance plans, custom builder, saved/pending plans",
        "default_mode": "allowlist",
        "default_allowlist": ["aporwal107@gmail.com"],
    },
    "gmail_import": {
        "display_name": "Gmail CAS Import",
        "description": "Auto-fetch CAS from Gmail inbox",
        "default_mode": "everyone",
        "default_allowlist": [],
    },
    "chat_streaming": {
        "display_name": "AI Chat (Streaming)",
        "description": "Conversational AI financial advisor",
        "default_mode": "everyone",
        "default_allowlist": [],
    },
    "copilot_engine_nidp": {
        "display_name": "Copilot Engine: NIDP (LangGraph)",
        "description": "Routes chat through the NIDP LangGraph multi-agent engine (market, stock, MF, portfolio nodes). Off = V3 RAG fast-retrieval path.",
        "default_mode": "everyone",
        "default_allowlist": [],
    },
}

# In-memory state — {flag: {mode, allowlist}}
_flags: Dict[str, Dict] = {}


def _ensure_defaults() -> None:
    for key, meta in KNOWN_FEATURES.items():
        _flags.setdefault(
            key,
            {
                "mode": meta["default_mode"],
                "allowlist": list(meta.get("default_allowlist", [])),
            },
        )


def is_enabled(flag: str, email: Optional[str]) -> bool:
    _ensure_defaults()
    cfg = _flags.get(flag)
    if not cfg:
        return False
    mode = cfg.get("mode", "off")
    if mode == "off":
        return False
    if mode == "everyone":
        return True
    # allowlist
    if not email:
        return False
    al = {e.lower() for e in cfg.get("allowlist", [])}
    return email.lower().strip() in al


def set_flag(flag: str, mode: Optional[str] = None, allowlist: Optional[List[str]] = None) -> None:
    _ensure_defaults()
    if flag not in _flags:
        _flags[flag] = {"mode": "off", "allowlist": []}
    if mode is not None:
        if mode not in {"off", "allowlist", "everyone"}:
            raise ValueError(f"Invalid mode: {mode}")
        _flags[flag]["mode"] = mode
    if allowlist is not None:
        _flags[flag]["allowlist"] = sorted({e.lower().strip() for e in allowlist if e.strip()})


def add_user(flag: str, email: str) -> None:
    _ensure_defaults()
    cfg = _flags.setdefault(flag, {"mode": "allowlist", "allowlist": []})
    cur = {e.lower() for e in cfg["allowlist"]}
    cur.add(email.lower().strip())
    cfg["allowlist"] = sorted(cur)


def remove_user(flag: str, email: str) -> None:
    _ensure_defaults()
    cfg = _flags.get(flag)
    if not cfg:
        return
    e = email.lower().strip()
    cfg["allowlist"] = [x for x in cfg["allowlist"] if x != e]


def list_all() -> List[Dict]:
    _ensure_defaults()
    out = []
    seen = set()
    for key, meta in KNOWN_FEATURES.items():
        cfg = _flags.get(key, {"mode": meta["default_mode"], "allowlist": []})
        out.append({
            "key": key,
            "display_name": meta["display_name"],
            "description": meta["description"],
            "mode": cfg["mode"],
            "allowlist": cfg.get("allowlist", []),
            "is_custom": False,
        })
        seen.add(key)
    # custom flags (added via admin, not pre-registered)
    for key, cfg in _flags.items():
        if key in seen:
            continue
        out.append({
            "key": key,
            "display_name": key,
            "description": "Custom feature flag",
            "mode": cfg["mode"],
            "allowlist": cfg.get("allowlist", []),
            "is_custom": True,
        })
    return out


def user_feature_map(email: Optional[str]) -> Dict[str, bool]:
    """Map for frontend gating — {flag_key: enabled_for_this_user}."""
    _ensure_defaults()
    return {key: is_enabled(key, email) for key in _flags.keys()}


async def hydrate_from_db(db) -> None:
    _ensure_defaults()
    doc = await db.system_config.find_one({"key": "feature_flags"}, {"_id": 0})
    if doc and "flags" in doc:
        for k, v in (doc["flags"] or {}).items():
            if isinstance(v, dict):
                _flags[k] = {
                    "mode": v.get("mode", "off"),
                    "allowlist": v.get("allowlist", []),
                }


async def persist_to_db(db, updated_by: str = "") -> None:
    from datetime import datetime, timezone
    await db.system_config.update_one(
        {"key": "feature_flags"},
        {
            "$set": {
                "flags": _flags,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "updated_by": updated_by,
            },
            "$setOnInsert": {"key": "feature_flags"},
        },
        upsert=True,
    )


# ── Backwards compat for existing code importing is_copilot_enabled ─────
def is_copilot_enabled(email: Optional[str]) -> bool:
    return is_enabled("ai_copilot", email)
