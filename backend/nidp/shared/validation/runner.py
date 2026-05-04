"""Validation runner — invoked by BaseIngester after persist.

Runs every registered rule for the ingester, persists a
validation_runs row + per-finding rows, and returns a summary
the BaseIngester logs.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import date
from typing import Optional

from nidp.shared.storage.pg import get_pool

from .registry import get_rules
from .rules import Finding, Rule, RuleContext

logger = logging.getLogger(__name__)


@dataclass
class ValidationSummary:
    validation_id: uuid.UUID
    status: str                                    # PASSED | FAILED | PARTIAL | ERROR
    rules_run: int
    rules_failed: int
    findings_count: int
    has_block: bool
    findings: list[Finding]


def _classify_status(findings: list[Finding]) -> str:
    if not findings:
        return "PASSED"
    if any(f.failure_class.value == "BLOCK" for f in findings):
        return "FAILED"
    if any(f.severity.value in ("ERROR", "CRITICAL") for f in findings):
        return "PARTIAL"
    return "PASSED"  # only INFO/WARN


def _json_dumps(obj) -> str:
    def default(o):
        if hasattr(o, "isoformat"):
            return o.isoformat()
        return str(o)
    return json.dumps(obj, default=default)


async def run_validation(
    *,
    ingester: str,
    target_date: Optional[date],
    job_run_id: uuid.UUID,
) -> ValidationSummary:
    rules: list[Rule] = get_rules(ingester)
    validation_id = uuid.uuid4()
    pool = await get_pool()

    findings: list[Finding] = []
    rules_failed = 0
    error_msg: Optional[str] = None

    started = time.time()
    async with pool.acquire() as conn:
        # Begin run row early so a crash mid-rule still records
        await conn.execute(
            """
            INSERT INTO nidp.validation_runs
                (validation_id, job_run_id, ingester, target_date, status,
                 rules_run, rules_failed, findings_count, started_at)
            VALUES ($1, $2, $3, $4::date, 'PASSED', 0, 0, 0, NOW())
            """,
            validation_id, job_run_id, ingester, target_date,
        )

        ctx = RuleContext(
            conn=conn, ingester=ingester, target_date=target_date,
            job_run_id=job_run_id,
        )
        for rule in rules:
            try:
                results = await rule.check(ctx)
            except Exception as e:                                     # noqa: BLE001
                logger.exception("validation rule %s crashed", rule.name)
                results = []
                rules_failed += 1
                error_msg = (error_msg or "") + f"{rule.name}: {e}; "
                continue
            if results:
                rules_failed += 1
                findings.extend(results)

        status = _classify_status(findings) if error_msg is None else "ERROR"

        # Persist findings
        for f in findings:
            await conn.execute(
                """
                INSERT INTO nidp.validation_findings
                    (finding_id, validation_id, job_run_id, ingester, target_date,
                     rule_name, severity, failure_class, message,
                     expected, actual, sample_rows, detected_at)
                VALUES ($1, $2, $3, $4, $5::date, $6, $7, $8, $9, $10, $11, $12::jsonb, NOW())
                """,
                uuid.uuid4(), validation_id, job_run_id, ingester, target_date,
                f.rule_name, f.severity.value, f.failure_class.value, f.message,
                f.expected, f.actual, _json_dumps(f.sample_rows),
            )

        await conn.execute(
            """
            UPDATE nidp.validation_runs SET
                status = $2,
                finished_at = NOW(),
                rules_run = $3,
                rules_failed = $4,
                findings_count = $5,
                notes = $6
             WHERE validation_id = $1
            """,
            validation_id, status,
            len(rules), rules_failed, len(findings), error_msg,
        )

    duration_ms = int((time.time() - started) * 1000)
    logger.info(
        "validation[%s] target=%s status=%s rules=%d failed=%d findings=%d duration=%dms",
        ingester, target_date, status, len(rules), rules_failed, len(findings), duration_ms,
    )

    return ValidationSummary(
        validation_id=validation_id,
        status=status,
        rules_run=len(rules),
        rules_failed=rules_failed,
        findings_count=len(findings),
        has_block=any(f.failure_class.value == "BLOCK" for f in findings),
        findings=findings,
    )
