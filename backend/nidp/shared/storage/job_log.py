"""Per-run job log writer.

Every ingester invocation creates exactly one job_log row. The row
moves through states:
    RUNNING  → at start
    OK       → all rows persisted, no errors
    PARTIAL  → some rows persisted, some failed validation
    FAILED   → unrecoverable error before any persist
    SKIPPED  → ingester decided no work (e.g. holiday, already-fresh)

The run_id is propagated into every fact row's `source_run_id`, so
revoking a bad run is a single DELETE … WHERE source_run_id = $1.
"""
from __future__ import annotations

import logging
import time
import uuid
from datetime import date, datetime, timezone
from typing import Optional

from nidp.shared.storage.pg import get_pool

logger = logging.getLogger(__name__)


class JobRun:
    """Context-manager that owns one job_log row from RUNNING → terminal."""

    def __init__(
        self,
        ingester: str,
        target_date: Optional[date] = None,
        source_url: Optional[str] = None,
    ) -> None:
        self.run_id: uuid.UUID = uuid.uuid4()
        self.ingester = ingester
        self.target_date = target_date
        self.source_url = source_url
        self._t0: float = 0.0
        self._terminated = False
        self.rows_fetched: int = 0
        self.rows_inserted: int = 0
        self.rows_skipped: int = 0
        self.metadata: dict = {}
        self.artifact_path: Optional[str] = None

    async def __aenter__(self) -> "JobRun":
        self._t0 = time.monotonic()
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO nidp.job_log
                    (run_id, ingester, target_date, source_url, status, started_at)
                VALUES ($1, $2, $3, $4, 'RUNNING', NOW())
                """,
                self.run_id, self.ingester, self.target_date, self.source_url,
            )
        return self

    async def finalize(
        self,
        status: str,
        *,
        error_message: Optional[str] = None,
        error_class: Optional[str] = None,
    ) -> None:
        if self._terminated:
            return
        self._terminated = True
        duration_ms = int((time.monotonic() - self._t0) * 1000)
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE nidp.job_log
                   SET status = $2,
                       finished_at = NOW(),
                       duration_ms = $3,
                       rows_fetched = $4,
                       rows_inserted = $5,
                       rows_skipped = $6,
                       error_message = $7,
                       error_class = $8,
                       artifact_path = $9,
                       metadata = $10::jsonb
                 WHERE run_id = $1
                """,
                self.run_id, status, duration_ms,
                self.rows_fetched, self.rows_inserted, self.rows_skipped,
                error_message, error_class, self.artifact_path,
                _json_dumps(self.metadata),
            )
            # Roll the per-feed dashboard fields on source_registry.
            # Matches by ingester (one ingester may map to >1 source rows;
            # we update them all so the registry stays consistent).
            await conn.execute(
                """
                UPDATE nidp.source_registry
                   SET last_run_at          = NOW(),
                       last_run_id          = $2,
                       last_run_status      = $3,
                       last_run_duration_ms = $4,
                       success_count        = success_count
                                              + CASE WHEN $3 = 'OK' THEN 1 ELSE 0 END,
                       partial_count        = partial_count
                                              + CASE WHEN $3 = 'PARTIAL' THEN 1 ELSE 0 END,
                       failure_count        = failure_count
                                              + CASE WHEN $3 = 'FAILED' THEN 1 ELSE 0 END,
                       last_success_at      = CASE WHEN $3 IN ('OK','PARTIAL')
                                                   THEN NOW() ELSE last_success_at END,
                       last_failure_at      = CASE WHEN $3 = 'FAILED'
                                                   THEN NOW() ELSE last_failure_at END,
                       consecutive_failures = CASE WHEN $3 = 'FAILED'
                                                   THEN consecutive_failures + 1
                                                   ELSE 0 END,
                       next_run_at          = CASE expected_freq
                           WHEN 'daily'     THEN NOW() + INTERVAL '1 day'
                           WHEN 'monthly'   THEN NOW() + INTERVAL '1 month'
                           WHEN 'quarterly' THEN NOW() + INTERVAL '3 months'
                           ELSE next_run_at
                       END,
                       updated_at           = NOW()
                 WHERE ingester = $1
                """,
                self.ingester, self.run_id, status, duration_ms,
            )
        logger.info(
            "job_log[%s] %s status=%s fetched=%d inserted=%d skipped=%d duration=%dms",
            self.ingester, self.run_id, status,
            self.rows_fetched, self.rows_inserted, self.rows_skipped, duration_ms,
        )

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if exc is not None and not self._terminated:
            await self.finalize(
                "FAILED",
                error_message=f"{type(exc).__name__}: {exc}"[:2000],
                error_class=type(exc).__name__,
            )
        # Don't suppress — let the exception propagate to the caller.


def _json_dumps(obj: dict) -> str:
    import json
    def default(o):
        if isinstance(o, (date, datetime)):
            return o.isoformat()
        return str(o)
    return json.dumps(obj, default=default)
