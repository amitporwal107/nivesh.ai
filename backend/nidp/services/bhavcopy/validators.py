"""Validation rules for the bhavcopy ingester.

NSE EOD bhavcopy is the most load-bearing daily file in NIDP — almost
every signal depends on its prices being right. Rules are graded:

  CRITICAL/BLOCK   — partial / corrupt feed; refuse to use downstream
  ERROR/FIX        — needs human attention but doesn't block snapshot
  WARN/INFO        — surface in Grafana, no action

Numeric thresholds reflect what NSE actually publishes (~2,000-2,200
EQ rows per session). Adjust via review.
"""
from __future__ import annotations

from nidp.shared.validation import register
from nidp.shared.validation.rules import (
    CountAtLeastRule, CustomSQLRule, FailureClass, NoNullsRule, RangeRule, Severity,
)

# 1. Row count — bhavcopy below ~1500 rows means partial fetch.
ROW_COUNT_MIN = CountAtLeastRule(
    name="bhavcopy.row_count_min",
    sql="""
        SELECT count(*) FROM nidp.prices_eod
         WHERE as_of_date = $1::date
           AND source_run_id = $2
           AND series IN ('EQ','BE','BZ','SM')
    """,
    min_count=1500,
    severity=Severity.CRITICAL,
    failure_class=FailureClass.BLOCK,
)

# 2. Required-field completeness on persisted rows
REQUIRED_FIELDS = NoNullsRule(
    name="bhavcopy.required_fields_present",
    table="nidp.prices_eod",
    columns=["close_price", "open_price", "high_price", "low_price"],
    severity=Severity.ERROR,
    failure_class=FailureClass.FIX,
)

# 3. Price sanity — 0 < price < 200,000 (covers MRF-class outliers)
PRICE_RANGE = RangeRule(
    name="bhavcopy.close_price_range",
    table="nidp.prices_eod",
    column="close_price",
    lo=0.01,
    hi=200_000.0,
    severity=Severity.ERROR,
    failure_class=FailureClass.FIX,
)

# 4. OHLC consistency: low <= open,close <= high
OHLC_CONSISTENT = CustomSQLRule(
    name="bhavcopy.ohlc_consistent",
    sql="""
        SELECT count(*) FROM nidp.prices_eod
         WHERE source_run_id = $2
           AND as_of_date = $1::date
           AND (low_price > open_price
                OR low_price > close_price
                OR high_price < open_price
                OR high_price < close_price)
    """,
    sample_sql="""
        SELECT symbol, series, open_price, high_price, low_price, close_price
          FROM nidp.prices_eod
         WHERE source_run_id = $2
           AND as_of_date = $1::date
           AND (low_price > open_price
                OR low_price > close_price
                OR high_price < open_price
                OR high_price < close_price)
         LIMIT 5
    """,
    message="OHLC inconsistency detected: low > open/close OR high < open/close",
    severity=Severity.ERROR,
    failure_class=FailureClass.FIX,
)

# 5. Symbol uniqueness within the run (PK already enforces this; this
# catches *parser* duplicates before insert would have failed).
SYMBOL_UNIQUE = CustomSQLRule(
    name="bhavcopy.symbol_series_unique",
    sql="""
        SELECT count(*) FROM (
            SELECT symbol, series, count(*) AS n
              FROM nidp.prices_eod
             WHERE source_run_id = $2 AND as_of_date = $1::date
             GROUP BY symbol, series
            HAVING count(*) > 1
        ) dup
    """,
    message="duplicate (symbol, series) rows in bhavcopy",
    severity=Severity.CRITICAL,
    failure_class=FailureClass.BLOCK,
)

register("bhavcopy", [
    ROW_COUNT_MIN,
    REQUIRED_FIELDS,
    PRICE_RANGE,
    OHLC_CONSISTENT,
    SYMBOL_UNIQUE,
])
