"""Invoke nidp.refresh_mf_derived_analytics and surface its row count."""
from __future__ import annotations

import logging
import os
from datetime import date
from typing import Optional

from nidp.shared.storage.pg import get_pool

logger = logging.getLogger(__name__)


async def run(
    target_date: Optional[date] = None,
    force: Optional[bool] = None,
) -> dict:
    if target_date is None:
        target_date = date.today()
    if force is None:
        force = os.environ.get("MF_DERIVED_FORCE", "").lower() in ("1", "true", "yes")

    pool = await get_pool()
    async with pool.acquire() as conn:
        n = await conn.fetchval(
            "SELECT nidp.refresh_mf_derived_analytics($1::date, $2::boolean)",
            target_date, force,
        )

    inserted = int(n or 0)
    logger.info("mf_derived_refresh as_of=%s force=%s schemes_refreshed=%d",
                target_date, force, inserted)
    return {"as_of_date": target_date.isoformat(),
            "force": force,
            "rows_inserted": inserted}
