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
    "v3_data_source_daas": {
        "display_name": "V3 Data Source: NIDP DaaS",
        "description": (
            "When ON, V3 scoring reads MF + stock primitives via NIDP DaaS HTTP "
            "(POST /v1/mf/v3-primitives/bulk, /v1/stocks/v3-primitives/bulk). "
            "When OFF, V3 falls back to direct PG reads against nidp.v_v3_* views — "
            "this is the pre-cutover behaviour, kept as a fast revert path."
        ),
        "default_mode": "everyone",
        "default_allowlist": [],
    },
    "auto_fix_agent": {
        "display_name": "Auto-fix agent (high-confidence coding bugs)",
        "description": (
            "When ON (mode = everyone), the Work tracker auto-classifies high-confidence "
            "CODING bugs as 'valid' and spawns the PR-only fix agent (opens a PR for review — "
            "never auto-merges). Data / vendor / delisted-symbol errors are excluded and left "
            "for human triage. OFF (default) keeps the pipeline human-gated."
        ),
        "default_mode": "off",
        "default_allowlist": [],
    },
    "copilot_persona_prompts_enabled": {
        "display_name": "Copilot Persona-Tagged Suggested Prompts",
        "description": (
            "Surfaces the 99-entry persona-tagged prompt catalog (10 personas × "
            "10 questions, minus the 1 trader Q5 hidden until P3) in /api/copilot/"
            "suggested-prompts and enables the 5-category chip filter in the chat "
            "shell. Off = pre-persona behaviour (10 universal templates only)."
        ),
        "default_mode": "everyone",
        "default_allowlist": [],
    },
    "research": {
        "display_name": "Research (Filings Intelligence)",
        "description": (
            "Grants access to the standalone Research / Filings Intelligence surface "
            "(/research) and shows its entry in the primary nav (desktop sidebar + "
            "mobile bottom bar). Default = everyone; flip to 'allowlist' to make the "
            "surface grant-only. Independent of `research_only` (which CONFINES a user "
            "to just this surface)."
        ),
        "default_mode": "everyone",
        "default_allowlist": [],
    },
    "research_only": {
        "display_name": "Research-only access (confined to /research)",
        "description": (
            "When ON for a user, they can ONLY use the Research surface (/research): "
            "every authenticated app route redirects there, onboarding is skipped, and "
            "sign-in lands on /research. Use for research-pilot accounts. Default = "
            "allowlist with NO emails, so nobody is confined until explicitly added "
            "here (Admin → Feature Flags). Implies `research` access."
        ),
        "default_mode": "allowlist",
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


def mode_enabled(flag: str) -> bool:
    """Mode-only check: True iff the flag's mode is 'everyone'.

    For flags where per-user routing isn't meaningful — e.g. data-source
    selectors that run in non-user contexts — callers consult this instead
    of `is_enabled`. The off / everyone semantics still let admins flip
    the flag globally from the admin panel; allowlist mode is treated as
    'off' here so unknown-user contexts default safely.
    """
    _ensure_defaults()
    cfg = _flags.get(flag)
    if not cfg:
        return False
    return cfg.get("mode", "off") == "everyone"


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
