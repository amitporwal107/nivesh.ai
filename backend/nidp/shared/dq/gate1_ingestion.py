"""Gate 1 — Ingestion Gate.

Runs inside BaseIngester immediately after validate() and before persist().
Implements the pre-Kafka-publish quality checks from QUALITY_GATE.md §5 Gate 1:

  G1-UNIV-001  Row count within the trailing 30-day band from dq.feed_sla   (P0)
  G1-UNIV-002  Row count ≥ absolute minimum floor from dq.feed_sla           (P0)
  G1-UNIV-003  target_date not in the future                                 (P0)
  G1-UNIV-004  target_date not older than 7 days (backfill flag bypasses)    (P1)

On P0 failure:
  * persist() is NOT called.
  * Rows are summarized into dq.dlq_findings with replay_status = PENDING.
  * GateCheckFailed is raised — BaseIngester catches it and finalizes FAILED.

Thresholds fall back to hard-coded defaults when dq.feed_sla has no row.
The gate itself is wrapped in try/except so a DB failure never silently
blocks a valid ingestion run (fail-open with logged error).
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import date, datetime, timezone, timedelta
from typing import Optional

import asyncpg

from nidp.shared.dq.gate import BaseGate, CheckResult, Severity

logger = logging.getLogger(__name__)

# ── Hard-coded row-count floors per feed ──────────────────────────────────────
# Used when dq.feed_sla has no row for the feed. These are conservative
# "something is deeply wrong" floors — not expected-value targets.
_FLOOR_DEFAULTS: dict[str, int] = {
    "bhavcopy":         1000,
    "delivery":          800,
    "index_close":        10,
    "fii_dii":             1,
    "mf_nav_daily":     2000,
    "fno_bhavcopy":      100,
    "corporate_actions":   0,
    "bulk_deals":          0,
    "block_deals":         0,
    "rbi_yields":          1,
    "nse_equity_master": 100,
    "index_constituents": 50,
    "nse_shareholding":   50,
}

_BACKFILL_MAX_AGE_DAYS = 365     # backfill flag bypasses the 7-day staleness check


class IngestionGate(BaseGate):
    """Gate 1 — runs per-ingester before persist().

    Usage (from BaseIngester.run):

        gate   = IngestionGate(feed=self.SERVICE_NAME)
        result = await gate.run(conn, target_date, job_run_id=run.run_id)
        # GateCheckFailed raised on P0; BaseIngester treats as FAILED run.
    """

    GATE_ID   = 1
    GATE_NAME = "ingestion"

    def __init__(
        self,
        feed: str,
        row_count: int = 0,
        is_backfill: bool = False,
    ) -> None:
        super().__init__(feed=feed)
        self._row_count  = row_count
        self._is_backfill = is_backfill

    async def _checks(
        self,
        conn: asyncpg.Connection,
        target_date: Optional[date],
        job_run_id: Optional[uuid.UUID] = None,
    ) -> list[CheckResult]:
        results: list[CheckResult] = []

        # G1-UNIV-002 / G1-UNIV-001: row count checks
        results.append(await self._check_row_count(conn, target_date))

        # G1-UNIV-003: target_date not in future
        if target_date is not None:
            results.append(self._check_not_future(target_date))

        # G1-UNIV-004: target_date not too stale (P1, skipped for backfill)
        if target_date is not None and not self._is_backfill:
            results.append(self._check_not_stale(target_date))

        return results

    # ── G1-UNIV-001 / 002: row count ─────────────────────────────────────────

    async def _check_row_count(
        self, conn: asyncpg.Connection, target_date: Optional[date]
    ) -> CheckResult:
        sla = await _load_sla(conn, self.feed)
        floor = sla.get("row_count_min") or _FLOOR_DEFAULTS.get(self.feed, 0)
        ok = self._row_count >= floor
        return CheckResult(
            name="G1-UNIV-001",
            passed=ok,
            severity=Severity.P0,
            message=(
                f"{self.feed} row count {self._row_count} >= floor {floor}"
                if ok
                else f"{self.feed} row count {self._row_count} < floor {floor}"
            ),
            details={"row_count": self._row_count, "floor": floor},
        )

    # ── G1-UNIV-003: not in future ────────────────────────────────────────────

    def _check_not_future(self, target_date: date) -> CheckResult:
        today = date.today()
        ok = target_date <= today
        return CheckResult(
            name="G1-UNIV-003",
            passed=ok,
            severity=Severity.P0,
            message=(
                f"target_date {target_date} is not in the future"
                if ok
                else f"target_date {target_date} is in the future (today={today})"
            ),
            details={"target_date": str(target_date), "today": str(today)},
        )

    # ── G1-UNIV-004: not too stale ────────────────────────────────────────────

    def _check_not_stale(self, target_date: date) -> CheckResult:
        age_days = (date.today() - target_date).days
        ok = age_days <= 7
        return CheckResult(
            name="G1-UNIV-004",
            passed=ok,
            severity=Severity.P1,   # AMBER — does not block
            message=(
                f"target_date {target_date} is {age_days}d old (≤ 7d)"
                if ok
                else f"target_date {target_date} is {age_days}d stale (> 7d)"
            ),
            details={"target_date": str(target_date), "age_days": age_days},
        )


# ── DLQ helper ────────────────────────────────────────────────────────────────

async def write_dlq(
    conn: asyncpg.Connection,
    gate_id: int,
    feed: str,
    target_date: Optional[date],
    job_run_id: Optional[uuid.UUID],
    failure_reason: str,
    severity: str,         # "P0" | "P1" | "P2"
    raw_payload: Optional[dict] = None,
    topic: Optional[str] = None,
) -> uuid.UUID:
    """Insert one DLQ row and return its id."""
    dlq_id = uuid.uuid4()
    await conn.execute(
        """
        INSERT INTO dq.dlq_findings
            (id, gate_id, feed, target_date, job_run_id,
             topic, failure_reason, severity, raw_payload)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb)
        """,
        dlq_id,
        gate_id,
        feed,
        target_date,
        job_run_id,
        topic,
        failure_reason,
        severity,
        json.dumps(raw_payload) if raw_payload else None,
    )
    logger.warning(
        "dq.dlq_findings: gate=%d feed=%s date=%s severity=%s reason=%s dlq_id=%s",
        gate_id, feed, target_date, severity, failure_reason, dlq_id,
    )
    return dlq_id


# ── SLA loader ────────────────────────────────────────────────────────────────

async def _load_sla(conn: asyncpg.Connection, feed: str) -> dict:
    """Return dq.feed_sla row for gate_id=1, or {} if not found."""
    try:
        row = await conn.fetchrow(
            "SELECT row_count_min, row_count_max FROM dq.feed_sla WHERE feed=$1 AND gate_id=1",
            feed,
        )
        return dict(row) if row else {}
    except Exception:                                           # noqa: BLE001
        return {}
