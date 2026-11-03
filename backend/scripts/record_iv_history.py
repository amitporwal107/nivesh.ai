#!/usr/bin/env python3
"""record_iv_history.py: record each F&O underlying's daily ATM implied volatility (services/fno_iv_history, Mongo
`fno_iv_history`), the figures GET /api/fno/{symbol}/iv-history serves. One document per underlying and session,
upserted by that key, so a rerun leaves one document.

    docker exec -w /app/backend nivesh-staging-app-backend python -m scripts.record_iv_history                  # the latest session, every underlying in the build-up scan
    docker exec -w /app/backend nivesh-staging-app-backend python -m scripts.record_iv_history --dry-run        # work it out and print the counts; writes nothing
    docker exec -w /app/backend nivesh-staging-app-backend python -m scripts.record_iv_history --symbols NIFTY,BANKNIFTY
    docker exec -w /app/backend nivesh-staging-app-backend python -m scripts.record_iv_history --backfill-days 260 --symbols NIFTY,BANKNIFTY --dry-run

Where the figures come from: the data platform's stored NSE F&O bhavcopy (nidp.fno_bhavcopy), one session at a time,
through DaaS /v1/fno/{symbol}?on=<day> (four futures reads, then one read per bucket expiry), worked out by
routes/fno.py :: session_iv, the chain route's own model. The latest session and the default universe are those of
the build-up scan (DaaS /desk/fno-buildup), as scripts/record_fno_forward.py does.

Backfill (--backfill-days N, or --start/--end): every WEEKDAY in the range is asked for. A weekday the data platform
has no rows for (an exchange holiday, a day not loaded) is skipped and counted as no_rows; a read that fails or
answers for another day is skipped and counted as failed. Nothing is interpolated, carried over or set to zero.
Sessions already stored with the current calculation version are skipped unless --recompute. Cost: about six
data-platform reads per underlying per weekday (260 weekdays x 2 indices is about 3,100 reads), so a backfill of the
whole universe (about 220 underlyings) is better run per group of symbols.

Exit codes: 0 every read answered; 2 the build-up scan gave no session; 4 some reads failed (counted in the log).

Schedule (documented here, NOT installed; installing it is a separate, approved step). After the NIDP F&O bhavcopy
ingest's last retry at 22:15 IST (deploy/cloudpe/nidp/nidp-staging.cron) and the forward-test recorder at 22:45:

    # /etc/cron.d/nivesh-staging-iv-history
    CRON_TZ=Asia/Kolkata
    0 23 * * 1-5  root  /usr/bin/docker exec nivesh-staging-app-backend python -m scripts.record_iv_history >> /opt/nivesh-staging/logs/iv-history.log 2>&1
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("iv_history")

CONCURRENCY = 4          # underlying-sessions in flight; each makes about six reads


def weekdays(start: date, end: date) -> List[str]:
    """Every Monday-to-Friday from `start` to `end`, inclusive, oldest first. Exchange holidays are not known
    here: the data platform answering with no rows for one is what skips it."""
    out: List[str] = []
    d = start
    while d <= end:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def backfill_start(end: date, n_weekdays: int) -> date:
    """The first day of the `n_weekdays` weekdays that end at `end`."""
    d, seen = end, 0
    while True:
        if d.weekday() < 5:
            seen += 1
            if seen >= n_weekdays:
                return d
        d -= timedelta(days=1)


def scan_universe(body: Dict[str, Any]) -> List[str]:
    """Every underlying the build-up scan lists: its index rows and its stock rows."""
    out = set()
    for key in ("indices", "rows"):
        for r in body.get(key) or []:
            if isinstance(r, dict) and r.get("symbol"):
                out.add(str(r["symbol"]).upper())
    return sorted(out)


async def record_one(db, sym: str, day: str, method: str, dry: bool) -> str:
    """Read, work out and (unless dry) upsert one underlying's session. Returns the outcome: "written" (new),
    "updated", "dry", "no_rows" (the data platform has no rows that day: nothing written) or "failed" (a read
    failed or answered for another day: nothing written, never a zero)."""
    from routes import fno as route
    from services import fno_iv_history as store
    from services import option_pricing

    try:
        got = await route.read_session(sym, day)
    except Exception as e:  # noqa: BLE001 — counted and logged; the session is not written
        log.warning("%s %s: the data platform read failed (%s): nothing written", sym, day, getattr(e, "detail", type(e).__name__))
        return "failed"
    if got is None:
        return "no_rows"
    buckets = route.session_iv(day, got["futures"], got["expiries"])
    doc = store.build_doc(sym, day, buckets, round(option_pricing.RISK_FREE_RATE * 100, 4))
    if dry:
        near = buckets["near_month"]
        log.info("%s %s: near_month %s atm_iv %s (%s)", sym, day, near["expiry"], near["atm_iv"], near["reason"] or near["forward_basis"])
        return "dry"
    return "written" if await store.upsert(db, doc, method) else "updated"


async def run(db, symbols: Iterable[str], days: List[str], method: str, dry: bool, skip_existing: bool) -> Counter:
    from services import fno_iv_history as store

    counts: Counter = Counter()
    gate = asyncio.Semaphore(CONCURRENCY)
    jobs = []
    for sym in symbols:
        have = await store.recorded_days(db, sym) if skip_existing else set()
        for day in days:
            if day in have:
                counts["skipped_existing"] += 1
            else:
                jobs.append((sym, day))

    async def one(sym: str, day: str) -> None:
        async with gate:
            counts[await record_one(db, sym, day, method, dry)] += 1

    await asyncio.gather(*(one(s, d) for s, d in jobs))
    return counts


async def main(a: argparse.Namespace) -> int:
    from routes import fno as route
    from services import fno_iv_history as store
    from deps import db

    try:
        body = await route._daas("/desk/fno-buildup", {}, "stock futures")
    except Exception as e:  # noqa: BLE001
        log.error("the build-up scan could not be read (%s): nothing recorded", getattr(e, "detail", type(e).__name__))
        return 2
    latest = route._iso_day(body.get("as_of"))
    if not latest:
        log.error("the build-up scan has no session: nothing recorded")
        return 2
    symbols = [s.strip().upper() for s in a.symbols.split(",") if s.strip()] if a.symbols else scan_universe(body)
    if not symbols:
        log.error("no underlyings to record (the scan listed none and --symbols was not given)")
        return 2
    backfill = bool(a.backfill_days or a.start)
    if backfill:
        end = date.fromisoformat(a.end) if a.end else date.fromisoformat(latest)
        start = date.fromisoformat(a.start) if a.start else backfill_start(end, a.backfill_days)
        days = weekdays(start, end)
    else:
        days = [latest]
    method = "backfill" if backfill else "recorded"
    log.info("%s: %d underlyings x %d weekdays (%s to %s), latest session %s%s", method, len(symbols), len(days),
             days[0] if days else "-", days[-1] if days else "-", latest, " [dry run]" if a.dry_run else "")
    if not a.dry_run:
        await store.ensure_indexes(db)
    counts = await run(db, symbols, days, method, a.dry_run, skip_existing=backfill and not a.recompute)
    log.info("done: %s", dict(sorted(counts.items())))
    return 4 if counts.get("failed") else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Record the daily ATM implied volatility of F&O underlyings")
    ap.add_argument("--dry-run", action="store_true", help="work it out and log it; write nothing")
    ap.add_argument("--symbols", help="comma-separated underlyings (default: every underlying in the build-up scan)")
    ap.add_argument("--backfill-days", type=int, default=0, help="also the N weekdays ending at the latest session (method backfill)")
    ap.add_argument("--start", help="backfill from YYYY-MM-DD")
    ap.add_argument("--end", help="backfill to YYYY-MM-DD (default: the latest session)")
    ap.add_argument("--recompute", action="store_true", help="backfill: recompute sessions already stored")
    sys.exit(asyncio.run(main(ap.parse_args())))
