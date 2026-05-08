"""Upsert event calendar rows into nidp.event_calendar."""
from __future__ import annotations

import logging
from typing import Any

from nidp.shared.storage.pg import get_pool

logger = logging.getLogger(__name__)


async def upsert_events(events: list[dict[str, Any]]) -> int:
    if not events:
        return 0
    pool = await get_pool()
    inserted = 0
    async with pool.acquire() as conn:
        for ev in events:
            try:
                await conn.execute(
                    """
                    INSERT INTO nidp.event_calendar
                        (symbol, company_name, event_type, event_date,
                         period, purpose, ex_date, record_date, source)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                    ON CONFLICT (symbol, event_type, event_date, period)
                    DO UPDATE SET
                        company_name = EXCLUDED.company_name,
                        purpose      = EXCLUDED.purpose,
                        ex_date      = COALESCE(EXCLUDED.ex_date, nidp.event_calendar.ex_date),
                        record_date  = COALESCE(EXCLUDED.record_date, nidp.event_calendar.record_date),
                        fetched_at   = NOW()
                    """,
                    ev["symbol"],
                    ev.get("company_name") or "",
                    ev["event_type"],
                    ev["event_date"],
                    ev.get("period"),
                    ev.get("purpose") or "",
                    ev.get("ex_date"),
                    ev.get("record_date"),
                    ev.get("source", "nse"),
                )
                inserted += 1
            except Exception as e:
                logger.warning("upsert_events skipped %s/%s: %s", ev.get("symbol"), ev.get("event_date"), e)
    return inserted
