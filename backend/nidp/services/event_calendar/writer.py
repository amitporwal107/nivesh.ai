"""Upsert event calendar rows into nidp.event_calendar.

first_seen_at is written once, on INSERT, and never updated: it is when NIDP
first saw the event. fetched_at still moves on every refresh, so it cannot
answer "was this known yesterday?". Backfilled rows — history NIDP did not
observe live — get first_seen_at NULL and never overwrite live-captured fields;
they only fill in intimated_at (the exchange's own known-since time).
"""
from __future__ import annotations

import logging
from typing import Any

from nidp.shared.storage.pg import get_pool

logger = logging.getLogger(__name__)

_LIVE_SQL = """
INSERT INTO nidp.event_calendar
    (symbol, company_name, event_type, event_date,
     period, purpose, ex_date, record_date, source,
     intimated_at, first_seen_at)
VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,NOW())
ON CONFLICT (symbol, event_type, event_date, COALESCE(period, ''))
DO UPDATE SET
    company_name = EXCLUDED.company_name,
    purpose      = EXCLUDED.purpose,
    period       = COALESCE(EXCLUDED.period, nidp.event_calendar.period),
    ex_date      = COALESCE(EXCLUDED.ex_date, nidp.event_calendar.ex_date),
    record_date  = COALESCE(EXCLUDED.record_date, nidp.event_calendar.record_date),
    intimated_at = COALESCE(nidp.event_calendar.intimated_at, EXCLUDED.intimated_at),
    fetched_at   = NOW()
"""

_BACKFILL_SQL = """
INSERT INTO nidp.event_calendar
    (symbol, company_name, event_type, event_date,
     period, purpose, ex_date, record_date, source,
     intimated_at, first_seen_at)
VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,NULL)
ON CONFLICT (symbol, event_type, event_date, COALESCE(period, ''))
DO UPDATE SET
    intimated_at = COALESCE(nidp.event_calendar.intimated_at, EXCLUDED.intimated_at)
"""


_STAMP_SQL = """
UPDATE nidp.event_calendar
   SET intimated_at = $3
 WHERE symbol = $1 AND event_date = $2 AND intimated_at IS NULL
"""


async def stamp_existing(events: list[dict[str, Any]]) -> int:
    """Fill intimated_at on rows already in the table for (symbol, event_date),
    whatever their type/period label. Returns the number of rows updated."""
    pool = await get_pool()
    updated = 0
    async with pool.acquire() as conn:
        for ev in events:
            if not ev.get("intimated_at"):
                continue
            tag = await conn.execute(_STAMP_SQL, ev["symbol"], ev["event_date"], ev["intimated_at"])
            updated += int(tag.rsplit(" ", 1)[-1])
    return updated


async def upsert_events(events: list[dict[str, Any]], *, backfill: bool = False) -> int:
    if not events:
        return 0
    sql = _BACKFILL_SQL if backfill else _LIVE_SQL
    pool = await get_pool()
    inserted = 0
    async with pool.acquire() as conn:
        for ev in events:
            try:
                await conn.execute(
                    sql,
                    ev["symbol"],
                    ev.get("company_name") or "",
                    ev["event_type"],
                    ev["event_date"],
                    ev.get("period"),
                    ev.get("purpose") or "",
                    ev.get("ex_date"),
                    ev.get("record_date"),
                    ev.get("source", "nse"),
                    ev.get("intimated_at"),
                )
                inserted += 1
            except Exception as e:
                logger.warning("upsert_events skipped %s/%s: %s", ev.get("symbol"), ev.get("event_date"), e)
    return inserted
