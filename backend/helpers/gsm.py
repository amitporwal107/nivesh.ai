"""Google Secret Manager — minimal read-side wrapper.

Used as the source of truth for a small set of operationally rotated
secrets (currently: the CAS Parser rotating key pool). Most app secrets
still live in the DB-backed admin console / env vars via
``helpers.secrets``; that path is intentionally untouched.

Behaviour:
  * ``get(name)`` returns the latest version's string value (or ``None``).
  * Results are cached in-process for ``CACHE_TTL_S`` seconds to keep the
    request hot-path fast and to cap GSM API spend.
  * ``reload(name)`` evicts the cache entry for ``name`` so the next read
    re-fetches — call this after ``gcloud secrets versions add ...``.
  * If GCP credentials are unavailable (local dev, no SA mounted), all
    reads return ``None`` instead of raising, so the app still boots.

Project resolution order:
  1. ``GSM_PROJECT`` env var (explicit override)
  2. ``GCP_PROJECT`` env var (matches other NIDP code paths)
  3. ``GOOGLE_CLOUD_PROJECT`` env var (GCP convention)
  4. ``"niveshdataintelligence"`` (last-resort default — matches deploy)
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Dict, Optional, Tuple

logger = logging.getLogger("gsm")

CACHE_TTL_S = float(os.environ.get("GSM_CACHE_TTL_S", "300"))  # 5 min

_DEFAULT_PROJECT = "niveshdataintelligence"

_client = None  # google.cloud.secretmanager.SecretManagerServiceClient | None
_client_init_failed = False
_client_lock = threading.Lock()

_cache_lock = threading.Lock()
_cache: Dict[str, Tuple[Optional[str], float]] = {}  # name -> (value, fetched_at)


def project_id() -> str:
    return (
        os.environ.get("GSM_PROJECT")
        or os.environ.get("GCP_PROJECT")
        or os.environ.get("GOOGLE_CLOUD_PROJECT")
        or _DEFAULT_PROJECT
    )


def _get_client():
    """Lazy, single-attempt client init. If init fails (e.g. no creds in
    local dev), we remember that and stop trying so we don't spam logs."""
    global _client, _client_init_failed
    if _client is not None or _client_init_failed:
        return _client
    with _client_lock:
        if _client is not None or _client_init_failed:
            return _client
        try:
            from google.cloud import secretmanager  # type: ignore
            _client = secretmanager.SecretManagerServiceClient()
            logger.info("GSM client initialised (project=%s)", project_id())
        except Exception as e:  # noqa: BLE001 — also catches ImportError + DefaultCredentialsError
            _client_init_failed = True
            logger.warning(
                "GSM client unavailable — secrets sourced from GSM will be None. (%s)",
                e,
            )
    return _client


def get(name: str) -> Optional[str]:
    """Fetch the latest enabled version of secret ``name``. Cached for
    ``CACHE_TTL_S``. Returns ``None`` if the secret is missing, access
    is denied, or GSM is unavailable — caller decides what that means."""
    if not name:
        return None
    now = time.time()
    with _cache_lock:
        hit = _cache.get(name)
        if hit and (now - hit[1]) < CACHE_TTL_S:
            return hit[0]

    client = _get_client()
    if client is None:
        with _cache_lock:
            _cache[name] = (None, now)
        return None

    secret_path = f"projects/{project_id()}/secrets/{name}/versions/latest"
    try:
        resp = client.access_secret_version(request={"name": secret_path})
        value = resp.payload.data.decode("utf-8")
    except Exception as e:  # noqa: BLE001 — NotFound, PermissionDenied, transient errors
        logger.warning("GSM read failed for %s: %s", name, e)
        value = None

    with _cache_lock:
        _cache[name] = (value, now)
    return value


def get_for_env(name: str, default: Optional[str] = None) -> Optional[str]:
    """Environment-aware secret read.

    Resolution order:
      1. GSM ``<NAME>_<ENV>``  (e.g. ``MONGO_URL_STAGING``) — env-specific
      2. GSM ``<NAME>``        (e.g. ``OPENAI_API_KEY``)    — shared across envs
      3. ``<NAME>`` env var                                  — last-resort fallback
      4. ``default``

    ``<ENV>`` is ``APP_ENV`` uppercased (``STAGING`` / ``PROD``). This lets a
    single GSM project hold both env-specific secrets and shared ones, while
    the env var stays as a fallback so nothing breaks before (or during) the
    migration of values into GSM. Once every read site uses this and GSM is
    populated, the secret can be removed from the env file.
    """
    env = (os.environ.get("APP_ENV") or "").strip().upper()
    if env:
        v = get(f"{name}_{env}")
        if v:
            return v
    v = get(name)
    if v:
        return v
    return os.environ.get(name, default)


def reload(name: str) -> None:
    """Evict ``name`` from the cache so the next ``get`` re-fetches from GSM.
    Call after ``gcloud secrets versions add <name> --data-file=-``."""
    with _cache_lock:
        _cache.pop(name, None)


def cache_size() -> int:
    """For diagnostics / health endpoints."""
    with _cache_lock:
        return len(_cache)
