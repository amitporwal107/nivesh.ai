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
    # NOTE: CAS Parser API keys are intentionally NOT registered here.
    # They live in Google Secret Manager only (secret name:
    # `casparser-api-keys-{production|preview}`). The admin console must
    # not edit them — see helpers/gsm.py and services/cas_api_client.py.
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
    "NIDP_DAAS_BASE_URL": {
        "display_name": "NIDP DaaS · Base URL",
        "description": "Base URL of the NIDP DaaS API (e.g. https://data.niveshcopilot.com/daas). Used by Copilot context fetcher and proxy routes.",
        "test_fn": None,
        "category": "nidp",
    },
    "NIDP_DAAS_INTERNAL_TOKEN": {
        "display_name": "NIDP DaaS · API Key (X-API-Key)",
        "description": "Shared API key sent as X-API-Key header to the NIDP DaaS API. Tokens start with nvd_. Use the Regenerate button to rotate.",
        "test_fn": None,
        "category": "nidp",
    },
    "NIDP_QUERY_API_URL": {
        "display_name": "NIDP Query API · Base URL",
        "description": "Base URL of the NIDP Query API (e.g. https://data.niveshcopilot.com/query). Bearer-token auth via NIDP_QUERY_API_TOKEN.",
        "test_fn": None,
        "category": "nidp",
    },
    "NIDP_QUERY_API_TOKEN": {
        "display_name": "NIDP Query API · Bearer Token",
        "description": "Bearer token used by the wealth-advisor backend to authenticate to the NIDP Query API. Tokens start with nqt_. Use the Regenerate button to rotate.",
        "test_fn": None,
        "category": "nidp",
    },
    "GOOGLE_DOCAI_CREDENTIALS_JSON": {
        "display_name": "Google Document AI · Service Account JSON",
        "description": "Full contents of the GCP service-account key.json (paste verbatim). Required when CAS Parser Provider = nivesh_cas_parser. Create one at Google Cloud Console → IAM & Admin → Service Accounts → Keys → Add Key → JSON.",
        "test_fn": None,
        "category": "parsing",
    },
    "GOOGLE_DOCAI_PROJECT": {
        "display_name": "Google Document AI · Project ID",
        "description": "GCP project that owns the Document AI processor (e.g., spatial-acumen-431713-j3).",
        "test_fn": None,
        "category": "parsing",
    },
    "GOOGLE_DOCAI_PROCESSOR": {
        "display_name": "Google Document AI · Processor ID",
        "description": "Document AI processor id (the long hex string shown on the processor's detail page).",
        "test_fn": None,
        "category": "parsing",
    },
    "GOOGLE_DOCAI_LOCATION": {
        "display_name": "Google Document AI · Location",
        "description": "Processor region — typically 'us' or 'eu' (default: 'us').",
        "test_fn": None,
        "category": "parsing",
    },
    "OPENALGO_BASE_URL": {
        "display_name": "OpenAlgo · Base URL",
        "description": "Internal URL of the Nivesh-hosted OpenAlgo instance the backend calls for holdings/positions/funds. Example: https://openalgo-internal.nivesh.svc.cluster.local. When set, the user-facing Broker Connect form drops the URL field.",
        "test_fn": None,
        "category": "broker",
    },
    "OPENALGO_DASHBOARD_URL": {
        "display_name": "OpenAlgo · Dashboard URL (public)",
        "description": "Public URL where end-users sign in to the Nivesh-hosted OpenAlgo dashboard, connect their broker, and copy their API key. Often the same as the base URL; can be a separate ingress (e.g. https://openalgo.nivesh.ai). Surfaced in the Broker Connect modal as 'Open OpenAlgo dashboard'.",
        "test_fn": None,
        "category": "broker",
    },
    "OPENALGO_MANAGEMENT_TOKEN": {
        "display_name": "OpenAlgo · Management API Token",
        "description": "Shared secret the Nivesh backend uses to call OpenAlgo's /management/v1/users endpoint and auto-provision per-user OpenAlgo accounts + API keys. Must match `OPENALGO_MANAGEMENT_TOKEN` in OpenAlgo's .env. When set, end-users never see OpenAlgo's signup/login screens — Nivesh signs them in transparently using their Google email.",
        "test_fn": None,
        "category": "broker",
    },
    # ── Native broker app credentials (Nivesh SPC, OpenAlgo-free path) ──
    # Each broker requires the operator to register a developer app with
    # the broker (their partner/dev portal) once, copy the resulting
    # api_key/api_secret here, and register Nivesh's `/api/broker/native/
    # callback?broker=<slug>` URL as the redirect URI on the broker side.
    "BROKER_ZERODHA_API_KEY": {
        "display_name": "Zerodha (Kite Connect) · API Key",
        "description": "Kite Connect partner-app key. Register the Nivesh native broker connect URL `<host>/api/broker/native/callback?broker=zerodha` as the redirect URI on Zerodha's developer portal.",
        "test_fn": None, "category": "broker",
    },
    "BROKER_ZERODHA_API_SECRET": {
        "display_name": "Zerodha (Kite Connect) · API Secret",
        "description": "Companion secret to BROKER_ZERODHA_API_KEY. Used in the SHA-256 checksum during `generate_session`.",
        "test_fn": None, "category": "broker",
    },
    "BROKER_UPSTOX_API_KEY": {
        "display_name": "Upstox · API Key", "category": "broker", "test_fn": None,
        "description": "Upstox v2 app key. Register at https://account.upstox.com/developer/apps with redirect URI `<host>/api/broker/native/callback?broker=upstox`.",
    },
    "BROKER_UPSTOX_API_SECRET": {
        "display_name": "Upstox · API Secret", "category": "broker", "test_fn": None,
        "description": "Companion to BROKER_UPSTOX_API_KEY for the OAuth code-exchange POST.",
    },
    "BROKER_ANGEL_API_KEY": {
        "display_name": "Angel One (SmartAPI) · API Key", "category": "broker", "test_fn": None,
        "description": "SmartAPI key. Register at https://smartapi.angelbroking.com/. Form-auth — user enters client_code + password + TOTP in the Nivesh credential form.",
    },
    "BROKER_ANGEL_API_SECRET": {
        "display_name": "Angel One (SmartAPI) · API Secret", "category": "broker", "test_fn": None,
        "description": "Companion to BROKER_ANGEL_API_KEY.",
    },
    "BROKER_FYERS_API_KEY": {
        "display_name": "Fyers · API Key", "category": "broker", "test_fn": None,
        "description": "Fyers v3 app id (`<id>-<suffix>`). Register at https://myapi.fyers.in/dashboard/ with redirect URI `<host>/api/broker/native/callback?broker=fyers`.",
    },
    "BROKER_FYERS_API_SECRET": {
        "display_name": "Fyers · API Secret", "category": "broker", "test_fn": None,
        "description": "Companion to BROKER_FYERS_API_KEY for sha256(api_key:api_secret) checksum.",
    },
    "BROKER_DHAN_API_KEY": {
        "display_name": "Dhan · API Key (optional placeholder)", "category": "broker", "test_fn": None,
        "description": "Dhan uses long-lived per-user access tokens, not OAuth. End-users paste their Dhan trader-portal access_token + client_id directly into the Nivesh credential form.",
    },
    "BROKER_FIVEPAISA_API_KEY": {
        "display_name": "5paisa · API Key (App Name)", "category": "broker", "test_fn": None,
        "description": "Register at https://www.5paisa.com/developerapi/. Form-auth.",
    },
    "BROKER_FIVEPAISA_API_SECRET": {
        "display_name": "5paisa · API Secret (App Source)", "category": "broker", "test_fn": None,
        "description": "Companion to BROKER_FIVEPAISA_API_KEY.",
    },
    "BROKER_FIVEPAISA_USER_KEY": {
        "display_name": "5paisa · User Encryption Key", "category": "broker", "test_fn": None,
        "description": "Encryption key from 5paisa partner portal. Used as USER_KEY + ENCRYPTION_KEY.",
    },
    "BROKER_FIVEPAISA_USER_ID": {
        "display_name": "5paisa · User ID", "category": "broker", "test_fn": None,
        "description": "Partner portal user ID for 5paisa.",
    },
    "BROKER_ALICEBLUE_API_KEY": {
        "display_name": "AliceBlue · App Code", "category": "broker", "test_fn": None,
        "description": "Register at https://ant.aliceblueonline.com/. Used as `appcode` in OAuth URL.",
    },
    "BROKER_ALICEBLUE_API_SECRET": {
        "display_name": "AliceBlue · API Secret", "category": "broker", "test_fn": None,
        "description": "Companion to BROKER_ALICEBLUE_API_KEY for sha256(userId+authCode+secret) checksum.",
    },
}

