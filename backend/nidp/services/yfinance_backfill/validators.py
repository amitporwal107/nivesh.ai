"""Validation rules for the yfinance_backfill ingester.

Same target table as bhavcopy — enforce same minimum sanity but
relaxed: yfinance may have null open/high/low for some illiquid
sessions; we only block on close_price being absurd.
"""
from __future__ import annotations

from nidp.shared.validation import register
from nidp.shared.validation.rules import (
    CountAtLeastRule, CustomSQLRule, FailureClass, NoNullsRule, RangeRule, Severity,
)

REQUIRED_FIELDS = NoNullsRule(
    name="yfinance.close_price_present",
    table="nidp.prices_eod",
    columns=["close_price"],
    where="source = 'YFINANCE'",
    severity=Severity.WARN,
    failure_class=FailureClass.INFO,
)

CLOSE_RANGE = RangeRule(
    name="yfinance.close_price_range",
    table="nidp.prices_eod",
    column="close_price",
    lo=0.01,
    hi=200_000.0,
    where="source = 'YFINANCE'",
    severity=Severity.WARN,
    failure_class=FailureClass.INFO,
)

OHLC_CONSISTENT = CustomSQLRule(
    name="yfinance.ohlc_consistent",
    sql="""
        SELECT count(*) FROM nidp.prices_eod
         WHERE source_run_id = $2
           AND source = 'YFINANCE'
           AND high_price IS NOT NULL AND low_price IS NOT NULL
           AND open_price IS NOT NULL AND close_price IS NOT NULL
           AND (low_price > high_price
                OR low_price > open_price
                OR low_price > close_price
                OR high_price < open_price
                OR high_price < close_price)
    """,
    message="yfinance OHLC inconsistency",
    severity=Severity.WARN,
    failure_class=FailureClass.INFO,
)

register("yfinance_backfill", [
    REQUIRED_FIELDS,
    CLOSE_RANGE,
    OHLC_CONSISTENT,
])
