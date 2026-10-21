"""Month-range backfill + catch-up for mf_holdings.

Why this is not nidp.backfill: that orchestrator enumerates TRADING DAYS and resumes off a
month-level job_log row whose status is PARTIAL whenever any AMC is missing. For a monthly feed
assembled from 14 independent AMC sites, "PARTIAL" is the steady state, so a day-based,
month-resumed backfill would either skip everything or redo everything. Resumability here is
per-(amc, month), off nidp.mf_holdings_coverage.

Usage:
    python -m nidp.services.mf_holdings.backfill --from 2025-09-01 --to 2026-09-01
    python -m nidp.services.mf_holdings.backfill --from 2025-09-01 --to 2026-09-01 \
        --amcs icici_pru,kotak,absl --only-missing
    python -m nidp.services.mf_holdings.backfill --from 2026-09-01 --to 2026-09-01 --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import uuid
from datetime import date
from typing import Optional, Sequence

import aiohttp

from nidp.shared.config import (
    DEFAULT_UA, HTTP_TIMEOUT_S, MF_AMC_TOP10, MF_AMC_TIER2, MF_AMC_TIER3,
)
from nidp.shared.logging_setup import bind_context, setup_logging
from nidp.shared.storage.job_log import JobRun
from nidp.shared.storage.pg import close_pool

from . import coverage
from .ingest import ingest_amc

logger = logging.getLogger(__name__)

ALL_AMCS: tuple[str, ...] = (*MF_AMC_TOP10, *MF_AMC_TIER2, *MF_AMC_TIER3)

# A disclosure file is 20-30 MB and several AMCs sit behind the same CDN. One AMC at a time with
# a gap between them: this is a monthly feed with no latency requirement, and politeness here is
# what keeps the sources usable.
POLITE_GAP_S = 2.0

# aiohttp's `total` timeout covers the body read, and these files are large. The daily service's
# 30s global budget is ample for a 25MB file on a healthy link (measured 1.2s) but leaves no room
# for a slow origin, so the backfill gives itself a wider one.
BACKFILL_TIMEOUT_S = max(HTTP_TIMEOUT_S, 300)


def months_between(start: date, end: date) -> list[date]:
    """Inclusive first-of-month list. Inputs are snapped to the 1st."""
    cur = date(start.year, start.month, 1)
    last = date(end.year, end.month, 1)
    out: list[date] = []
    while cur <= last:
        out.append(cur)
        cur = date(cur.year + 1, 1, 1) if cur.month == 12 else date(cur.year, cur.month + 1, 1)
    return out


async def run_backfill(
    start: date,
    end: date,
    *,
    amcs: Optional[Sequence[str]] = None,
    only_missing: bool = True,
    dry_run: bool = False,
) -> dict:
    """Walk (month × amc), ingesting each pair that is not already covered.

    Newest month first: if the run is cut short, the most useful months are already in.
    """
    months = months_between(start, end)
    amc_list = list(amcs) if amcs else list(ALL_AMCS)
    unknown = [a for a in amc_list if a not in ALL_AMCS]
    if unknown:
        raise SystemExit(f"unknown amc_id(s): {', '.join(unknown)}\nknown: {', '.join(ALL_AMCS)}")

    # Ledger rows may not exist for holdings written before migration 159; seed them so
    # --only-missing does not re-fetch what we already hold.
    if not dry_run:
        await coverage.backfill_from_holdings()

    done = await coverage.done_pairs(amc_list, months) if only_missing else set()
    todo = [(m, a) for m in reversed(months) for a in amc_list if (a, m) not in done]

    logger.info("mf_holdings backfill: %d month(s) × %d amc(s) = %d pair(s); "
                "%d already OK → %d to attempt%s",
                len(months), len(amc_list), len(months) * len(amc_list),
                len(done), len(todo), " [DRY RUN]" if dry_run else "")

    summary = {
        "months": [m.isoformat() for m in months],
        "amcs": amc_list,
        "skipped_already_ok": len(done),
        "attempted": 0, "ok": 0, "empty": 0, "error": 0,
        "rows_written": 0,
        "pairs": [],
    }

    if dry_run:
        summary["would_attempt"] = [f"{a} {m.isoformat()}" for m, a in todo]
        for line in summary["would_attempt"]:
            logger.info("  would attempt: %s", line)
        return summary

    if not todo:
        logger.info("mf_holdings backfill: nothing to do — every pair already covered")
        return summary

    timeout = aiohttp.ClientTimeout(total=BACKFILL_TIMEOUT_S)
    headers = {"User-Agent": DEFAULT_UA}

    async with JobRun(ingester="mf_holdings_backfill", target_date=months[-1]) as run:
        bind_context(service="mf_holdings_backfill", run_id=str(run.run_id))
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            for i, (month, amc) in enumerate(todo, 1):
                logger.info("[%d/%d] %s %s", i, len(todo), amc, month.isoformat())
                res = await ingest_amc(session, amc, month, run.run_id)
                summary["attempted"] += 1
                summary[res.status.lower()] += 1
                summary["rows_written"] += res.rows_written
                summary["pairs"].append(
                    {"amc_id": amc, "as_of_month": month.isoformat(), "status": res.status,
                     "rows": res.rows_written, "schemes": res.schemes_written,
                     "error": res.error}
                )
                if i < len(todo):
                    await asyncio.sleep(POLITE_GAP_S)

        run.rows_inserted = summary["rows_written"]
        run.rows_fetched = summary["rows_written"]
        run.metadata.update({k: summary[k] for k in
                             ("attempted", "ok", "empty", "error", "skipped_already_ok")})
        # A backfill that wrote nothing is a failure even though no exception escaped —
        # the same honesty rule the daily service learned (see service.py).
        final = "OK" if summary["ok"] and not summary["error"] else (
            "FAILED" if summary["ok"] == 0 else "PARTIAL")
        await run.finalize(final, error_message=(
            f"ok={summary['ok']} empty={summary['empty']} error={summary['error']} "
            f"rows={summary['rows_written']}" if final != "OK" else None))

    logger.info("mf_holdings backfill done: attempted=%d ok=%d empty=%d error=%d rows=%d",
                summary["attempted"], summary["ok"], summary["empty"],
                summary["error"], summary["rows_written"])
    return summary


def _parse_month(s: str) -> date:
    return date.fromisoformat(s if len(s) > 7 else f"{s}-01")


def latest_disclosure_month(today: Optional[date] = None) -> date:
    """The most recent month whose portfolio should exist by now.

    SEBI requires disclosure within 10 days of month end, so before the 11th the previous
    month is not due yet and the one before it is the latest we can expect.
    """
    d = today or date.today()
    prev = date(d.year - 1, 12, 1) if d.month == 1 else date(d.year, d.month - 1, 1)
    if d.day >= 11:
        return prev
    return date(prev.year - 1, 12, 1) if prev.month == 1 else date(prev.year, prev.month - 1, 1)


def trailing_range(n: int, today: Optional[date] = None) -> tuple[date, date]:
    """The n most recent due disclosure months, oldest..newest."""
    if n < 1:
        raise SystemExit("--trailing must be >= 1")
    end = latest_disclosure_month(today)
    start = end
    for _ in range(n - 1):
        start = date(start.year - 1, 12, 1) if start.month == 1 else \
            date(start.year, start.month - 1, 1)
    return start, end


def main() -> None:
    ap = argparse.ArgumentParser(description="Backfill nidp.mf_holdings_monthly over a month range")
    ap.add_argument("--from", dest="start", help="YYYY-MM or YYYY-MM-01")
    ap.add_argument("--to", dest="end", help="YYYY-MM or YYYY-MM-01")
    ap.add_argument("--trailing", type=int, metavar="N",
                    help="instead of --from/--to, the N most recent due disclosure months. "
                         "Intended for cron: with the default --only-missing this is a cheap "
                         "no-op once every pair is OK, and heals months a third-party index "
                         "had not yet listed on the scheduled run day.")
    ap.add_argument("--amcs", help="comma-separated adapter keys (default: all)")
    ap.add_argument("--all", dest="only_missing", action="store_false", default=True,
                    help="re-fetch pairs already marked OK (default: skip them)")
    ap.add_argument("--dry-run", action="store_true",
                    help="list the (amc, month) pairs that would be fetched; write nothing")
    args = ap.parse_args()

    setup_logging("mf_holdings_backfill")
    amcs = [a.strip() for a in args.amcs.split(",")] if args.amcs else None

    if args.trailing is not None:
        start, end = trailing_range(args.trailing)
    elif args.start and args.end:
        start, end = _parse_month(args.start), _parse_month(args.end)
    else:
        raise SystemExit("give either --trailing N, or both --from and --to")

    async def _go() -> None:
        try:
            await run_backfill(start, end, amcs=amcs,
                               only_missing=args.only_missing, dry_run=args.dry_run)
        finally:
            await close_pool()

    asyncio.run(_go())


if __name__ == "__main__":
    main()
