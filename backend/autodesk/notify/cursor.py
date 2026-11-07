"""Reads new desk events by cursor (autodesk.event_cursors, an existing table) and hands them to the notifier."""
from __future__ import annotations

import asyncio

import asyncpg

from .notifier import Notifier

CONSUMER = "slack-notifier"
BATCH = 200


async def _save(c: asyncpg.Connection, seq: int) -> None:
    await c.execute("""INSERT INTO autodesk.event_cursors (consumer, last_seq) VALUES ($1,$2)
                       ON CONFLICT (consumer) DO UPDATE SET last_seq=EXCLUDED.last_seq, updated_at=now()""",
                    CONSUMER, seq)


async def run_pending(c: asyncpg.Connection, notifier: Notifier) -> int:
    """Process the next batch of events after the cursor; returns how many events were read.

    - The first ever run starts at the newest event: history from before the notifier existed is not replayed.
    - A disabled notifier does not move the cursor, so events are not lost if it is enabled later.
    - The cursor moves after the batch was attempted (at most once per event: a failure is recorded in the log and not
      retried forever)."""
    if not notifier.enabled:
        return 0
    last = await c.fetchval("SELECT last_seq FROM autodesk.event_cursors WHERE consumer=$1", CONSUMER)
    if last is None:
        await _save(c, int(await c.fetchval("SELECT COALESCE(MAX(seq),0) FROM autodesk.events")))
        return 0
    rows = [dict(r) for r in await c.fetch("SELECT * FROM autodesk.events WHERE seq>$1 ORDER BY seq LIMIT $2",
                                           last, BATCH)]
    if not rows:
        return 0
    await asyncio.to_thread(notifier.process, rows)
    await _save(c, rows[-1]["seq"])
    return len(rows)
