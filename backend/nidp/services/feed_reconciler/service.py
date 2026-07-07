"""feed_reconciler — self-healing catch-up for missed feed runs.

Problem it solves: when a feed run fails (transient NSE error, or the VM
disk-full → Postgres crash-loop that fails *every* feed for hours), the
one-shot cron model leaves a permanent hole — a missing `(feed,
target_date)` in `nidp.job_log`/the fact tables — because nothing re-runs
the missed day. See HANDOFF-FEED-RELIABILITY.md §Theme C.

What it does: every morning (after the evening ingest window and after
the DB has recovered from any overnight incident), it enumerates the
trading days in a rolling look-back window, finds which recoverable daily
feeds have NO successful `job_log` row for a given day, and heals the gaps
by calling the existing `nidp.backfill.run_backfill(..., skip_existing=True)`
— which is holiday-aware, idempotent, and resumable, so re-running is
safe and only the missing days actually execute. If any gap can't be
healed (source still down / genuinely missing), it emails an operator.

It reuses `nidp.backfill` deliberately: no new "list of feeds" to drift
out of sync (feed-list fragmentation is itself a documented root cause).
Only feeds present in `backfill.SPEC_BY_NAME` (the vetted idempotent set)
are reconciled; anything else is reported as un-runnable rather than
silently skipped.

Wrapped in a `JobRun` so the reconciler itself shows up in
`nidp.v_feed_status` and the feed-health dashboards.

Config (env / nidp.env):
    NIDP_RECONCILE_FEEDS          comma list (default bhavcopy,delivery,index_close,fii_dii)
    NIDP_RECONCILE_LOOKBACK_DAYS  default 7

Run:
    python -m nidp.services.feed_reconciler [--lookback N] [--feeds a,b,c] [--dry-run]
"""
from __future__ import annotations

import logging
import os
from datetime import date, timedelta
from typing import Optional

from nidp import backfill as bf
from nidp.shared import notify as _notify
from nidp.shared.storage import job_log as _job_log
from nidp.shared.trading_day import last_market_close_date

logger = logging.getLogger(__name__)

INGESTER_NAME = "feed_reconciler"
DEFAULT_FEEDS = ["bhavcopy", "delivery", "index_close", "fii_dii"]
DEFAULT_LOOKBACK_DAYS = 7


def _configured_feeds() -> list[str]:
    raw = os.environ.get("NIDP_RECONCILE_FEEDS", "")
    if raw.strip():
        return [f.strip() for f in raw.split(",") if f.strip()]
    return list(DEFAULT_FEEDS)


def _configured_lookback() -> int:
    try:
        return int(os.environ.get("NIDP_RECONCILE_LOOKBACK_DAYS", str(DEFAULT_LOOKBACK_DAYS)))
    except ValueError:
        return DEFAULT_LOOKBACK_DAYS


async def find_gaps(feeds: list[str], days: list[date]) -> list[tuple[str, date]]:
    """Return every (feed, day) that has NO OK/PARTIAL run in job_log.

    Uses the same `already_succeeded` predicate the backfill uses for
    resumability, so gap-detection and gap-healing agree by construction.
    """
    gaps: list[tuple[str, date]] = []
    for feed in feeds:
        for d in days:
            if not await bf.already_succeeded(feed, d):
                gaps.append((feed, d))
    return gaps


def _format_gaps(gaps: list[tuple[str, date]]) -> str:
    return ", ".join(f"{feed}@{d.isoformat()}" for feed, d in gaps) or "(none)"


