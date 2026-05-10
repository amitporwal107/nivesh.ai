"""Replay Engine — walks a date range, re-runs the quality pipeline.

Key design decisions:
  - Reuses existing services (compute_quality_score, run_consistency_checks,
    great_expectations_runner) rather than re-implementing them.
  - Threads a versioned `ScoringPolicy` through scoring, certification,
    and publish-gate decisions so calibration is config-driven.
  - Persists per-(date, domain) outcomes into `audit.replay_dates` and
    aggregate stats into `audit.replay_statistics`.
  - Skips weekends/holidays via `nidp.nse_holidays` if available, else
    weekday() check.
  - `parallel` controls how many dates run concurrently via asyncio
    semaphore.
  - `reset_data` purges existing replay-managed tables (quality_scores,
    exception_queue, quarantine_log, certified_dates) for the window
    so each run is deterministic.
"""
from __future__ import annotations

import asyncio
import logging
import statistics
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import asyncpg

from .policy import ScoringPolicy, get_policy
from .failure_injector import (
    plan_failures,
    persist_failure,
    update_detection,
    InjectedFailure,
)

logger = logging.getLogger(__name__)

DEFAULT_DOMAINS = ("mf", "equity")


# ─────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────
@dataclass
class ReplayConfig:
    start_date:      date
    end_date:        date
    domains:         List[str]
    policy_version:  str          = "v1"
    parallel:        int          = 4
    inject_failures: bool         = False
    reset_data:      bool         = False
    initiated_by:    Optional[str] = None
    failure_seed:    Optional[int] = None
    failure_rate:    float        = 0.10
    skip_weekends:   bool         = True

    def __post_init__(self):
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        if not self.domains:
            self.domains = list(DEFAULT_DOMAINS)
        for d in self.domains:
            if d not in ("mf", "equity", "all"):
                raise ValueError(f"unknown domain: {d}")
        if self.parallel < 1 or self.parallel > 64:
            raise ValueError("parallel must be in [1, 64]")
        if not 0.0 <= self.failure_rate <= 1.0:
            raise ValueError("failure_rate must be in [0, 1]")


# ─────────────────────────────────────────────────────────────────
# Trading-day helpers
# ─────────────────────────────────────────────────────────────────
async def list_trading_days(
    conn: Optional[asyncpg.Connection],
    start: date,
    end: date,
    *,
    skip_weekends: bool = True,
) -> List[date]:
    """Return every trading day in [start, end] inclusive.

    Uses nidp.nse_holidays if available; otherwise falls back to a
    weekday-only filter. Both endpoints are inclusive.
    """
    days: List[date] = []
    cur = start
    while cur <= end:
        if not skip_weekends or cur.weekday() < 5:   # Mon-Fri
            days.append(cur)
        cur += timedelta(days=1)

    if conn is None:
        return days

    try:
        holidays = {
            r["holiday_date"]
            for r in await conn.fetch(
                """
                SELECT holiday_date
                  FROM nidp.nse_holidays
                 WHERE holiday_date BETWEEN $1 AND $2
                   AND COALESCE(segment, 'CM') IN ('CM', 'ALL')
                """,
                start, end,
            )
        }
        return [d for d in days if d not in holidays]
    except (asyncpg.UndefinedTableError, asyncpg.UndefinedColumnError):
        return days
    except Exception as e:                                                # noqa: BLE001
        logger.warning("trading-day filter: holiday lookup failed (%s) — using weekday-only fallback", e)
        return days


# ─────────────────────────────────────────────────────────────────
# Reset helpers
# ─────────────────────────────────────────────────────────────────
async def reset_window(
    conn: asyncpg.Connection,
    start: date,
    end: date,
    domains: List[str],
) -> Dict[str, int]:
    """Wipe replay-managed rows for the window so the engine starts
    from a clean slate. Returns row-counts deleted per table."""
    deleted: Dict[str, int] = {}
    domain_filter = (
        "AND domain = ANY($3::text[])" if domains and "all" not in domains else ""
    )
    args = [start, end, domains] if domain_filter else [start, end]

    for table in (
        "nidp.quality_scores",
        "nidp.certified_dates",
        "nidp.exception_queue",
        "nidp.quarantine_log",
    ):
        try:
            sql = f"""
                DELETE FROM {table}
                 WHERE target_date BETWEEN $1 AND $2
                 {domain_filter}
            """
            res = await conn.execute(sql, *args)
            # res like 'DELETE N'
            try:
                deleted[table] = int(res.split()[-1])
            except Exception:                                             # noqa: BLE001
                deleted[table] = 0
        except Exception as e:                                            # noqa: BLE001
            logger.warning("reset_window: failed to clear %s — %s", table, e)
            deleted[table] = -1
    return deleted