# Module-level cache: DB overrides for the CURRENT running environment.
# Populated at startup + on update.
_cache: Dict[str, str] = {}

# ── Environment scoping ───────────────────────────────────────────────────
# Each deploy pins itself via the `APP_ENV` env var:
#   * "production" → production deploy (customer traffic)
#   * "preview"    → preview / staging / dev (default)
#
# Secrets are stored in three Mongo documents in `db.system_config`:
#   * {key: "secrets"}              — shared/legacy defaults (back-compat)
#   * {key: "secrets:preview"}      — preview-only overrides
#   * {key: "secrets:production"}   — production-only overrides
#
# Lookup precedence during hydration (for the *current* APP_ENV):
#   1. secrets:<APP_ENV>.values[key]
#   2. secrets.values[key]
#   3. os.environ[key]
#
# This means a preview deploy can point to a staging Neon / Upstash /
# Google OAuth client while production uses a completely different set —
# isolated end-to-end even if they happen to share the same Mongo.


def current_env() -> str:
    """Return the current deploy's environment tag: 'preview' | 'production'."""
    raw = os.environ.get("APP_ENV", "preview").strip().lower()
    return "production" if raw == "production" else "preview"


def _secrets_doc_key(env: Optional[str] = None) -> str:
    """Mongo doc key for the given environment (defaults to current)."""
    env = env or current_env()
    return f"secrets:{env}"


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
    """Load overrides for the CURRENT environment into _cache.

    Precedence (lowest → highest, later wins):
      1. Legacy shared `{key: "secrets"}` doc (unscoped defaults)
      2. Environment-scoped `{key: "secrets:<APP_ENV>"}` doc
    """
    # Step 1: shared/legacy defaults (back-compat for existing deploys)
    legacy = await db.system_config.find_one({"key": "secrets"}, {"_id": 0})
    if legacy and "values" in legacy:
        for k, v in (legacy.get("values") or {}).items():
            if isinstance(v, str) and v:
                _cache[k] = v
    # Step 2: environment-scoped overrides
    scoped = await db.system_config.find_one({"key": _secrets_doc_key()}, {"_id": 0})
    if scoped and "values" in scoped:
        for k, v in (scoped.get("values") or {}).items():
            if isinstance(v, str) and v:
                _cache[k] = v