async def reconcile(
    feeds: Optional[list[str]] = None,
    lookback_days: Optional[int] = None,
    *,
    dry_run: bool = False,
) -> dict:
    """Detect and heal feed gaps in the rolling window. Returns a report dict."""
    feeds = feeds or _configured_feeds()
    lookback_days = lookback_days if lookback_days is not None else _configured_lookback()

    # Only feeds the backfill can actually run are "recoverable". Surface
    # the rest loudly instead of pretending we healed them.
    recoverable = [f for f in feeds if f in bf.SPEC_BY_NAME]
    unrunnable = [f for f in feeds if f not in bf.SPEC_BY_NAME]
    if unrunnable:
        logger.warning(
            "feed_reconciler: %s not in backfill registry — cannot auto-heal; "
            "add a ServiceSpec in nidp/backfill.py to make them recoverable",
            unrunnable,
        )

    async with _job_log.JobRun(ingester=INGESTER_NAME) as run:
        end = await last_market_close_date()
        start = end - timedelta(days=lookback_days)
        days = await bf.trading_days(start, end)

        gaps_before = await find_gaps(recoverable, days)
        run.metadata.update({
            "window_start": start.isoformat(),
            "window_end": end.isoformat(),
            "trading_days": len(days),
            "feeds": recoverable,
            "unrunnable_feeds": unrunnable,
            "gaps_found": [f"{f}@{d.isoformat()}" for f, d in gaps_before],
            "dry_run": dry_run,
        })
        run.rows_fetched = len(gaps_before)

        if not gaps_before:
            logger.info(
                "feed_reconciler: no gaps — %d feed(s) complete across %d trading day(s) "
                "(%s..%s)", len(recoverable), len(days), start, end,
            )
            await run.finalize("OK")
            return {"gaps_before": [], "healed": [], "remaining": [], "status": "OK"}

        logger.warning(
            "feed_reconciler: %d gap(s) in %s..%s: %s",
            len(gaps_before), start, end, _format_gaps(gaps_before),
        )

        if dry_run:
            await run.finalize("OK", error_message="dry-run: gaps detected, not healed")
            return {"gaps_before": gaps_before, "healed": [], "remaining": gaps_before,
                    "status": "DRY_RUN"}

        # Heal — run_backfill(skip_existing=True) executes ONLY the missing
        # days for these feeds; already-succeeded days are skipped.
        await bf.run_backfill(
            start=start, end=end, services=recoverable,
            skip_existing=True, rolling_first=False,
        )

        gaps_after = await find_gaps(recoverable, days)
        healed = [g for g in gaps_before if g not in gaps_after]
        run.rows_inserted = len(healed)
        run.rows_skipped = len(gaps_after)
        run.metadata["healed"] = [f"{f}@{d.isoformat()}" for f, d in healed]
        run.metadata["remaining"] = [f"{f}@{d.isoformat()}" for f, d in gaps_after]

        logger.info(
            "feed_reconciler: healed %d/%d gap(s); %d remaining",
            len(healed), len(gaps_before), len(gaps_after),
        )

        body = (
            f"Window: {start} .. {end} ({len(days)} trading days)\n"
            f"Feeds: {', '.join(recoverable)}\n"
            f"Gaps found: {_format_gaps(gaps_before)}\n"
            f"Healed: {_format_gaps(healed)}\n"
            f"STILL MISSING: {_format_gaps(gaps_after)}\n"
        )
        if unrunnable:
            body += f"Un-runnable feeds (config): {', '.join(unrunnable)}\n"

        if gaps_after:
            # Actionable: source still down / genuinely missing → page a human.
            _notify.notify(
                f"⚠ NIDP feed_reconciler: {len(gaps_after)} gap(s) could NOT be healed",
                body,
            )
            await run.finalize(
                "PARTIAL" if healed else "FAILED",
                error_message=f"{len(gaps_after)} gap(s) unhealed: {_format_gaps(gaps_after)}",
                error_class="RECONCILE",
            )
        else:
            # Informational: a gap occurred but self-healed. Worth knowing.
            _notify.notify(
                f"✓ NIDP feed_reconciler: healed {len(healed)} gap(s)", body,
            )
            await run.finalize("OK")

        return {"gaps_before": gaps_before, "healed": healed,
                "remaining": gaps_after, "status": "OK" if not gaps_after else "PARTIAL"}


# BaseIngester-style entrypoint alias so this is triggerable via the same
# `run(target_date)` convention the backfill/admin trigger use. The
# reconciler ignores target_date (it derives its own window).
async def run(target_date: Optional[date] = None) -> dict:  # noqa: ARG001
    return await reconcile()
