"""Quality Gate — PASS / REVIEW / FAIL router.

This is the decision point that sits between the Validation + Consistency
engines and the Certification publisher.  It reads the quality score and
block findings for a (date, domain) and routes to one of three paths:

  PASS   → hand off to CertificationPublisher.publish()
  REVIEW → write to nidp.exception_queue; alert ops channel
  FAIL   → quarantine the run; suppress from API; alert ops

Decision matrix (from NIDP Data Quality Rules Summary):
  Any BLOCK finding           → FAIL
  Q  < 95                     → FAIL
  Q ∈ [95, 98) OR K < 90     → REVIEW  (HOLD or MANUAL_REVIEW)
  Q ≥ 98 AND K ≥ 90          → PASS    (AUTO_PUBLISH)

Usage:
    from nidp.shared.quality_gate import QualityGate
    gate = QualityGate(conn)
    decision = await gate.evaluate(target_date, domain)
    if decision.outcome == "PASS":
        await certifier.publish(target_date, domain)
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import asyncpg

from nidp.shared.validation.quality_score import QualityScore

logger = logging.getLogger(__name__)


class GateOutcome:
    PASS   = "PASS"
    REVIEW = "REVIEW"
    FAIL   = "FAIL"


@dataclass
class GateDecision:
    target_date:     date
    domain:          str
    outcome:         str                  # PASS | REVIEW | FAIL
    quality_score:   Optional[float]
    confidence:      Optional[float]
    certification:   Optional[str]
    block_findings:  int
    reason:          str
    findings_summary: list[dict] = field(default_factory=list)


class QualityGate:
    def __init__(self, conn: asyncpg.Connection) -> None:
        self._conn = conn

    async def evaluate(self, target_date: date, domain: str) -> GateDecision:
        """Run the full gate evaluation for (date, domain)."""
        # 1. Fetch latest quality score
        qs_row = await self._conn.fetchrow(
            """
            SELECT overall_score, confidence_score, certification, publish_decision
              FROM nidp.v_data_certification
             WHERE target_date = $1 AND domain = $2
            """,
            target_date, domain,
        )

        # 2. Count BLOCK consistency findings
        block_count = int(await self._conn.fetchval(
            """
            SELECT count(*) FROM nidp.consistency_findings
             WHERE target_date = $1 AND domain = $2
               AND failure_class = 'BLOCK'
            """,
            target_date, domain,
        ) or 0)

        # 3. Also count BLOCK validation findings from per-ingester runs
        val_blocks = int(await self._conn.fetchval(
            """
            SELECT count(*) FROM nidp.validation_findings vf
              JOIN nidp.validation_runs vr ON vr.job_run_id = vf.job_run_id
             WHERE vr.target_date = $1
               AND vf.failure_class = 'BLOCK'
               AND ($2 = 'all' OR vf.ingester LIKE $3)
            """,
            target_date, domain, f"{domain}%",
        ) or 0)

        total_blocks = block_count + val_blocks

        q  = float(qs_row["overall_score"])   if qs_row else None
        k  = float(qs_row["confidence_score"]) if qs_row and qs_row["confidence_score"] else None
        cert = qs_row["certification"]          if qs_row else None

        # 4. Apply decision matrix
        if total_blocks > 0:
            outcome = GateOutcome.FAIL
            reason  = f"{total_blocks} BLOCK finding(s) — data condemned, suppressed from API"
        elif q is None:
            outcome = GateOutcome.REVIEW
            reason  = "no quality score computed — manual review required"
        elif q < 95.0:
            outcome = GateOutcome.FAIL
            reason  = f"quality score {q:.2f} < 95 threshold — reject"
        elif q < 98.0 or (k is not None and k < 90.0):
            outcome = GateOutcome.REVIEW
            reason  = (
                f"quality score {q:.2f} in [95, 98) — hold for review"
                if q < 98.0
                else f"confidence {k:.2f} < 90 — manual review required"
            )
        else:
            outcome = GateOutcome.PASS
            reason  = f"quality {q:.2f}, confidence {k:.2f} — auto-publish"

        decision = GateDecision(
            target_date=target_date,
            domain=domain,
            outcome=outcome,
            quality_score=q,
            confidence=k,
            certification=cert,
            block_findings=total_blocks,
            reason=reason,
        )

        # 5. Persist to exception_queue or quarantine based on outcome
        if outcome == GateOutcome.REVIEW:
            await self._write_exception(decision)
        elif outcome == GateOutcome.FAIL:
            await self._quarantine(decision)

        logger.info(
            "quality_gate[%s] date=%s outcome=%s q=%.2f k=%s blocks=%d reason=%s",
            domain, target_date, outcome,
            q or 0, f"{k:.2f}" if k else "n/a", total_blocks, reason,
        )
        return decision

    async def _write_exception(self, decision: GateDecision) -> None:
        await self._conn.execute(
            """
            INSERT INTO nidp.exception_queue
                (queue_id, target_date, domain, outcome,
                 quality_score, confidence_score, block_findings,
                 reason, created_at, resolved)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,NOW(),FALSE)
            ON CONFLICT (target_date, domain) DO UPDATE SET
                outcome         = EXCLUDED.outcome,
                quality_score   = EXCLUDED.quality_score,
                confidence_score= EXCLUDED.confidence_score,
                block_findings  = EXCLUDED.block_findings,
                reason          = EXCLUDED.reason,
                created_at      = NOW(),
                resolved        = FALSE
            """,
            uuid.uuid4(), decision.target_date, decision.domain,
            decision.outcome, decision.quality_score,
            decision.confidence, decision.block_findings, decision.reason,
        )

    async def _quarantine(self, decision: GateDecision) -> None:
        await self._conn.execute(
            """
            INSERT INTO nidp.quarantine_log
                (quarantine_id, target_date, domain,
                 quality_score, confidence_score, block_findings,
                 reason, quarantined_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,NOW())
            ON CONFLICT (target_date, domain) DO UPDATE SET
                quality_score    = EXCLUDED.quality_score,
                confidence_score = EXCLUDED.confidence_score,
                block_findings   = EXCLUDED.block_findings,
                reason           = EXCLUDED.reason,
                quarantined_at   = NOW()
            """,
            uuid.uuid4(), decision.target_date, decision.domain,
            decision.quality_score, decision.confidence,
            decision.block_findings, decision.reason,
        )
