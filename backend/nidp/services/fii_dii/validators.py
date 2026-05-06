"""Validation rules for the FII/DII flows ingester.

NSE moved FII/DII to a rolling JSON API — entries carry their own
date in the response, and the ingester runs without a fixed
target_date. So validators must filter strictly by source_run_id;
filtering by `as_of_date = target_date::date` would compare against
NULL and match nothing, BLOCKing every healthy run.

Cash-only: the new endpoint exposes only EQUITY_CASH (no F&O segments
like INDEX_FUTURES, STOCK_OPTIONS, etc. that the legacy XLS carried).
We assert FII + DII cash rows are present; we don't expect F&O.
"""
from __future__ import annotations

from nidp.shared.validation import register
from nidp.shared.validation.rules import (
    CustomSQLRule, FailureClass, Severity,
)

# At least one row landed for this run — empty response is a parse
# failure (the JSON shape changed or the API blocked us).
ANY_ROW_PRESENT = CustomSQLRule(
    name="fii_dii.any_row_present",
    sql="""
        SELECT (count(*) = 0)::int
          FROM nidp.fii_dii_flows
         WHERE source_run_id = $1
    """,
    message="no FII/DII rows landed for this run",
    severity=Severity.CRITICAL,
    failure_class=FailureClass.BLOCK,
    params_fn=lambda c: [c.job_run_id],
)

# Both FII and DII cash rows must be present — anything less means the
# response was incomplete or the parser didn't classify a category.
FII_DII_CASH_PRESENT = CustomSQLRule(
    name="fii_dii.cash_rows_present",
    sql="""
        WITH have AS (
            SELECT category FROM nidp.fii_dii_flows
             WHERE source_run_id = $1
               AND segment = 'EQUITY_CASH'
               AND category IN ('FII','DII')
             GROUP BY category
        )
        SELECT (SELECT count(*) FROM have) < 2
    """,
    message="FII/DII EQUITY_CASH rows incomplete (need both categories)",
    severity=Severity.CRITICAL,
    failure_class=FailureClass.BLOCK,
    params_fn=lambda c: [c.job_run_id],
)

# Net consistency: |net - (buy - sell)| should be tiny (rounding only).
NET_BUY_MINUS_SELL = CustomSQLRule(
    name="fii_dii.net_equals_buy_minus_sell",
    sql="""
        SELECT count(*) FROM nidp.fii_dii_flows
         WHERE source_run_id = $1
           AND buy_value_cr IS NOT NULL AND sell_value_cr IS NOT NULL
           AND net_value_cr IS NOT NULL
           AND abs(net_value_cr - (buy_value_cr - sell_value_cr)) > 1.0
    """,
    sample_sql="""
        SELECT as_of_date, category, segment,
               buy_value_cr, sell_value_cr, net_value_cr,
               (buy_value_cr - sell_value_cr) AS computed_net
          FROM nidp.fii_dii_flows
         WHERE source_run_id = $1
           AND abs(net_value_cr - (buy_value_cr - sell_value_cr)) > 1.0
         LIMIT 5
    """,
    message="net_value != buy - sell (>₹1cr drift)",
    severity=Severity.ERROR,
    failure_class=FailureClass.FIX,
    params_fn=lambda c: [c.job_run_id],
)

register("fii_dii", [
    ANY_ROW_PRESENT,
    FII_DII_CASH_PRESENT,
    NET_BUY_MINUS_SELL,
])
