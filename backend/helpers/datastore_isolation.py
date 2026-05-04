"""Detect and refuse cross-environment datastore sharing.

A production deploy that points at the same Mongo / Postgres / Redis as
the preview deploy is a data-leak waiting to happen — preview test
sessions, parsed CAS payloads, holdings, audit logs all flow into the
same physical store, and a customer in production can see (or worse,
overwrite) data that was created from preview traffic.

This module provides:
  * `fingerprint(url)` — non-reversible 10-char SHA-256 prefix, safe to
    log without leaking the credential.
  * `audit_isolation(db)` — returns the per-env fingerprint matrix for
    `MONGO_URL`, `POSTGRES_URL`, `REDIS_URL` so admins can see whether
    the current `APP_ENV` shares a backing store with the other env.
  * `enforce_isolation_at_startup(db)` — called from server startup;
    HARD-FAILS when the active environment is `production` AND any of
    the data URLs collide with the preview-doc value, unless the
    operator opts out with `ALLOW_SHARED_DATASTORES=1`.

Mongo `MONGO_URL` is special: it can't be stored in `system_config`
(chicken-and-egg), so we read it from the live process env and compare
against whatever fingerprint the *other* environment's docs reference
indirectly — pragmatically we just compare against the other env's
declared `MONGO_URL_HINT` if the operator stores one for sanity checks.
"""
from __future__ import annotations
import hashlib
import logging
import os
from typing import Any, Dict, List, Optional

from helpers import secrets as _secrets

logger = logging.getLogger(__name__)


# Keys we treat as datastore credentials. Mongo is special: its URL is
# pulled from process env (not the Mongo-stored secrets doc), so we
# read from os.environ for the live value and from a sibling _HINT key
# in the secrets doc for the *other* env's expected value.
DATASTORE_KEYS = ("MONGO_URL", "POSTGRES_URL", "REDIS_URL")


def fingerprint(url: Optional[str]) -> Optional[str]:
    """Return a 10-char SHA-256 prefix of the URL — stable across calls,
    safe to log because it can't be reversed back to the credential."""
    if not url:
        return None
    return hashlib.sha256(url.strip().encode()).hexdigest()[:10]


async def _read_env_url(db, env: str, key: str) -> Optional[str]:
    """Read the configured URL for `key` in the given `env`'s secrets
    doc. Falls back to MONGO_URL_HINT-style sibling keys when the
    canonical key isn't stored (Mongo case)."""
    if key == "MONGO_URL":
        if env == _secrets.current_env():
            return os.environ.get("MONGO_URL")
        # For the OTHER env, the operator can stash a non-credential
        # marker so isolation can still be audited. Empty if absent —
        # we just don't compare.
        doc = await db.system_config.find_one(
            {"key": _secrets._secrets_doc_key(env)}, {"_id": 0, "values": 1},
        )
        return ((doc or {}).get("values") or {}).get("MONGO_URL_HINT")

    doc = await db.system_config.find_one(
        {"key": _secrets._secrets_doc_key(env)}, {"_id": 0, "values": 1},
    )
    return ((doc or {}).get("values") or {}).get(key)


