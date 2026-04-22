"""Unified secrets registry — DB-first with env fallback.

Known secrets are pre-registered so the admin UI has useful defaults; admins
can also add arbitrary custom secrets under the "custom" category.

Values are stored plain-text in db.system_config.{key:"secrets"}.values.
TODO (future): encrypt at rest using Fernet + SECRETS_ENCRYPTION_KEY env var.
"""
from __future__ import annotations
import os
from typing import Dict, Optional, List


KNOWN_SECRETS: Dict[str, Dict[str, Optional[str]]] = {
    "CASPARSER_API_KEY": {
        "display_name": "CAS Parser API Key",
        "description": "Used for CAS PDF parsing + Connect widget",
        "test_fn": "cas_parser",
        "category": "parsing",
    },
    "EMERGENT_LLM_KEY": {
        "display_name": "Emergent LLM Key",
        "description": "Universal key for all AI (insights, copilot, chat)",
        "test_fn": "llm",
        "category": "ai",
    },
    "OPENAI_API_KEY": {
        "display_name": "OpenAI API Key (override)",
        "description": "Direct OpenAI key (falls back to Emergent key when empty)",
        "test_fn": "openai",
        "category": "ai",
    },
    "GOOGLE_CLIENT_ID": {
        "display_name": "Google OAuth Client ID",
        "description": "For Google Sign-In on web",
        "test_fn": None,
        "category": "auth",
    },
    "GMAIL_OAUTH_CLIENT_ID": {
        "display_name": "Gmail OAuth Client ID",
        "description": "For Gmail inbox CAS import",
        "test_fn": None,
        "category": "auth",
    },
    "CASPARSER_BASE_URL": {
        "display_name": "CAS Parser Base URL",
        "description": "Override API endpoint (default: https://api.casparser.in)",
        "test_fn": None,
        "category": "parsing",
    },
    "POSTGRES_URL": {
        "display_name": "Postgres URL",
        "description": "Analytics datastore for instrument_master, MF NAV history, V3 primitives. Recommended: Neon (free tier, serverless). Format: postgresql://user:pass@ep-xxx.aws.neon.tech/neondb?sslmode=require",
        "test_fn": "postgres",
        "category": "data",
    },
    "REDIS_URL": {
        "display_name": "Redis URL",
        "description": "V3 composite score cache (24h TTL) + equity fundamentals cache. Recommended: Upstash (free tier, serverless). Format: rediss://default:pass@xxx.upstash.io:6379",
        "test_fn": "redis",
        "category": "data",
    },
}

# Module-level cache: DB overrides. Populated at startup + on update.
_cache: Dict[str, str] = {}


def set_override(key: str, value: Optional[str]) -> None:
    """Set or clear (pass "" or None) an override for a secret."""
    if value:
        _cache[key] = value
    else:
        _cache.pop(key, None)


def get(key: str) -> str:
    """Effective secret value — DB override first, then env var."""
    if key in _cache:
        return _cache[key]
    return os.environ.get(key, "")


def mask(value: Optional[str]) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "••••"
    return f"{value[:4]}••••••{value[-4:]}"


def list_all() -> List[Dict]:
    """All known + custom secrets with masked values."""
    result: List[Dict] = []
    seen: set = set()
    for key, meta in KNOWN_SECRETS.items():
        env_val = os.environ.get(key, "")
        override_val = _cache.get(key)
        effective = override_val or env_val
        result.append({
            "key": key,
            "display_name": meta["display_name"],
            "description": meta["description"],
            "category": meta["category"],
            "test_fn": meta["test_fn"],
            "has_env_fallback": bool(env_val),
            "has_override": override_val is not None,
            "masked_value": mask(effective),
            "configured": bool(effective),
            "is_custom": False,
        })
        seen.add(key)
    # Custom keys in override cache that aren't pre-registered
    for key, val in _cache.items():
        if key in seen:
            continue
        result.append({
            "key": key,
            "display_name": key,
            "description": "Custom secret",
            "category": "custom",
            "test_fn": None,
            "has_env_fallback": False,
            "has_override": True,
            "masked_value": mask(val),
            "configured": True,
            "is_custom": True,
        })
    return result


async def hydrate_from_db(db) -> None:
    doc = await db.system_config.find_one({"key": "secrets"}, {"_id": 0})
    if doc and "values" in doc:
        for k, v in (doc.get("values") or {}).items():
            if isinstance(v, str) and v:
                _cache[k] = v


async def persist_to_db(db, key: str, value: Optional[str], updated_by: str = "") -> None:
    """Update one secret in DB + cache atomically."""
    from datetime import datetime, timezone
    set_override(key, value)
    update_path = f"values.{key}"
    if value:
        await db.system_config.update_one(
            {"key": "secrets"},
            {
                "$set": {
                    update_path: value,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "updated_by": updated_by,
                },
                "$setOnInsert": {"key": "secrets"},
            },
            upsert=True,
        )
    else:
        await db.system_config.update_one(
            {"key": "secrets"},
            {
                "$unset": {update_path: ""},
                "$set": {
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "updated_by": updated_by,
                },
            },
        )
