"""dq_runner — DB orchestration for the canonical (zip-derived) DQ stack.

For each suite in dq_suites.build_suites(): execute suite.fetch.to_sql() against the
NIDP DB, run it through dq_gate.run_suite(), and persist results — flag-only
(decision #1): never blocks ingest; the per-feed verdict surfaces via v_feed_status.

  findings -> nidp.validation_findings   (one row per failed rule)
  header   -> nidp.validation_runs       (one row per suite run; status = verdict)

Usage:
    python -m nidp.services.quality_gate.dq_runner            # all suites, today
    python -m nidp.services.quality_gate.dq_runner --feeds mf_holdings,nse_financials
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import date, datetime, timezone
from typing import Optional

import pandas as pd

from nidp.shared.logging_setup import setup_logging
from nidp.shared.storage.pg import close_pool, get_pool

from .dq_gate import RunContext, finding_rows, run_header, run_suite
from .dq_primitives import TradingCalendar
from .dq_suites import build_suites, trading_calendar

logger = logging.getLogger(__name__)

_FINDINGS_SQL = """
INSERT INTO nidp.validation_findings
  (finding_id, validation_id, job_run_id, ingester, target_date, rule_name,
   severity, failure_class, message, expected, actual, sample_rows, detected_at)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12::jsonb, $13)
"""

_RUN_SQL = """
INSERT INTO nidp.validation_runs
  (validation_id, job_run_id, ingester, target_date, started_at, finished_at,
   status, rules_run, rules_failed, findings_count, notes)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
"""

# NOTE: the gate maps the internal vocabulary -> the real plumbing enums via dq_sink
# (run_header.status, finding_rows.severity/failure_class, expected/actual as TEXT).
# This runner persists those values verbatim — no re-mapping here.


async def _load_calendar(conn) -> TradingCalendar:
    try:
        rows = await conn.fetch("SELECT holiday_date FROM nidp.nse_holidays")
        return trading_calendar({r["holiday_date"] for r in rows})
    except Exception as exc:                      # table absent / empty — degrade gracefully
        logger.warning("dq_runner: no holidays loaded (%s); using empty calendar", exc)
        return trading_calendar(set())


async def run(feeds: Optional[list[str]] = None, target_date: Optional[date] = None) -> dict:
    setup_logging(service="quality_gate")
    pool = await get_pool()
    async with pool.acquire() as conn:
        cal = await _load_calendar(conn)

    suites = build_suites(cal)
    td = target_date or date.today()
    verdicts: dict[str, str] = {}

    for name, suite in suites.items():
        if feeds and name not in feeds:
            continue
        ctx = RunContext(ingester=suite.ingester, target_date=td)
        started = datetime.now(timezone.utc)
        try:
            # Per-suite isolation: a fetch error (e.g. a suite naming a column the table
            # doesn't have) must surface as an ERROR run, never abort the whole batch.
            async with pool.acquire() as conn:
                recs = await conn.fetch(suite.fetch.to_sql())
            df = pd.DataFrame([dict(r) for r in recs])

            srun = run_suite(suite, df)
            hdr = run_header(srun, ctx)
            fr = finding_rows(srun, ctx)

            async with pool.acquire() as conn:
                async with conn.transaction():
                    await conn.execute(
                        _RUN_SQL, ctx.validation_id, ctx.job_run_id, suite.ingester, td,
                        started, datetime.now(timezone.utc), hdr["status"],
                        hdr["rules_run"], hdr["rules_failed"], hdr["findings_count"],
                        (suite.description or "")[:200],
                    )
                    if fr:
                        await conn.executemany(_FINDINGS_SQL, [
                            (f["finding_id"], f["validation_id"], f["job_run_id"], f["ingester"],
                             td, f["rule_name"], f["severity"], f["failure_class"],
                             f["message"], f["expected"], f["actual"], f["sample_rows"], started)
                            for f in fr
                        ])
            verdicts[name] = hdr["status"]
            logger.info("dq_runner: %-22s verdict=%-7s rules=%d failed=%d rows=%d",
                        name, hdr["status"], hdr["rules_run"], hdr["rules_failed"], len(df))
        except Exception as exc:
            verdicts[name] = "ERROR"
            logger.error("dq_runner: %-22s ERROR  %r", name, exc)
            async with pool.acquire() as conn:
                await conn.execute(
                    _RUN_SQL, ctx.validation_id, ctx.job_run_id, suite.ingester, td,
                    started, datetime.now(timezone.utc), "ERROR", 0, 1, 0,
                    f"suite error: {exc}"[:200],
                )

    await close_pool()
    return verdicts


def main() -> None:
    p = argparse.ArgumentParser(description="Run canonical DQ suites (flag-only).")
    p.add_argument("--feeds", default=None, help="Comma-separated suite names (default: all)")
    a = p.parse_args()
    feeds = [s.strip() for s in a.feeds.split(",")] if a.feeds else None
    asyncio.run(run(feeds=feeds))


if __name__ == "__main__":
    main()
