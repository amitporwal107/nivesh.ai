"""Finalize job_log rows left in RUNNING by a process that died.

An ingester writes a RUNNING row on start and finalizes it on exit. If
the process is killed mid-run — OOM, a full disk, a reboot, a SIGKILL —
nothing ever finalizes it and the row stays RUNNING forever. Staging had
24 such rows, the oldest 2,026 hours (85 days) old, with no live process
behind any of them.

Why it matters: `nidp.v_feed_status` reports each ingester's *latest*
run. A stranded RUNNING row that happens to be the latest makes a dead
feed look busy rather than broken, so it never trips a staleness alarm —
the failure mode hides itself.

This reaper closes them out as FAILED with an explicit reason. It is
deliberately conservative:
  * only rows older than `max_age_hours` (a long-running ingester must
    never be shot in the back),
  * `finished_at` is set from `started_at + max_age_hours` rather than
    now(), so a run abandoned in May does not appear to have finished
    today,
  * the message says what actually happened, so nobody re-debugs it as
    an ingester bug.
"""
from __future__ import annotations

import logging
from typing import Any

from nidp.shared.storage.pg import get_pool

logger = logging.getLogger(__name__)

DEFAULT_MAX_AGE_HOURS = 6

_REAP_SQL = """
UPDATE nidp.job_log
   SET status = 'FAILED',
       finished_at = started_at + ($1 || ' hours')::interval,
       error_message = COALESCE(error_message, '') ||
           'abandoned: still RUNNING ' || $1 || 'h after start with no ' ||
           'completion recorded — the process died without finalizing ' ||
           '(OOM / disk full / reboot / kill). Reaped by reap_stale_runs.'
 WHERE status = 'RUNNING'
   AND started_at < now() - ($1 || ' hours')::interval
RETURNING ingester, started_at
"""


async def reap(max_age_hours: int = DEFAULT_MAX_AGE_HOURS) -> list[dict[str, Any]]:
    """Close out abandoned RUNNING rows. Returns what was reaped."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            rows = await conn.fetch(_REAP_SQL, str(max_age_hours))
    if rows:
        by_ingester: dict[str, int] = {}
        for r in rows:
            by_ingester[r["ingester"]] = by_ingester.get(r["ingester"], 0) + 1
        logger.warning(
            "reaped %d abandoned RUNNING job_log row(s) older than %dh: %s",
            len(rows), max_age_hours,
            ", ".join(f"{k}x{v}" for k, v in sorted(by_ingester.items())),
        )
    else:
        logger.info("no abandoned RUNNING rows older than %dh", max_age_hours)
    return [dict(r) for r in rows]
