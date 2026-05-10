"""python -m nidp.services.quality_gate [--date YYYY-MM-DD] [--domain mf|equity|all]

Runs the full post-ingestion quality pipeline for one trading date:
  1. Consistency checks (all rules registered for the domain)
  2. Quality score computation (Q = 0.40A + 0.30C + 0.15P + 0.10F + 0.05U)
  3. Gate decision: PASS → certify + cache flush
                   REVIEW → exception queue
                   FAIL   → quarantine + non-zero exit (triggers Cloud Run retry)

Exit codes:
  0 — all domains PASS or REVIEW (publishable or queued for ops)
  1 — at least one domain FAIL (Cloud Run will retry up to --max-retries)
  2 — argument / config error
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import date, datetime

from nidp.shared.derived_run import run_with_job_log
from nidp.shared.logging_setup import setup_logging

# Trigger rule registration as a side-effect of import
from nidp.shared.validation.consistency_rules import mf as _mf_rules   # noqa: F401
from nidp.shared.validation.consistency_rules import equity as _eq_rules  # noqa: F401

from nidp.shared.storage.pg import get_pool, close_pool
from nidp.shared.validation.consistency_runner import run_consistency_checks
from nidp.shared.validation.quality_score import (
    compute_quality_score,
    persist_quality_score,
)
from nidp.shared.quality_gate import QualityGate, GateOutcome
from nidp.shared.certification import CertificationPublisher

logger = logging.getLogger(__name__)

_DOMAINS = ("mf", "equity")


async def run_pipeline(target_date: date, domain_arg: str) -> bool:
    """Returns True if all domains passed or went to REVIEW; False if any FAIL."""
    domains = _DOMAINS if domain_arg == "all" else (domain_arg,)
    pool    = await get_pool()
    all_ok  = True

    # ── Stage 0: Great Expectations ───────────────────────────────
    # Per-feed expectation suites translated from the user-supplied
    # NIDP_Sample_Feed_Expectation_Rules.docx. Findings land in
    # nidp.validation_findings, so they're picked up by the
    # quality-score (accuracy + completeness dimensions) and the
    # data-quality dashboard the same way ingester-side validators are.
    try:
        from nidp.services.quality_gate.great_expectations_runner import run_all as _ge_run_all
        ge_report = await _ge_run_all(target_date=target_date.isoformat())
        ge_summary = ge_report.get("summary", {})
        logger.info(
            "great_expectations: feeds=%d pass=%d fail=%d (per-feed: %s)",
            ge_summary.get("feeds_total", 0),
            ge_summary.get("feeds_pass",  0),
            ge_summary.get("feeds_fail",  0),
            {k: ("PASS" if v.get("success") else f"FAIL/{v.get('failed_count', '?')}") for k, v in ge_report.get("feeds", {}).items()},
        )
    except Exception:                                                    # noqa: BLE001
        # GE engine must NEVER fail the gate by itself — its findings
        # influence the quality score, but a runner crash should not
        # block certification of unrelated domains.
        logger.exception("great_expectations runner crashed (continuing)")

    # ── Stage 0b: Dynamic rules from dq.expectations_active ──────
    # AI-promoted + hand-authored business rules persisted in the
    # registry. Findings flow into nidp.validation_findings and feed
    # the quality score the same way GE findings do.
    try:
        from nidp.services.quality_gate.dynamic_runner import run_active_rules
        dyn_report = await run_active_rules(target_date=target_date)
        if dyn_report.get("skipped"):
            logger.info(
                "dynamic_rules: skipped — %s",
                dyn_report.get("skipped_reason", "unknown"),
            )
        else:
            logger.info(
                "dynamic_rules: rules=%d pass=%d fail=%d error=%d (datasets=%d)",
                dyn_report.get("rules_total", 0),
                dyn_report.get("rules_pass",  0),
                dyn_report.get("rules_fail",  0),
                dyn_report.get("rules_error", 0),
                len(dyn_report.get("datasets", {})),
            )
    except Exception:                                                    # noqa: BLE001
        logger.exception("dynamic_runner crashed (continuing)")

    for domain in domains:
        logger.info("=== quality_gate[%s] %s ===", domain, target_date)

        # Stage 1: consistency checks
        c_summary = await run_consistency_checks(target_date=target_date, domain=domain)
        logger.info(
            "consistency[%s]: status=%s rules=%d findings=%d block=%s",
            domain, c_summary.status, c_summary.rules_run,
            c_summary.findings_count, c_summary.has_block,
        )

        # Stage 2: quality score
        async with pool.acquire() as conn:
            qs = await compute_quality_score(conn, target_date, domain)
            await persist_quality_score(conn, qs)
        logger.info(
            "quality_score[%s]: overall=%.3f cert=%s decision=%s",
            domain, qs.overall, qs.certification, qs.publish_decision,
        )

        # Stage 3: gate decision
        async with pool.acquire() as conn:
            gate      = QualityGate(conn)
            decision  = await gate.evaluate(target_date, domain)

        logger.info(
            "gate[%s]: outcome=%s reason=%s",
            domain, decision.outcome, decision.reason,
        )

        if decision.outcome == GateOutcome.PASS:
            async with pool.acquire() as conn:
                pub = CertificationPublisher(conn)
                await pub.publish(target_date, domain, quality_score=qs)
            logger.info("certified[%s] %s — cache invalidated", domain, target_date)

        elif decision.outcome == GateOutcome.REVIEW:
            logger.warning(
                "REVIEW[%s] %s — added to exception_queue. ops must resolve manually.",
                domain, target_date,
            )

        else:  # FAIL
            logger.error(
                "FAIL[%s] %s — quarantined. reason: %s",
                domain, target_date, decision.reason,
            )
            all_ok = False

    return all_ok


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def main() -> None:
    setup_logging(service="quality_gate")

    p = argparse.ArgumentParser(
        description="NIDP Quality Gate — post-ingestion pipeline",
    )
    p.add_argument(
        "--date", type=_parse_date, default=None,
        help="Target date (default: today)",
    )
    p.add_argument(
        "--domain", choices=("mf", "equity", "all"), default="all",
        help="Domain to gate (default: all)",
    )
    args = p.parse_args()

    target_date = args.date or date.today()
    logger.info("quality_gate starting: date=%s domain=%s", target_date, args.domain)

    async def _main() -> bool:
        try:
            return await run_with_job_log(
                "quality_gate",
                run_pipeline,
                target_date,
                args.domain,
                target_date=target_date,
            )
        finally:
            await close_pool()

    success = asyncio.run(_main())
    if not success:
        logger.error("quality_gate FAILED — exiting with code 1 (Cloud Run will retry)")
        sys.exit(1)

    logger.info("quality_gate complete for %s", target_date)


if __name__ == "__main__":
    main()
