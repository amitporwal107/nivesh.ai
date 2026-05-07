"""Validation rules for the nse_equity_master ingester."""
from __future__ import annotations

from nidp.shared.validation import register
from nidp.shared.validation.rules import (
    CountAtLeastRule, CustomSQLRule, FailureClass, NoNullsRule, Severity,
)

REQUIRED_FIELDS = NoNullsRule(
    name="nse_equity_master.required_fields",
    table="nidp.sector_master",
    columns=["symbol"],
    severity=Severity.ERROR,
    failure_class=FailureClass.FIX,
)

# NSE has ~2000 listed equities. <1500 means we got a partial CSV.
ROW_COUNT_MIN = CountAtLeastRule(
    name="nse_equity_master.row_count_min",
    # CountAtLeastRule binds (target_date, job_run_id). target_date is
    # irrelevant for this weekly reference feed; we filter by run.
    sql="""
        SELECT count(*) FROM nidp.sector_master
         WHERE $1::date IS NOT DISTINCT FROM $1::date
           AND source_run_id = $2
    """,
    min_count=1500,
    severity=Severity.CRITICAL,
    failure_class=FailureClass.BLOCK,
)

# ISIN is the canonical cross-exchange identifier — should be present
# for nearly all rows. Tracking >5% missing means parser/header drift.
ISIN_COVERAGE = CustomSQLRule(
    name="nse_equity_master.isin_coverage",
    sql="""
        SELECT (
          COUNT(*) FILTER (WHERE isin IS NULL OR isin = '')
            > GREATEST(50, COUNT(*) / 20)
        )
          FROM nidp.sector_master
         WHERE source_run_id = $1
    """,
    message="more than 5% of rows missing ISIN — parser/header drift likely",
    severity=Severity.WARN,
    failure_class=FailureClass.FIX,
    params_fn=lambda c: [c.job_run_id],
)

register("nse_equity_master", [
    REQUIRED_FIELDS,
    ROW_COUNT_MIN,
    ISIN_COVERAGE,
])
