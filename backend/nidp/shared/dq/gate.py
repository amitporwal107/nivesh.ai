"""Base gate framework — anatomy from PRD §4.2.

Every gate:
  1. VERIFY  — run gate-specific invariants (subclass implements _checks())
  2. RECORD  — persist verdict to dq.gate_verdicts
  3. BLOCK   — raise GateCheckFailed on P0 failures
  4. EMIT    — Prometheus counter + structured Loki log
"""
from __future__ import annotations

import abc
import logging
import uuid
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Any, Optional

import asyncpg

from nidp.shared.metrics import GATE_VERDICTS   # see metrics.py

logger = logging.getLogger(__name__)


# ── Enums ─────────────────────────────────────────────────────────────────────

class Severity(str, Enum):
    OK = "OK"
    P2 = "P2"   # cosmetic / informational — pass, log only
    P1 = "P1"   # degrades a domain — pass with AMBER, alert
    P0 = "P0"   # blocks downstream — stop propagation, raise


class Verdict(str, Enum):
    PASS  = "PASS"
    AMBER = "AMBER"
    FAIL  = "FAIL"


# ── Result ────────────────────────────────────────────────────────────────────

@dataclass
class CheckResult:
    """Outcome of a single invariant check inside a gate."""
    name:        str
    passed:      bool
    severity:    Severity
    message:     str
    details:     dict[str, Any] = field(default_factory=dict)


@dataclass
class GateResult:
    gate_id:        int
    feed:           Optional[str]
    target_date:    date
    verdict:        Verdict
    severity:       Severity        # worst severity among failed checks
    checks:         list[CheckResult] = field(default_factory=list)
    verdict_id:     Optional[uuid.UUID] = None

    @property
    def blocked(self) -> bool:
        return self.verdict == Verdict.FAIL

    @property
    def failed_checks(self) -> list[CheckResult]:
        return [c for c in self.checks if not c.passed]


# ── Exception ─────────────────────────────────────────────────────────────────

class GateCheckFailed(Exception):
    """Raised when a gate has ≥1 P0 failure.

    Caller (pipeline orchestrator) catches this to halt downstream work.
    """
    def __init__(self, result: GateResult) -> None:
        self.result = result
        reasons = "; ".join(c.message for c in result.failed_checks if c.severity == Severity.P0)
        super().__init__(f"Gate {result.gate_id} P0 failure on {result.target_date}: {reasons}")


# ── Base Gate ─────────────────────────────────────────────────────────────────

class BaseGate(abc.ABC):
    """Abstract base for all 7 gates.

    Subclasses implement `_checks()` which yields CheckResult objects.
    The base class handles recording, blocking, and emitting.
    """

    GATE_ID: int        # override in subclass (1–7)
    GATE_NAME: str      # human label, e.g. "ingestion", "snapshot_completion"

    def __init__(self, feed: Optional[str] = None) -> None:
        self.feed = feed

    @abc.abstractmethod
    async def _checks(
        self,
        conn: asyncpg.Connection,
        target_date: date,
        job_run_id: Optional[uuid.UUID] = None,
    ) -> list[CheckResult]:
        """Run gate-specific invariants and return one CheckResult per check."""
        ...

    async def run(
        self,
        conn: asyncpg.Connection,
        target_date: date,
        job_run_id: Optional[uuid.UUID] = None,
    ) -> GateResult:
        """Execute the full 4-step gate anatomy."""
        # ── 1. VERIFY ────────────────────────────────────────────────────────
        checks = await self._checks(conn, target_date, job_run_id)

        # ── 2. Derive verdict from worst severity ─────────────────────────
        failed = [c for c in checks if not c.passed]
        worst  = max((c.severity for c in failed), default=Severity.OK)

        if worst == Severity.P0:
            verdict = Verdict.FAIL
        elif worst == Severity.P1:
            verdict = Verdict.AMBER
        else:
            verdict = Verdict.PASS

        result = GateResult(
            gate_id=self.GATE_ID,
            feed=self.feed,
            target_date=target_date,
            verdict=verdict,
            severity=worst,
            checks=checks,
        )

        # ── 3. RECORD verdict ────────────────────────────────────────────────
        result.verdict_id = await _persist_verdict(conn, result, job_run_id)

        # ── 4. EMIT metric + log ─────────────────────────────────────────────
        emit_verdict(result)

        # ── BLOCK if P0 ──────────────────────────────────────────────────────
        if result.blocked:
            raise GateCheckFailed(result)

        return result


# ── Persistence ───────────────────────────────────────────────────────────────

async def _persist_verdict(
    conn: asyncpg.Connection,
    result: GateResult,
    job_run_id: Optional[uuid.UUID],
) -> uuid.UUID:
    verdict_id = uuid.uuid4()
    details = {
        "checks": [
            {
                "name":    c.name,
                "passed":  c.passed,
                "severity": c.severity.value,
                "message": c.message,
                **c.details,
            }
            for c in result.checks
        ]
    }
    await conn.execute(
        """
        INSERT INTO dq.gate_verdicts
            (id, gate_id, feed, target_date, job_run_id, verdict, severity, details)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        """,
        verdict_id,
        result.gate_id,
        result.feed,
        result.target_date,
        job_run_id,
        result.verdict.value,
        result.severity.value,
        details,
    )
    return verdict_id


# ── Emit ──────────────────────────────────────────────────────────────────────

def emit_verdict(result: GateResult) -> None:
    gate  = str(result.gate_id)
    feed  = result.feed or "multi"
    label = result.verdict.value.lower()

    GATE_VERDICTS.labels(gate=gate, feed=feed, verdict=label).inc()

    log_fn = logger.error if result.verdict == Verdict.FAIL else (
             logger.warning if result.verdict == Verdict.AMBER else logger.info)
    log_fn(
        "gate=%s feed=%s date=%s verdict=%s severity=%s failed_checks=%d",
        gate, feed, result.target_date, result.verdict.value,
        result.severity.value, len(result.failed_checks),
        extra={
            "gate_id":      result.gate_id,
            "feed":         result.feed,
            "target_date":  str(result.target_date),
            "verdict":      result.verdict.value,
            "severity":     result.severity.value,
            "verdict_id":   str(result.verdict_id) if result.verdict_id else None,
        },
    )
