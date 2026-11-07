"""Background task of the desk process: the live paper tick (PHASE2_DESIGN §6.2). Every few seconds in session hours it
submits validated desk intents, prices working paper orders from FRESH live quotes, expires them at the close and marks open
positions. Outside session hours it wakes once a minute (so a missed close still expires orders). It never raises: a failed
tick is logged and the next one tries again."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time as dtime, timezone

from ..market.view import IST
from . import settle

log = logging.getLogger(__name__)
TICK_S = 5.0
IDLE_S = 60.0


def in_session_hours(now: datetime) -> bool:
    t = now.astimezone(IST)
    return t.weekday() < 5 and dtime(9, 0) <= t.time() <= dtime(15, 45)


async def run(gw, *, stop: asyncio.Event) -> None:
    last_close_day = None
    last_eod_day = None
    while not stop.is_set():
        now = datetime.now(timezone.utc)
        try:
            await settle.live_tick(gw, now=now)
            t = now.astimezone(IST)
            if gw.lifecycle is None:
                if t.time() >= dtime(15, 31) and last_close_day != t.date():
                    await settle.live_close(gw, now=now)
                    last_close_day = t.date()
            else:     # Phase 3: the day's final mark after every segment ends, corrected by the exchange's close (PHASE3_DESIGN §10.2)
                from ..lifecycle import marks
                if t.time() >= marks.FINAL_MARK_IST and last_close_day != t.date():
                    await marks.final_mark(gw, now=now)
                    last_close_day = t.date()
                if t.time() >= marks.EOD_CORRECTION_IST and last_eod_day != t.date():
                    await marks.eod_correction(gw, now=now)
                    last_eod_day = t.date()
        except Exception:  # noqa: BLE001 — the loop must survive; the failure is in the log
            log.exception("live execution tick failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=TICK_S if in_session_hours(now) else IDLE_S)
        except asyncio.TimeoutError:
            pass
