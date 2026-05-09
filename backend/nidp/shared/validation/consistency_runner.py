"""Cross-source consistency runner.

Runs every ConsistencyRule registered for a domain, persists a
consistency_runs row + per-finding rows, and returns a summary.

Designed to run AFTER all per-ingester runs for the day have completed
(i.e. triggered by the nidp_quality_gate DAG, not inside BaseIngester).

Usage:
    from nidp.shared.validation.consistency_runner import run_consistency_checks
    summary = await run_consistency_checks(target_date=date.today(), domain="all")
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from datetime import date
from typing import Optional

from nidp.shared.storage.pg import get_pool
from nidp.shared.validation.consistency import (
    ConsistencyFinding,
    ConsistencyRule,
    get_consistency_rules,
)

logger = logging.getLogger(__name__)


@dataclass
class ConsistencyRunSummary:
    run_id:         uuid.UUID
    target_date:    date
    domain:         str
    status:         str          # PASSED | FAILED | PARTIAL | ERROR
    rules_run:      int
    rules_failed:   int
    findings_count: int
    has_block:      bool
    findings:       list[ConsistencyFinding]


def _classify_status(findings: list[ConsistencyFinding], error: bool) -> str:
    if error:
        return "ERROR"
    if not findings:
        return "PASSED"
    if any(f.failure_class.value == "BLOCK" for f in findings):
        return "FAILED"
    if any(f.severity.value in ("ERROR", "CRITICAL") for f in findings):
        return "PARTIAL"
    return "PASSED"   # only INFO / WARN findings


async def run_consistency_checks(
    target_date: date,
    domain: str = "all",
) -> ConsistencyRunSummary:
    """Execute every registered ConsistencyRule for `domain` and persist results."""
    rules: list[ConsistencyRule] = get_consistency_rules(domain)
    run_id = uuid.uuid4()
    pool = await get_pool()

    findings: list[ConsistencyFinding] = []
    rules_failed = 0
    error_msg: Optional[str] = None
    started = time.time()

    async with pool.acquire() as conn:
        # Insert the run row early so a crash mid-run still has a record.
        await conn.execute(
            """
            INSERT INTO nidp.consistency_runs
                (run_id, target_date, domain, status,
                 rules_run, rules_failed, findings_count, has_block, started_at)
            VALUES ($1, $2, $3, 'PASSED', 0, 0, 0, FALSE, NOW())
            """,
            run_id, target_date, domain,
        )

        for rule in rules:
            try:
                results = await rule.check(conn, target_date)
            except Exception as exc:                               # noqa: BLE001
                logger.exception("consistency rule %s crashed", rule.name)
                rules_failed += 1
                error_msg = (error_msg or "") + f"{rule.name}: {exc}; "
                continue
            if results:
                rules_failed += 1
                findings.extend(results)

        has_block = any(f.failure_class.value == "BLOCK" for f in findings)
        status = _classify_status(findings, error=error_msg is not None)

        # Persist each finding
        for f in findings:
            await conn.execute(
                """
                INSERT INTO nidp.consistency_findings
                    (run_id, target_date, domain, dimension,
                     rule_name, severity, failure_class,
                     entity_type, entity_id, field_name,
                     source_a, value_a, source_b, value_b,
                     deviation_pct, message, detected_at)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,NOW())
                """,
                run_id, target_date, domain, f.dimension.value,
                f.rule_name, f.severity.value, f.failure_class.value,
                f.entity_type, f.entity_id, f.field_name,
                f.source_a, f.value_a, f.source_b, f.value_b,
                f.deviation_pct, f.message,
            )

        await conn.execute(
            """
            UPDATE nidp.consistency_runs SET
                status         = $2,
                rules_run      = $3,
                rules_failed   = $4,
                findings_count = $5,
                has_block      = $6,
                finished_at    = NOW(),
                notes          = $7
            WHERE run_id = $1
            """,
            run_id, status, len(rules), rules_failed, len(findings), has_block, error_msg,
        )

    duration_ms = int((time.time() - started) * 1000)
    logger.info(
        "consistency[%s] date=%s status=%s rules=%d failed=%d findings=%d block=%s %dms",
        domain, target_date, status, len(rules), rules_failed,
        len(findings), has_block, duration_ms,
    )

    return ConsistencyRunSummary(
        run_id=run_id,
        target_date=target_date,
        domain=domain,
        status=status,
        rules_run=len(rules),
        rules_failed=rules_failed,
        findings_count=len(findings),
        has_block=has_block,
        findings=findings,
    )
