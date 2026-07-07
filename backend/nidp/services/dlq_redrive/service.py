"""dlq_redrive — close the write-only DLQ loop.

Problem it solves: Gate 1 quarantines a bad ingestion into
`dq.dlq_findings` with `replay_status='PENDING'`, but nothing ever
reprocesses it — no code flips a row to REPLAYED, so quarantined days
accumulate as permanent gaps until a human intervenes. See
HANDOFF-FEED-RELIABILITY.md §Theme C (DLQ is write-only).

What it does: reads PENDING entries oldest-first, re-runs the owning
feed for its (feed, target_date), and transitions the row:
  * REPLAYED       — a fresh OK/PARTIAL run landed after the re-run.
  * PENDING        — still failing, but under the attempt budget → try again next cycle.
  * INVESTIGATING  — hit NIDP_DLQ_MAX_ATTEMPTS, or the feed has no runnable
                     service → stop retrying, surface for a human.
  * DROPPED        — older than NIDP_DLQ_DROP_AGE_DAYS and still failing →
                     the source almost certainly no longer serves that date.
Emails an operator when any entry needs human attention.

Success is judged by an authoritative `job_log` lookup scoped to runs
that *started after* the re-run kicked off — not by whether the ingester
raised — because an ingester can finalize FAILED/SKIPPED without raising.

Wrapped in a `JobRun` so the redrive itself shows up in v_feed_status.

Config (env / nidp.env):
    NIDP_DLQ_REDRIVE_LIMIT   max entries per cycle (default 200)
    NIDP_DLQ_MAX_ATTEMPTS    attempts before INVESTIGATING (default 3)
    NIDP_DLQ_DROP_AGE_DAYS   age past which a still-failing entry is DROPPED (default 30)

Run:
    python -m nidp.services.dlq_redrive [--limit N]
"""
from __future__ import annotations

import importlib
import importlib.util
import logging
import os
import re
from datetime import date, datetime, timezone
from typing import Optional

from nidp import backfill as bf
from nidp.shared import notify as _notify
from nidp.shared.storage import job_log as _job_log
from nidp.shared.storage.pg import get_pool

logger = logging.getLogger(__name__)

INGESTER_NAME = "dlq_redrive"
DEFAULT_LIMIT = 200
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_DROP_AGE_DAYS = 30

_ATTEMPTS_RE = re.compile(r"attempts=(\d+)")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _attempts(notes: Optional[str]) -> int:
    m = _ATTEMPTS_RE.search(notes or "")
    return int(m.group(1)) if m else 0


def _note(attempt: int, now: datetime, msg: str) -> str:
    return f"redrive: attempts={attempt}; last={now.isoformat()}; {msg}"


def _feed_runnable(feed: str) -> bool:
    """True if we can import a `run()` entrypoint for this feed."""
    if feed in bf.SPEC_BY_NAME:
        return True
    try:
        return importlib.util.find_spec(f"nidp.services.{feed}.service") is not None
    except (ImportError, ValueError, ModuleNotFoundError):
        return False


async def _rerun_feed(feed: str, target_date: Optional[date]) -> None:
    """Import the feed's service module and run it for target_date."""
    if feed in bf.SPEC_BY_NAME:
        module_path = bf.SPEC_BY_NAME[feed].module_path
    else:
        module_path = f"nidp.services.{feed}.service"
    mod = importlib.import_module(module_path)
    run_fn = getattr(mod, "run")
    await run_fn(target_date)


async def _succeeded_since(conn, feed: str, target_date: Optional[date], since: datetime) -> bool:
    """Authoritative success check: an OK/PARTIAL job_log row that STARTED
    at/after `since` (i.e. produced by the re-run we just triggered)."""
    if target_date is not None:
        v = await conn.fetchval(
            """SELECT 1 FROM nidp.job_log
                WHERE ingester=$1 AND target_date=$2
                  AND status IN ('OK','PARTIAL') AND started_at >= $3 LIMIT 1""",
            feed, target_date, since,
        )
    else:
        v = await conn.fetchval(
            """SELECT 1 FROM nidp.job_log
                WHERE ingester=$1 AND target_date IS NULL
                  AND status IN ('OK','PARTIAL') AND started_at >= $2 LIMIT 1""",
            feed, since,
        )
    return v is not None


async def _mark(conn, dlq_id, status: str, notes: str) -> None:
    if status == "REPLAYED":
        await conn.execute(
            "UPDATE dq.dlq_findings SET replay_status=$2, replayed_at=NOW(), notes=$3 WHERE id=$1",
            dlq_id, status, notes,
        )
    else:
        await conn.execute(
            "UPDATE dq.dlq_findings SET replay_status=$2, notes=$3 WHERE id=$1",
            dlq_id, status, notes,
        )