# ─────────────────────────────────────────────────────────────────
# Per-date pipeline
# ─────────────────────────────────────────────────────────────────
@dataclass
class DateOutcome:
    target_date:     date
    domain:          str
    overall_score:   Optional[float]      = None
    confidence:      Optional[float]      = None
    accuracy:        Optional[float]      = None
    consistency:     Optional[float]      = None
    completeness:    Optional[float]      = None
    freshness:       Optional[float]      = None
    auditability:    Optional[float]      = None
    certification:   Optional[str]        = None
    publish_decision: Optional[str]       = None
    gate_outcome:    Optional[str]        = None
    block_findings:  int                  = 0
    rules_run:       int                  = 0
    rules_failed:    int                  = 0
    duration_ms:     Optional[int]        = None
    error:           Optional[str]        = None


async def _run_one_date(
    pool: asyncpg.Pool,
    target_date: date,
    domain: str,
    policy: ScoringPolicy,
    *,
    inject_failures: bool,
    failure_seed: Optional[int],
    failure_rate: float,
    replay_id: str,
) -> DateOutcome:
    """Execute the existing post-ingestion pipeline for one (date, domain)
    under the given policy and return the outcome."""
    t0 = time.perf_counter()
    out = DateOutcome(target_date=target_date, domain=domain)

    # Lazy imports — avoid forcing the entire pipeline graph at module
    # load time so unit tests can stub these out.
    from nidp.shared.validation.consistency_runner import run_consistency_checks
    from nidp.shared.validation.quality_score import (
        compute_quality_score, persist_quality_score,
    )

    injected: List[InjectedFailure] = []
    try:
        if inject_failures:
            injected = plan_failures(
                target_date, domain, seed=failure_seed, rate=failure_rate,
            )
            async with pool.acquire() as c2:
                for f in injected:
                    await persist_failure(c2, replay_id, f)

        # Stage 1: consistency
        try:
            cs = await run_consistency_checks(target_date=target_date, domain=domain)
            out.rules_run    = int(getattr(cs, "rules_run",    0) or 0)
            out.rules_failed = int(getattr(cs, "rules_failed", 0) or 0)
            out.block_findings = 1 if getattr(cs, "has_block", False) else 0
        except Exception as e:                                             # noqa: BLE001
            logger.warning("replay: consistency check failed for %s/%s: %s", target_date, domain, e)

        # Stage 2: scoring (using existing dimension-derivation logic)
        async with pool.acquire() as conn:
            qs = await compute_quality_score(conn, target_date, domain)
            await persist_quality_score(conn, qs)

        # Re-score under our policy. `qs.confidence` may be None if the
        # confidence sub-components weren't computable; fall back to
        # auditability for the K-component (matches legacy semantics).
        k_value = qs.confidence if qs.confidence is not None else qs.auditability

        overall = policy.score(
            accuracy=qs.accuracy,
            consistency=qs.consistency,
            completeness=qs.completeness,
            freshness=qs.freshness,
            confidence=k_value,
        )
        cert = policy.certify(overall)
        decision = policy.publish_decision(overall, qs.confidence)

        out.overall_score    = overall
        out.confidence       = qs.confidence
        out.accuracy         = qs.accuracy
        out.consistency      = qs.consistency
        out.completeness     = qs.completeness
        out.freshness        = qs.freshness
        out.auditability     = qs.auditability
        out.certification    = cert
        out.publish_decision = decision

        # Gate outcome maps decision → PASS/REVIEW/FAIL using policy
        # cutoffs for symmetry with QualityGate.
        if cert in ("GOLD", "SILVER") and out.block_findings == 0:
            gate = "PASS"
        elif cert == "REVIEW" or out.block_findings > 0:
            gate = "REVIEW"
        else:
            gate = "FAIL"
        out.gate_outcome = gate

        # Side-effects: write into governance tables for parity with
        # production gate (so dashboards populate from replay data).
        async with pool.acquire() as conn:
            if gate == "PASS":
                await conn.execute(
                    """
                    INSERT INTO nidp.certified_dates
                        (target_date, domain, overall_score, certification)
                    VALUES ($1, $2, $3,
                        CASE WHEN $4 = 'REJECTED' THEN 'REVIEW' ELSE $4 END)
                    ON CONFLICT (target_date, domain) DO UPDATE
                        SET overall_score = EXCLUDED.overall_score,
                            certification = EXCLUDED.certification,
                            certified_at  = NOW()
                    """,
                    target_date, domain, overall, cert,
                )
            elif gate == "REVIEW":
                await conn.execute(
                    """
                    INSERT INTO nidp.exception_queue
                        (target_date, domain, outcome, quality_score,
                         confidence_score, block_findings, reason)
                    VALUES ($1, $2, 'REVIEW', $3, $4, $5, $6)
                    ON CONFLICT (target_date, domain) DO UPDATE
                        SET quality_score    = EXCLUDED.quality_score,
                            confidence_score = EXCLUDED.confidence_score,
                            block_findings   = EXCLUDED.block_findings,
                            reason           = EXCLUDED.reason
                    """,
                    target_date, domain, overall, qs.confidence,
                    out.block_findings,
                    f"replay/{policy.version}: cert={cert} blocks={out.block_findings}",
                )
            else:  # FAIL
                await conn.execute(
                    """
                    INSERT INTO nidp.quarantine_log
                        (target_date, domain, quality_score,
                         confidence_score, block_findings, reason)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    ON CONFLICT (target_date, domain) DO UPDATE
                        SET quality_score    = EXCLUDED.quality_score,
                            confidence_score = EXCLUDED.confidence_score,
                            block_findings   = EXCLUDED.block_findings,
                            reason           = EXCLUDED.reason
                    """,
                    target_date, domain, overall, qs.confidence,
                    out.block_findings,
                    f"replay/{policy.version}: cert={cert} score={overall:.2f}",
                )

        # If we injected failures, mark detected/not-detected based on
        # whether the gate ended up FAIL/REVIEW (proxy for detection —
        # for a dedicated pass we'd correlate with rule names).
        if injected:
            detected = gate in ("FAIL", "REVIEW")
            async with pool.acquire() as c3:
                for f in injected:
                    await update_detection(
                        c3, f.failure_id, detected,
                        f"gate_outcome={gate}",
                    )

    except Exception as e:                                                # noqa: BLE001
        logger.exception("replay: pipeline crashed for %s/%s", target_date, domain)
        out.error = f"{type(e).__name__}: {str(e)[:500]}"

    out.duration_ms = int((time.perf_counter() - t0) * 1000)
    return out


