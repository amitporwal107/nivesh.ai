"""Validation rules for the fred_macro ingester."""
from __future__ import annotations

from nidp.shared.validation import register
from nidp.shared.validation.rules import (
    CountAtLeastRule, CustomSQLRule, FailureClass, Severity,
)

# At least 6 of 8 expected series should have ≥ 1 row after a run.
COVERAGE_MIN = CustomSQLRule(
    name="fred_macro.series_coverage",
    sql="""
        SELECT count(DISTINCT series_id) < 6 FROM nidp.fred_macro
         WHERE source_run_id = $2
    """,
    message="fewer than 6 distinct FRED series ingested",
    severity=Severity.ERROR,
    failure_class=FailureClass.FIX,
    params_fn=lambda c: [c.target_date, c.job_run_id],
)

# 10Y yield must be present — that's the most-load-bearing series.
TENY_PRESENT = CountAtLeastRule(
    name="fred_macro.us10y_present",
    sql="""
        SELECT count(*) FROM nidp.fred_macro
         WHERE source_run_id = $2 AND series_id = 'DGS10' AND value IS NOT NULL
    """,
    min_count=1,
    severity=Severity.CRITICAL,
    failure_class=FailureClass.BLOCK,
)

register("fred_macro", [
    COVERAGE_MIN,
    TENY_PRESENT,
])
