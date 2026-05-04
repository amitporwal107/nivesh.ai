"""Validation rules for the FII/DII flows ingester."""
from __future__ import annotations

from nidp.shared.validation import register
from nidp.shared.validation.rules import (
    CountAtLeastRule, CustomSQLRule, FailureClass, NoNullsRule, Severity,
)

# At minimum, FII + DII cash rows must exist for the date.
FII_DII_CASH_PRESENT = CustomSQLRule(
    name="fii_dii.cash_rows_present",
    sql="""
        WITH have AS (
            SELECT category FROM nidp.fii_dii_flows
             WHERE source_run_id = $2 AND as_of_date = $1::date
               AND segment = 'EQUITY_CASH'
               AND category IN ('FII','DII')
             GROUP BY category
        )
        SELECT (SELECT count(*) FROM have) < 2
    """,
    message="FII/DII cash rows missing for this date",
    severity=Severity.CRITICAL,
    failure_class=FailureClass.BLOCK,
)

# Net consistency: |net - (buy - sell)| should be tiny (rounding only).
NET_BUY_MINUS_SELL = CustomSQLRule(
    name="fii_dii.net_equals_buy_minus_sell",
    sql="""
        SELECT count(*) FROM nidp.fii_dii_flows
         WHERE source_run_id = $2 AND as_of_date = $1::date
           AND buy_value_cr IS NOT NULL AND sell_value_cr IS NOT NULL
           AND net_value_cr IS NOT NULL
           AND abs(net_value_cr - (buy_value_cr - sell_value_cr)) > 1.0
    """,
    sample_sql="""
        SELECT category, segment, buy_value_cr, sell_value_cr, net_value_cr,
               (buy_value_cr - sell_value_cr) AS computed_net
          FROM nidp.fii_dii_flows
         WHERE source_run_id = $2 AND as_of_date = $1::date
           AND abs(net_value_cr - (buy_value_cr - sell_value_cr)) > 1.0
         LIMIT 5
    """,
    message="net_value != buy - sell (>₹1cr drift)",
    severity=Severity.ERROR,
    failure_class=FailureClass.FIX,
)

# At least one row should land — empty workbook is a parse failure.
ANY_ROW_PRESENT = CountAtLeastRule(
    name="fii_dii.any_row_present",
    sql="""
        SELECT count(*) FROM nidp.fii_dii_flows
         WHERE source_run_id = $2 AND as_of_date = $1::date
    """,
    min_count=1,
    severity=Severity.CRITICAL,
    failure_class=FailureClass.BLOCK,
)

register("fii_dii", [
    ANY_ROW_PRESENT,
    FII_DII_CASH_PRESENT,
    NET_BUY_MINUS_SELL,
])