# ─────────────────────────────────────────────────────────────────
# Engine
# ─────────────────────────────────────────────────────────────────
class ReplayEngine:
    """Orchestrates a single replay invocation.

    Usage:
        async with asyncpg.create_pool(dsn) as pool:
            engine = ReplayEngine(pool, config)
            stats = await engine.run()
    """

    def __init__(self, pool: asyncpg.Pool, config: ReplayConfig):
        self.pool   = pool
        self.cfg    = config
        self.replay_id: Optional[str] = None
        self.policy: Optional[ScoringPolicy] = None
        self._semaphore = asyncio.Semaphore(config.parallel)

    async def _create_run_row(self) -> str:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO audit.replay_runs
                    (start_date, end_date, domains, policy_version,
                     parallel, inject_failures, reset_data,
                     initiated_by, config_json)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb)
                RETURNING replay_id::text
                """,
                self.cfg.start_date, self.cfg.end_date, self.cfg.domains,
                self.cfg.policy_version, self.cfg.parallel,
                self.cfg.inject_failures, self.cfg.reset_data,
                self.cfg.initiated_by,
                _to_json({
                    "failure_seed": self.cfg.failure_seed,
                    "failure_rate": self.cfg.failure_rate,
                    "skip_weekends": self.cfg.skip_weekends,
                }),
            )
            return row["replay_id"]

    async def _persist_outcome(self, outcome: DateOutcome) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO audit.replay_dates
                    (replay_id, target_date, domain,
                     overall_score, confidence_score,
                     accuracy, consistency, completeness, freshness, auditability,
                     certification, publish_decision, gate_outcome,
                     block_findings, rules_run, rules_failed,
                     duration_ms, error)
                VALUES ($1::uuid, $2, $3, $4, $5, $6, $7, $8, $9, $10,
                        $11, $12, $13, $14, $15, $16, $17, $18)
                ON CONFLICT (replay_id, target_date, domain) DO UPDATE
                    SET overall_score    = EXCLUDED.overall_score,
                        confidence_score = EXCLUDED.confidence_score,
                        accuracy         = EXCLUDED.accuracy,
                        consistency      = EXCLUDED.consistency,
                        completeness     = EXCLUDED.completeness,
                        freshness        = EXCLUDED.freshness,
                        auditability     = EXCLUDED.auditability,
                        certification    = EXCLUDED.certification,
                        publish_decision = EXCLUDED.publish_decision,
                        gate_outcome     = EXCLUDED.gate_outcome,
                        block_findings   = EXCLUDED.block_findings,
                        rules_run        = EXCLUDED.rules_run,
                        rules_failed     = EXCLUDED.rules_failed,
                        duration_ms      = EXCLUDED.duration_ms,
                        error            = EXCLUDED.error,
                        finished_at      = NOW()
                """,
                self.replay_id, outcome.target_date, outcome.domain,
                outcome.overall_score, outcome.confidence,
                outcome.accuracy, outcome.consistency, outcome.completeness,
                outcome.freshness, outcome.auditability,
                outcome.certification, outcome.publish_decision,
                outcome.gate_outcome,
                outcome.block_findings, outcome.rules_run, outcome.rules_failed,
                outcome.duration_ms, outcome.error,
            )

    async def _finalize(self, outcomes: List[DateOutcome], status: str, error: Optional[str]) -> Dict[str, Any]:
        scores = [o.overall_score for o in outcomes if o.overall_score is not None]
        durations = [o.duration_ms for o in outcomes if o.duration_ms is not None]

        def pct(values: list, p: float) -> Optional[float]:
            if not values:
                return None
            try:
                return round(statistics.quantiles(values, n=100)[int(p) - 1], 3)
            except statistics.StatisticsError:
                return round(values[0], 3)

        stats: Dict[str, Any] = {
            "total_evaluations":  len(outcomes),
            "pass_count":         sum(1 for o in outcomes if o.gate_outcome == "PASS"),
            "review_count":       sum(1 for o in outcomes if o.gate_outcome == "REVIEW"),
            "fail_count":         sum(1 for o in outcomes if o.gate_outcome == "FAIL"),
            "avg_overall_score":  round(statistics.fmean(scores), 3) if scores else None,
            "p50_overall_score":  pct(scores, 50),
            "p10_overall_score":  pct(scores, 10),
            "cert_gold":          sum(1 for o in outcomes if o.certification == "GOLD"),
            "cert_silver":        sum(1 for o in outcomes if o.certification == "SILVER"),
            "cert_review":        sum(1 for o in outcomes if o.certification == "REVIEW"),
            "cert_rejected":      sum(1 for o in outcomes if o.certification == "REJECTED"),
            "publish_auto":       sum(1 for o in outcomes if o.publish_decision == "PUBLISH"),
            "publish_review":     sum(1 for o in outcomes if o.publish_decision == "REVIEW"),
            "publish_reject":     sum(1 for o in outcomes if o.publish_decision == "REJECT"),
            "quarantine_count":   sum(1 for o in outcomes if o.gate_outcome == "FAIL"),
            "exception_count":    sum(1 for o in outcomes if o.gate_outcome == "REVIEW"),
            "avg_duration_ms":    int(statistics.fmean(durations)) if durations else None,
        }

        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO audit.replay_statistics
                    (replay_id, total_evaluations, pass_count, review_count, fail_count,
                     avg_overall_score, p50_overall_score, p10_overall_score,
                     cert_gold, cert_silver, cert_review, cert_rejected,
                     publish_auto, publish_review, publish_reject,
                     quarantine_count, exception_count, avg_duration_ms)
                VALUES ($1::uuid, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12,
                        $13, $14, $15, $16, $17, $18)
                ON CONFLICT (replay_id) DO UPDATE
                    SET total_evaluations = EXCLUDED.total_evaluations,
                        pass_count        = EXCLUDED.pass_count,
                        review_count      = EXCLUDED.review_count,
                        fail_count        = EXCLUDED.fail_count,
                        avg_overall_score = EXCLUDED.avg_overall_score,
                        p50_overall_score = EXCLUDED.p50_overall_score,
                        p10_overall_score = EXCLUDED.p10_overall_score,
                        cert_gold         = EXCLUDED.cert_gold,
                        cert_silver       = EXCLUDED.cert_silver,
                        cert_review       = EXCLUDED.cert_review,
                        cert_rejected     = EXCLUDED.cert_rejected,
                        publish_auto      = EXCLUDED.publish_auto,
                        publish_review    = EXCLUDED.publish_review,
                        publish_reject    = EXCLUDED.publish_reject,
                        quarantine_count  = EXCLUDED.quarantine_count,
                        exception_count   = EXCLUDED.exception_count,
                        avg_duration_ms   = EXCLUDED.avg_duration_ms,
                        computed_at       = NOW()
                """,
                self.replay_id, stats["total_evaluations"], stats["pass_count"],
                stats["review_count"], stats["fail_count"],
                stats["avg_overall_score"], stats["p50_overall_score"], stats["p10_overall_score"],
                stats["cert_gold"], stats["cert_silver"], stats["cert_review"], stats["cert_rejected"],
                stats["publish_auto"], stats["publish_review"], stats["publish_reject"],
                stats["quarantine_count"], stats["exception_count"], stats["avg_duration_ms"],
            )

            await conn.execute(
                """
                UPDATE audit.replay_runs
                   SET status          = $2,
                       finished_at     = NOW(),
                       dates_processed = $3,
                       dates_failed    = $4,
                       error           = $5
                 WHERE replay_id       = $1::uuid
                """,
                self.replay_id, status,
                stats["total_evaluations"],
                sum(1 for o in outcomes if o.error),
                error,
            )

        stats["replay_id"] = self.replay_id
        stats["status"]    = status
        stats["error"]     = error
        return stats

    async def run(self) -> Dict[str, Any]:
        """Execute the full replay. Returns aggregate statistics."""
        # 1. Resolve policy
        async with self.pool.acquire() as conn:
            self.policy = await get_policy(conn, self.cfg.policy_version)

        # 2. Compute trading days
        async with self.pool.acquire() as conn:
            days = await list_trading_days(
                conn, self.cfg.start_date, self.cfg.end_date,
                skip_weekends=self.cfg.skip_weekends,
            )
        if not days:
            raise ValueError("no trading days in window")

        # 3. Persist replay row + dates_total
        self.replay_id = await self._create_run_row()
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE audit.replay_runs SET dates_total=$2 WHERE replay_id=$1::uuid",
                self.replay_id, len(days) * len(self.cfg.domains),
            )

        # 4. Optional reset
        if self.cfg.reset_data:
            async with self.pool.acquire() as conn:
                purged = await reset_window(
                    conn, self.cfg.start_date, self.cfg.end_date, self.cfg.domains,
                )
            logger.info("replay: reset rows = %s", purged)

        # 5. Walk dates × domains under semaphore
        outcomes: List[DateOutcome] = []
        status = "SUCCESS"
        error: Optional[str] = None

        async def _bounded(target_date: date, domain: str) -> DateOutcome:
            async with self._semaphore:
                outcome = await _run_one_date(
                    self.pool, target_date, domain, self.policy,
                    inject_failures=self.cfg.inject_failures,
                    failure_seed=self.cfg.failure_seed,
                    failure_rate=self.cfg.failure_rate,
                    replay_id=self.replay_id,
                )
                await self._persist_outcome(outcome)
                return outcome

        try:
            tasks = [
                _bounded(d, dom)
                for d in days
                for dom in self.cfg.domains
            ]
            outcomes = await asyncio.gather(*tasks)
        except Exception as e:                                            # noqa: BLE001
            logger.exception("replay: orchestration failed")
            status = "FAILED"
            error = f"{type(e).__name__}: {str(e)[:500]}"

        return await self._finalize(outcomes, status, error)


# ─────────────────────────────────────────────────────────────────
# Top-level helper
# ─────────────────────────────────────────────────────────────────
async def run_replay(pool: asyncpg.Pool, config: ReplayConfig) -> Dict[str, Any]:
    """One-shot helper. Use ReplayEngine directly for finer control."""
    return await ReplayEngine(pool, config).run()


# ─────────────────────────────────────────────────────────────────
# Internals
# ─────────────────────────────────────────────────────────────────
def _to_json(payload: Any) -> str:
    import json
    return json.dumps(payload, default=str)