async def redrive_one(
    conn, row: dict, *, max_attempts: int, drop_age_days: int, now: datetime,
) -> str:
    """Reprocess one DLQ row; returns the new replay_status."""
    feed = row["feed"]
    td = row.get("target_date")
    dlq_id = row["id"]
    attempt = _attempts(row.get("notes")) + 1

    if not _feed_runnable(feed):
        await _mark(conn, dlq_id, "INVESTIGATING",
                    _note(attempt, now, f"no runnable service for feed '{feed}'"))
        return "INVESTIGATING"

    since = now
    rerun_error: Optional[str] = None
    try:
        await _rerun_feed(feed, td)
    except Exception as e:                                          # noqa: BLE001
        rerun_error = f"{type(e).__name__}: {e}"[:200]
        logger.warning("dlq_redrive: re-run %s@%s raised: %s", feed, td, rerun_error)

    if await _succeeded_since(conn, feed, td, since):
        await _mark(conn, dlq_id, "REPLAYED", _note(attempt, now, "replayed"))
        return "REPLAYED"

    created_at = row.get("created_at")
    age_days = (now - created_at).days if created_at else 0
    if drop_age_days and age_days > drop_age_days:
        await _mark(conn, dlq_id, "DROPPED",
                    _note(attempt, now, f"aged out {age_days}d; {rerun_error or 'still failing'}"))
        return "DROPPED"

    if attempt >= max_attempts:
        await _mark(conn, dlq_id, "INVESTIGATING",
                    _note(attempt, now, f"max attempts ({max_attempts}); {rerun_error or 'still failing'}"))
        return "INVESTIGATING"

    await _mark(conn, dlq_id, "PENDING", _note(attempt, now, rerun_error or "still failing"))
    return "PENDING"


async def redrive(limit: Optional[int] = None) -> dict:
    """Process PENDING dq.dlq_findings entries. Returns a counts report."""
    limit = limit or _env_int("NIDP_DLQ_REDRIVE_LIMIT", DEFAULT_LIMIT)
    max_attempts = _env_int("NIDP_DLQ_MAX_ATTEMPTS", DEFAULT_MAX_ATTEMPTS)
    drop_age_days = _env_int("NIDP_DLQ_DROP_AGE_DAYS", DEFAULT_DROP_AGE_DAYS)

    async with _job_log.JobRun(ingester=INGESTER_NAME) as run:
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT id, feed, target_date, severity, notes, created_at
                     FROM dq.dlq_findings
                    WHERE replay_status='PENDING'
                    ORDER BY created_at ASC
                    LIMIT $1""",
                limit,
            )

        counts = {"REPLAYED": 0, "PENDING": 0, "INVESTIGATING": 0, "DROPPED": 0}
        now = datetime.now(timezone.utc)
        for row in rows:
            async with pool.acquire() as conn:
                outcome = await redrive_one(
                    conn, dict(row),
                    max_attempts=max_attempts, drop_age_days=drop_age_days, now=now,
                )
            counts[outcome] = counts.get(outcome, 0) + 1

        run.rows_fetched = len(rows)
        run.rows_inserted = counts["REPLAYED"]
        run.metadata.update(counts)
        needs_human = counts["INVESTIGATING"] + counts["DROPPED"]

        logger.info(
            "dlq_redrive: processed %d PENDING — replayed=%d still_pending=%d "
            "investigating=%d dropped=%d",
            len(rows), counts["REPLAYED"], counts["PENDING"],
            counts["INVESTIGATING"], counts["DROPPED"],
        )

        if needs_human:
            body = (
                f"DLQ redrive processed {len(rows)} PENDING entr(y/ies):\n"
                f"  replayed:      {counts['REPLAYED']}\n"
                f"  still pending: {counts['PENDING']}\n"
                f"  INVESTIGATING: {counts['INVESTIGATING']}\n"
                f"  DROPPED:       {counts['DROPPED']}\n\n"
                f"INVESTIGATING/DROPPED entries need a human — see dq.dlq_findings.notes."
            )
            _notify.notify(
                f"⚠ NIDP dlq_redrive: {needs_human} DLQ entr(y/ies) need attention", body,
            )

        await run.finalize(
            "OK" if not needs_human else "PARTIAL",
            error_message=(f"{needs_human} DLQ entr(y/ies) need attention"
                           if needs_human else None),
            error_class="DLQ" if needs_human else None,
        )
        return {"processed": len(rows), **counts}


# BaseIngester-style entrypoint alias (ignores target_date — it derives its
# own work from the DLQ table).
async def run(target_date: Optional[date] = None) -> dict:  # noqa: ARG001
    return await redrive()
