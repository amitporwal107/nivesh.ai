"""Validation rules for the index-close ingester."""
from __future__ import annotations

from nidp.shared.validation import register
from nidp.shared.validation.rules import (
    CountAtLeastRule, CustomSQLRule, FailureClass, RangeRule, Severity,
)

ROW_COUNT_MIN = CountAtLeastRule(
    name="index_close.row_count_min",
    sql="""
        SELECT count(*) FROM nidp.index_eod
         WHERE source_run_id = $2 AND as_of_date = $1::date
    """,
    min_count=20,
    severity=Severity.ERROR,
    failure_class=FailureClass.FIX,
)

# Nifty 50 must land — that's the headline; missing it = bad day.
NIFTY50_PRESENT = CustomSQLRule(
    name="index_close.nifty50_present",
    sql="""
        SELECT NOT EXISTS (
            SELECT 1 FROM nidp.index_eod
             WHERE source_run_id = $2 AND as_of_date = $1::date
               AND index_name ILIKE 'Nifty 50%'
        )
    """,
    message="Nifty 50 row missing from ind_close_all",
    severity=Severity.CRITICAL,
    failure_class=FailureClass.BLOCK,
)

PCT_CHANGE_RANGE = RangeRule(
    name="index_close.pct_change_in_range",
    table="nidp.index_eod",
    column="pct_change",
    lo=-25.0,
    hi=25.0,
    severity=Severity.WARN,
    failure_class=FailureClass.INFO,
)

register("index_close", [
    ROW_COUNT_MIN,
    NIFTY50_PRESENT,
    PCT_CHANGE_RANGE,
])
