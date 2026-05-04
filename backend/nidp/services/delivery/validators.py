"""Validation rules for the delivery (sec_bhavdata_full) ingester."""
from __future__ import annotations

from nidp.shared.validation import register
from nidp.shared.validation.rules import (
    CountAtLeastRule, CustomSQLRule, FailureClass, RangeRule, Severity,
)

ROW_COUNT_MIN = CountAtLeastRule(
    name="delivery.row_count_min",
    sql="""
        SELECT count(*) FROM nidp.delivery_data
         WHERE as_of_date = $1::date AND source_run_id = $2
    """,
    min_count=1500,
    severity=Severity.CRITICAL,
    failure_class=FailureClass.BLOCK,
)

# Delivery % must be in [0, 100] — outside is a parse error.
DELIV_PCT_RANGE = RangeRule(
    name="delivery.deliv_pct_range",
    table="nidp.delivery_data",
    column="deliverable_pct",
    lo=0.0,
    hi=100.0,
    severity=Severity.ERROR,
    failure_class=FailureClass.FIX,
)

# deliverable_qty <= traded_qty by definition.
DELIV_LE_TRADED = CustomSQLRule(
    name="delivery.deliverable_le_traded",
    sql="""
        SELECT count(*) FROM nidp.delivery_data
         WHERE source_run_id = $2 AND as_of_date = $1::date
           AND deliverable_qty IS NOT NULL AND traded_qty IS NOT NULL
           AND deliverable_qty > traded_qty
    """,
    sample_sql="""
        SELECT symbol, series, traded_qty, deliverable_qty, deliverable_pct
          FROM nidp.delivery_data
         WHERE source_run_id = $2 AND as_of_date = $1::date
           AND deliverable_qty > traded_qty
         LIMIT 5
    """,
    message="deliverable_qty > traded_qty (impossible)",
    severity=Severity.ERROR,
    failure_class=FailureClass.FIX,
)

# Cross-source: every (symbol, series, date) in delivery should also
# exist in prices_eod for the same date. A gap signals out-of-sync feeds.
CROSS_PRICES_PRESENT = CustomSQLRule(
    name="delivery.cross_check_prices_eod_present",
    sql="""
        SELECT count(*) FROM nidp.delivery_data d
         WHERE d.source_run_id = $2 AND d.as_of_date = $1::date
           AND NOT EXISTS (
                SELECT 1 FROM nidp.prices_eod p
                 WHERE p.as_of_date = d.as_of_date
                   AND p.symbol = d.symbol
                   AND p.series = d.series
                   AND p.source = 'NSE_BHAVCOPY'
           )
    """,
    sample_sql="""
        SELECT d.symbol, d.series
          FROM nidp.delivery_data d
         WHERE d.source_run_id = $2 AND d.as_of_date = $1::date
           AND NOT EXISTS (
                SELECT 1 FROM nidp.prices_eod p
                 WHERE p.as_of_date = d.as_of_date
                   AND p.symbol = d.symbol
                   AND p.series = d.series
                   AND p.source = 'NSE_BHAVCOPY'
           )
         LIMIT 5
    """,
    message="delivery rows without matching bhavcopy entry",
    severity=Severity.WARN,
    failure_class=FailureClass.FIX,
)

register("delivery", [
    ROW_COUNT_MIN,
    DELIV_PCT_RANGE,
    DELIV_LE_TRADED,
    CROSS_PRICES_PRESENT,
])
