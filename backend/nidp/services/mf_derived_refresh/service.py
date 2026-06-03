"""Invoke compute_mf_derived_analytics per-scheme with controlled concurrency.

Replaces the single PL/pgSQL refresh_mf_derived_analytics() call, which
crashed the DB (OOM / lock contention) when iterating 14k schemes in one
long-running transaction. This version:
  - fetches active schemes once
  - calls compute_mf_derived_analytics(scheme, date) for each with asyncpg
  - limits concurrency to CONCURRENCY (default 12) to stay within
    max_connections=25 budget shared with other services
  - each compute call is its own small transaction — no one crash kills all
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import date
from typing import Optional

from nidp.shared.storage.pg import get_pool

logger = logging.getLogger(__name__)

CONCURRENCY = int(os.environ.get("MF_DERIVED_CONCURRENCY", "10"))
LOG_EVERY   = int(os.environ.get("MF_DERIVED_LOG_EVERY", "500"))


async def run(
    target_date: Optional[date] = None,
    force: Optional[bool] = None,
) -> dict:
    if target_date is None:
        target_date = date.today()
    if force is None:
        force = os.environ.get("MF_DERIVED_FORCE", "").lower() in ("1", "true", "yes")

    pool = await get_pool()

    # Load all active schemes
    async with pool.acquire() as conn:
        if force:
            # Recompute all active schemes (upsert overwrites existing rows)
            schemes = [r["scheme_code"] for r in await conn.fetch(
                "SELECT scheme_code FROM nidp.mf_scheme_master WHERE status = 'active' ORDER BY scheme_code"
            )]
        else:
            # Skip schemes that already have a recent row (within 7 days)
            schemes = [r["scheme_code"] for r in await conn.fetch(
                """
                SELECT sm.scheme_code
                FROM nidp.mf_scheme_master sm
                WHERE sm.status = 'active'
                  AND NOT EXISTS (
                      SELECT 1 FROM nidp.mf_derived_analytics da
                      WHERE da.scheme_code = sm.scheme_code
                        AND da.as_of_date > $1::date - 7
                  )
                ORDER BY sm.scheme_code
                """,
                target_date,
            )]

    total = len(schemes)
    logger.info("mf_derived_refresh: as_of=%s force=%s schemes=%d concurrency=%d",
                target_date, force, total, CONCURRENCY)

    sem  = asyncio.Semaphore(CONCURRENCY)
    done = 0
    ok   = 0

    async def _one(scheme: str) -> None:
        nonlocal done, ok
        async with sem:
            async with pool.acquire() as conn:
                try:
                    await conn.execute(
                        "SELECT nidp.compute_mf_derived_analytics($1, $2)",
                        scheme, target_date,
                    )
                    ok_flag = True
                except Exception as exc:
                    logger.warning("mf_derived_refresh: skip %s: %s", scheme, exc)
                    ok_flag = False
        done += 1
        if ok_flag:
            ok += 1
        if done % LOG_EVERY == 0:
            logger.info("mf_derived_refresh: %d/%d (%.1f%%) ok=%d",
                        done, total, 100 * done / total, ok)

    await asyncio.gather(*[_one(s) for s in schemes])

    logger.info("mf_derived_refresh: DONE as_of=%s schemes=%d/%d ok=%d",
                target_date, ok, total, ok)
    return {
        "as_of_date": target_date.isoformat(),
        "force":      force,
        "rows_inserted": ok,
    }
