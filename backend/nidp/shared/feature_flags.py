"""Runtime feature flags for NIDP services.

Two-layer check (fastest first):
  1. Env var NIDP_FEATURE_<FLAG_NAME>=0  →  disabled regardless of DB
  2. nidp.feature_flags table in Postgres  →  DB-level toggle

Use `is_enabled(flag)` anywhere before running optional processing:

    if not await is_enabled("event_processing"):
        logger.info("event_processing flag is OFF — skipping")
        return

Flags can be toggled live without redeployment:
    UPDATE nidp.feature_flags SET enabled=false WHERE flag_name='d1_prep';
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


async def is_enabled(flag_name: str, default: bool = True) -> bool:
    """Return True if the named feature flag is enabled."""
    # Env var override — instant kill without DB round-trip
    env_key = "NIDP_FEATURE_" + flag_name.upper().replace("-", "_")
    env_val = os.environ.get(env_key)
    if env_val is not None:
        enabled = env_val.strip().lower() not in ("0", "false", "no", "off", "disabled")
        if not enabled:
            logger.info("feature_flag %s: OFF via env var %s", flag_name, env_key)
        return enabled

    # DB check
    try:
        from nidp.shared.storage.pg import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT enabled FROM nidp.feature_flags WHERE flag_name = $1",
                flag_name,
            )
        if row is not None:
            if not row["enabled"]:
                logger.info("feature_flag %s: OFF via DB flag", flag_name)
            return bool(row["enabled"])
    except Exception as e:
        logger.warning("feature_flag: DB check failed for %s (%s) — defaulting to %s",
                       flag_name, e, default)

    return default


async def set_flag(flag_name: str, enabled: bool, notes: Optional[str] = None) -> None:
    """Toggle a feature flag in the DB (used by CLI)."""
    from nidp.shared.storage.pg import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO nidp.feature_flags (flag_name, enabled, notes, updated_at)
            VALUES ($1, $2, $3, NOW())
            ON CONFLICT (flag_name) DO UPDATE
                SET enabled = EXCLUDED.enabled,
                    notes   = COALESCE($3, nidp.feature_flags.notes),
                    updated_at = NOW()
            """,
            flag_name, enabled, notes,
        )
    logger.info("feature_flag %s set to %s", flag_name, enabled)


async def list_flags() -> list[dict]:
    from nidp.shared.storage.pg import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT flag_name, enabled, notes, updated_at FROM nidp.feature_flags ORDER BY flag_name"
        )
    return [dict(r) for r in rows]
