#!/usr/bin/env python3
"""record_fno_forward.py: record the day's near-month short build-up signals for the forward test (services/fno_forward). Writes ONE document per session to Mongo (first write wins).

    docker exec -w /app/backend nivesh-staging-app-backend python -m scripts.record_fno_forward            # the latest session in the build-up scan
    docker exec -w /app/backend nivesh-staging-app-backend python -m scripts.record_fno_forward --dry-run  # show what would be recorded; writes nothing

A session is recorded only while it is still "in time": before the next trading day's 09:15 IST open (a signal recorded after the next open is not point in time and is refused). It reads
the build-up scan for the day and each underlying's futures; a failed read leaves that underlying without a state (counted), never a guess.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import date, datetime, time as dtime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("fno_forward")
IST = timezone(timedelta(hours=5, minutes=30))


def next_open(as_of: str) -> datetime:
    """09:15 IST of the next weekday after `as_of` (exchange holidays ignored: the guard errs on the side of recording sooner)."""
    d = date.fromisoformat(as_of) + timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return datetime.combine(d, dtime(9, 15), tzinfo=IST)


def in_time(as_of: str, now: Optional[datetime] = None) -> bool:
    return (now or datetime.now(IST)) < next_open(as_of)


async def main(dry: bool, force_date: Optional[str]) -> int:
    from routes import fno as route
    from services import fno_forward as ff
    from deps import db

    body = await route._daas("/desk/fno-buildup", {"date": force_date} if force_date else {}, "stock futures")
    as_of = route._iso_day(body.get("as_of"))
    symbols = sorted({str(r["symbol"]).upper() for r in body.get("rows") or [] if isinstance(r, dict) and r.get("symbol")})
    if not as_of or not symbols:
        log.error("the build-up scan has no day or no rows: nothing recorded")
        return 2
    if not in_time(as_of):
        log.error("session %s is past the next open (%s): a signal recorded now is not point in time, so nothing is recorded", as_of, next_open(as_of).isoformat())
        return 3
    gate = asyncio.Semaphore(6)
    states: Dict[str, Any] = {}
    failed = 0

    async def one(sym: str) -> None:
        nonlocal failed
        async with gate:
            try:
                rows, _ = await route._futures_rows(sym)
            except Exception:  # noqa: BLE001
                failed += 1
                states[sym] = None
                return
        rows = [r for r in rows if route._iso_day(r.get("as_of_date")) == as_of]
        states[sym] = ff.near_state(route.shape_futures(rows, route.find_spot(rows)))

    await asyncio.gather(*(one(s) for s in symbols))
    doc = ff.build_record(as_of, states)
    log.info("session %s: %d underlyings, %d with a state, %d reads failed; production_floors %d signals, no_threshold %d signals",
             as_of, len(symbols), doc["with_state"], failed, len(doc["settings"]["production_floors"]), len(doc["settings"]["no_threshold"]))
    if dry:
        log.info("dry run: nothing written")
        return 0
    wrote = await ff.record(db, as_of, states)
    log.info("recorded" if wrote else "already recorded for %s: left untouched (first write wins)", as_of)
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Record the forward test's signals for the latest session")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--date", help="YYYY-MM-DD: ask the scan for that day (still refused when past the next open)")
    a = ap.parse_args()
    sys.exit(asyncio.run(main(a.dry_run, a.date)))