async def audit_isolation(db) -> Dict[str, Any]:
    """Return a per-env fingerprint matrix, a list of collisions, AND the
    fingerprint each live subsystem (pg pool, redis client, mongo
    client) is actually using right now — so an operator can confirm an
    admin-UI secret edit has been picked up without needing to read the
    URL itself.

    Surfaced to admins via `GET /api/admin/datastore-isolation`.
    """
    envs = ("preview", "production")
    matrix: Dict[str, Dict[str, Optional[str]]] = {}
    for key in DATASTORE_KEYS:
        per_env: Dict[str, Optional[str]] = {}
        for env in envs:
            url = await _read_env_url(db, env, key)
            per_env[env] = fingerprint(url)
            per_env[f"{env}_set"] = bool(url)
        matrix[key] = per_env

    collisions: List[Dict[str, Any]] = []
    for key, per_env in matrix.items():
        fp_pre = per_env.get("preview")
        fp_prd = per_env.get("production")
        if fp_pre and fp_prd and fp_pre == fp_prd:
            collisions.append({
                "key": key,
                "fingerprint": fp_pre,
                "message": (
                    f"{key} is identical across preview and production "
                    f"— production traffic is hitting the preview "
                    f"datastore. Provision a separate {key} for "
                    f"production and paste it into the production "
                    f"secrets doc (system_config.secrets:production)."
                ),
            })

    # Live fingerprints — what the subsystems are actually bound to right
    # now. If these differ from the active-env's expected fingerprint,
    # the secret edit hasn't been picked up (or the pool is stale).
    live: Dict[str, Any] = {}
    try:
        from services import pg_client as _pg
        live["POSTGRES_URL"] = {
            "fingerprint": fingerprint(_pg._last_url),
            "pool_initialised": _pg._pool is not None,
        }
    except Exception:  # noqa: BLE001
        live["POSTGRES_URL"] = {"fingerprint": None, "pool_initialised": False}
    try:
        from services import redis_client as _rc
        live["REDIS_URL"] = {
            "fingerprint": fingerprint(_rc._last_url) if _rc._last_url else None,
            "client_initialised": _rc._client is not None,
        }
    except Exception:  # noqa: BLE001
        live["REDIS_URL"] = {"fingerprint": None, "client_initialised": False}
    live["MONGO_URL"] = {
        "fingerprint": fingerprint(os.environ.get("MONGO_URL")),
        "client_initialised": True,  # always set if the request reached us
    }
    # Cross-check: live fingerprint should match the active-env's stored
    # fingerprint. If not, the operator just edited a secret and the
    # subsystem hasn't refreshed yet — happens for ~1 request after edit
    # because pg_client / redis_client check `_last_url` lazily.
    active = _secrets.current_env()
    drift: List[Dict[str, Any]] = []
    for key in DATASTORE_KEYS:
        expected = matrix.get(key, {}).get(active)
        actual = live.get(key, {}).get("fingerprint")
        if expected and actual and expected != actual:
            drift.append({
                "key": key,
                "expected": expected,
                "actual": actual,
                "message": (
                    f"Live {key} subsystem is using a different URL than "
                    f"system_config.secrets:{active}. Either the secret "
                    f"was edited and the pool hasn't refreshed yet, or "
                    f"the process started before hydration completed."
                ),
            })

    return {
        "active_env": active,
        "matrix": matrix,
        "live": live,
        "drift": drift,
        "collisions": collisions,
        "ok": not collisions and not drift,
    }


async def enforce_isolation_at_startup(db) -> None:
    """Refuse to fully start a `production` deploy when any datastore
    URL matches the preview env's. Logs a warning and raises unless the
    operator explicitly opts out with `ALLOW_SHARED_DATASTORES=1`.

    Preview deploys log warnings but never raise — this is a one-way
    safety net for the customer-facing tier."""
    audit = await audit_isolation(db)
    collisions = audit["collisions"]
    active = audit["active_env"]

    if not collisions:
        logger.info(
            "datastore isolation OK — preview vs production fingerprints "
            "differ for %s", ", ".join(DATASTORE_KEYS),
        )
        return

    for c in collisions:
        logger.warning(
            "datastore isolation breach: %s preview=%s production=%s — %s",
            c["key"], c["fingerprint"], c["fingerprint"], c["message"],
        )

    if active == "production" and os.environ.get("ALLOW_SHARED_DATASTORES") != "1":
        keys = ", ".join(c["key"] for c in collisions)
        raise RuntimeError(
            f"Refusing to start production deploy: {keys} share fingerprint "
            f"with preview. Set distinct values in "
            f"system_config.secrets:production, OR override with "
            f"ALLOW_SHARED_DATASTORES=1 (NOT recommended)."
        )
