"""Validation rules for mf_holdings.

Holdings rows are SEBI-mandated, so completeness expectations apply
per-scheme (every scheme that *has* a portfolio for the month should
sum to ~100%). Holdings is a heterogeneous source (ten parsers), so
the rules are deliberately lenient — we want a finding when a parser
breaks, not when an AMC published a quirky workbook.
"""
from __future__ import annotations

from nidp.shared.validation import register
from nidp.shared.validation.rules import (
    CustomSQLRule, FailureClass, NoNullsRule, RangeRule, Severity,
)

# 1. Required fields present.
REQUIRED_FIELDS = NoNullsRule(
    name="mf_holdings.required_fields",
    table="nidp.mf_holdings_monthly",
    columns=["scheme_code", "as_of_month", "security_name", "source"],
    severity=Severity.CRITICAL,
    failure_class=FailureClass.BLOCK,
)

# 2. weight_pct ∈ [0, 100] when present.
WEIGHT_RANGE = RangeRule(
    name="mf_holdings.weight_pct_range",
    table="nidp.mf_holdings_monthly",
    column="weight_pct",
    lo=0.0,
    hi=100.0,
    severity=Severity.ERROR,
    failure_class=FailureClass.FIX,
)

# 3. Per-scheme weight sum sanity. If a scheme published a portfolio
# this month, the weights should sum to ~100% (±5% tolerance for cash
# / derivatives / FX rounding). Schemes whose adapters didn't write
# weight_pct (NULL) are excluded from the check.
WEIGHT_SUM = CustomSQLRule(
    name="mf_holdings.scheme_weight_sum",
    sql="""
        SELECT count(*) FROM (
            SELECT scheme_code, as_of_month, sum(weight_pct) AS s
              FROM nidp.mf_holdings_monthly
             WHERE source_run_id = $2
               AND weight_pct IS NOT NULL
             GROUP BY scheme_code, as_of_month
            HAVING abs(sum(weight_pct) - 100.0) > 5.0
        ) bad
    """,
    sample_sql="""
        SELECT scheme_code, as_of_month, round(sum(weight_pct)::numeric, 2) AS total
          FROM nidp.mf_holdings_monthly
         WHERE source_run_id = $2
           AND weight_pct IS NOT NULL
         GROUP BY scheme_code, as_of_month
        HAVING abs(sum(weight_pct) - 100.0) > 5.0
         LIMIT 5
    """,
    message="scheme weights don't sum to ~100% — likely parser drop or AMC schema change",
    severity=Severity.ERROR,
    failure_class=FailureClass.FIX,
)

register("mf_holdings", [
    REQUIRED_FIELDS,
    WEIGHT_RANGE,
    WEIGHT_SUM,
])
