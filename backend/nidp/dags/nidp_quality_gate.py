"""DAG: nidp_quality_gate

Post-ingestion pipeline stage.  Runs after the market-EOD and MF
ingesters have settled (~21:30 IST / 16:00 UTC Mon-Fri).

Pipeline stages (in dependency order):

  consistency_mf    — cross-source + temporal + internal MF checks
  consistency_eq    — cross-source + temporal + internal equity checks
         ↓
  quality_score_mf  — compute weighted quality score for MF domain
  quality_score_eq  — compute weighted quality score for equity domain
         ↓
  gate_mf           — PASS → certify, REVIEW → exception queue, FAIL → quarantine
  gate_eq
         ↓
  cache_refresh     — invalidate API response cache for certified dates

Each task is idempotent: re-running for the same ds produces the same
outcome (consistency_runs rows are keyed by run_id, quality_scores are
append-only, certified_dates is UPSERT).
"""
from __future__ import annotations

try:
    from airflow import DAG
    from airflow.operators.python import PythonOperator
    AIRFLOW_AVAILABLE = True
except ImportError:                                                # pragma: no cover
    AIRFLOW_AVAILABLE = False
    DAG = None
    PythonOperator = None

import asyncio
import logging
from datetime import date, datetime, timedelta

from nidp.dags._dag_helpers import make_default_args

logger = logging.getLogger(__name__)


# ── Task implementations ─────────────────────────────────────────────

def _run_consistency(domain: str, ds: str) -> None:
    # Import here to avoid paying import cost at DAG-parse time
    from nidp.shared.validation.consistency_runner import run_consistency_checks
    # Trigger rule imports so they self-register
    from nidp.shared.validation.consistency_rules import mf, equity  # noqa: F401

    target = date.fromisoformat(ds)
    summary = asyncio.run(run_consistency_checks(target_date=target, domain=domain))
    logger.info(
        "consistency[%s] %s: status=%s rules=%d findings=%d block=%s",
        domain, target, summary.status, summary.rules_run,
        summary.findings_count, summary.has_block,
    )
    if summary.has_block:
        raise RuntimeError(
            f"consistency[{domain}] {target}: {summary.findings_count} finding(s) "
            f"including BLOCK — failing task so gate_task sees the right state"
        )


def _run_quality_score(domain: str, ds: str) -> None:
    from nidp.shared.storage.pg import get_pool
    from nidp.shared.validation.quality_score import (
        compute_quality_score, persist_quality_score,
    )

    async def _inner() -> None:
        target = date.fromisoformat(ds)
        pool   = await get_pool()
        async with pool.acquire() as conn:
            qs = await compute_quality_score(conn, target, domain)
            await persist_quality_score(conn, qs)
            logger.info(
                "quality_score[%s] %s: overall=%.3f cert=%s decision=%s",
                domain, target, qs.overall, qs.certification, qs.publish_decision,
            )

    asyncio.run(_inner())


def _run_gate(domain: str, ds: str) -> None:
    from nidp.shared.storage.pg import get_pool
    from nidp.shared.certification import CertificationPublisher
    from nidp.shared.quality_gate import QualityGate, GateOutcome
    from nidp.shared.validation.quality_score import compute_quality_score

    async def _inner() -> None:
        target = date.fromisoformat(ds)
        pool   = await get_pool()
        async with pool.acquire() as conn:
            gate     = QualityGate(conn)
            decision = await gate.evaluate(target, domain)

            if decision.outcome == GateOutcome.PASS:
                qs = await compute_quality_score(conn, target, domain)
                publisher = CertificationPublisher(conn)
                await publisher.publish(target, domain, quality_score=qs)
                logger.info("gate[%s] %s: PASS → certified", domain, target)
            elif decision.outcome == GateOutcome.REVIEW:
                logger.warning(
                    "gate[%s] %s: REVIEW → exception queue. reason=%s",
                    domain, target, decision.reason,
                )
            else:
                logger.error(
                    "gate[%s] %s: FAIL → quarantine. reason=%s",
                    domain, target, decision.reason,
                )
                raise RuntimeError(
                    f"gate[{domain}] {target}: FAIL — {decision.reason}"
                )

    asyncio.run(_inner())


def _run_cache_refresh(ds: str) -> None:
    """Signal DaaS API to drop response-cache for this date."""
    from nidp.shared.storage.pg import get_pool
    from nidp.shared.certification import CertificationPublisher

    async def _inner() -> None:
        target = date.fromisoformat(ds)
        pool   = await get_pool()
        # Re-trigger cache invalidation for all certified domains on this date
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT domain FROM nidp.certified_dates WHERE target_date = $1",
                target,
            )
            for row in rows:
                pub = CertificationPublisher(conn)
                await pub._invalidate_api_cache(target, row["domain"])
        logger.info("cache_refresh: invalidated cache for %s", target)

    asyncio.run(_inner())


# ── DAG definition ───────────────────────────────────────────────────

if AIRFLOW_AVAILABLE:
    with DAG(
        dag_id="nidp_quality_gate",
        description="Post-ingestion: consistency checks → quality score → gate → certify → cache flush",
        default_args=make_default_args(retries=1),
        start_date=datetime(2026, 1, 1),
        schedule="0 16 * * 1-5",                                   # Mon-Fri 16:00 UTC ≈ 21:30 IST
        catchup=False,
        max_active_runs=1,
        tags=["nidp", "quality", "gate"],
    ) as dag:

        # ── Stage 1: Consistency checks (parallel by domain) ─────────
        consistency_mf = PythonOperator(
            task_id="consistency_mf",
            python_callable=lambda **kw: _run_consistency("mf", kw["ds"]),
        )
        consistency_eq = PythonOperator(
            task_id="consistency_equity",
            python_callable=lambda **kw: _run_consistency("equity", kw["ds"]),
        )

        # ── Stage 2: Quality scores (parallel, wait for both checks) ──
        quality_mf = PythonOperator(
            task_id="quality_score_mf",
            python_callable=lambda **kw: _run_quality_score("mf", kw["ds"]),
        )
        quality_eq = PythonOperator(
            task_id="quality_score_equity",
            python_callable=lambda **kw: _run_quality_score("equity", kw["ds"]),
        )

        # ── Stage 3: Gate + certification (parallel by domain) ────────
        gate_mf = PythonOperator(
            task_id="gate_mf",
            python_callable=lambda **kw: _run_gate("mf", kw["ds"]),
        )
        gate_eq = PythonOperator(
            task_id="gate_equity",
            python_callable=lambda **kw: _run_gate("equity", kw["ds"]),
        )

        # ── Stage 4: Cache refresh (after both gates complete) ────────
        cache_refresh = PythonOperator(
            task_id="cache_refresh",
            python_callable=lambda **kw: _run_cache_refresh(kw["ds"]),
            trigger_rule="all_done",    # run even if one gate went to REVIEW
        )

        # ── Dependencies ──────────────────────────────────────────────
        [consistency_mf, consistency_eq] >> quality_mf
        [consistency_mf, consistency_eq] >> quality_eq
        quality_mf >> gate_mf
        quality_eq >> gate_eq
        [gate_mf, gate_eq] >> cache_refresh