async def list_for_env(db, env: str) -> List[Dict]:
    """Return every known + custom secret for a specific environment,
    including its masked value from that environment's Mongo doc.

    This is used by the Admin UI when an operator wants to view / edit
    the OTHER environment's secrets from their current deploy's panel.
    Does NOT mutate the in-process `_cache` — read-only operation.
    """
    doc = await db.system_config.find_one({"key": _secrets_doc_key(env)}, {"_id": 0})
    env_vals = (doc or {}).get("values", {}) if doc else {}
    # Fallback to legacy doc for keys missing in the scoped doc
    legacy = await db.system_config.find_one({"key": "secrets"}, {"_id": 0})
    legacy_vals = (legacy or {}).get("values", {}) if legacy else {}

    result: List[Dict] = []
    seen: set = set()
    for key, meta in KNOWN_SECRETS.items():
        scoped_val = env_vals.get(key, "")
        fallback_val = legacy_vals.get(key, "")
        effective = scoped_val or fallback_val
        result.append({
            "key": key,
            "display_name": meta["display_name"],
            "description": meta["description"],
            "category": meta["category"],
            "test_fn": meta["test_fn"],
            "has_env_fallback": bool(fallback_val),  # legacy shared value as fallback
            "has_override": bool(scoped_val),
            "masked_value": mask(effective),
            "configured": bool(effective),
            "is_custom": False,
        })
        seen.add(key)
    # Custom keys in scoped doc that aren't pre-registered
    for key, val in env_vals.items():
        if key in seen or not isinstance(val, str):
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


async def persist_to_db(db, key: str, value: Optional[str], updated_by: str = "",
                         env: Optional[str] = None) -> None:
    """Update one secret in DB + in-process cache atomically.

    Writes to the environment-scoped document (defaults to the current
    deploy's environment). If `env` points to a DIFFERENT environment,
    the in-process _cache is NOT touched — only the Mongo doc for the
    target env is updated, so a production deploy's cache stays pristine
    when an admin pre-seeds preview values from the production UI (or
    vice-versa).
    """
    from datetime import datetime, timezone
    target_env = (env or current_env()).strip().lower()
    target_env = "production" if target_env == "production" else "preview"
    doc_key = _secrets_doc_key(target_env)

    # Only mutate in-process cache when writing to the CURRENT env
    if target_env == current_env():
        set_override(key, value)

    update_path = f"values.{key}"
    if value:
        await db.system_config.update_one(
            {"key": doc_key},
            {
                "$set": {
                    update_path: value,
                    "env": target_env,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "updated_by": updated_by,
                },
                "$setOnInsert": {"key": doc_key},
            },
            upsert=True,
        )
    else:
        await db.system_config.update_one(
            {"key": doc_key},
            {
                "$unset": {update_path: ""},
                "$set": {
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "updated_by": updated_by,
                },
            },
        )
