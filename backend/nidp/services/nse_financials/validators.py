"""Validation rules for the nse_financials ingester."""
from __future__ import annotations

from nidp.shared.validation import register
from nidp.shared.validation.rules import (
    CustomSQLRule, FailureClass, NoNullsRule, Severity,
)

# Required identifiers — drop the run if these are missing.
REQUIRED_FIELDS = NoNullsRule(
    name="nse_financials.required_fields",
    table="nidp.nse_financials_quarterly",
    columns=["symbol", "period_end", "period_type"],
    severity=Severity.ERROR,
    failure_class=FailureClass.FIX,
)

# Sanity bound on EPS — Indian listed cos almost never report
# |EPS| > 5000 ₹/share even for ultra-high-priced names. A bigger
# value almost certainly means a scaling bug (decimals attribute
# misread, lakhs vs crores confusion).
EPS_IN_RANGE = CustomSQLRule(
    name="nse_financials.eps_in_range",
    sql="""
        SELECT count(*) FROM nidp.nse_financials_quarterly
         WHERE source_run_id = $1
           AND eps_basic IS NOT NULL
           AND ABS(eps_basic) > 5000
    """,
    sample_sql="""
        SELECT symbol, period_end, eps_basic
          FROM nidp.nse_financials_quarterly
         WHERE source_run_id = $1
           AND eps_basic IS NOT NULL
           AND ABS(eps_basic) > 5000
         LIMIT 5
    """,
    message="EPS outside sane range (|eps| > 5000) — likely a scaling bug",
    severity=Severity.ERROR,
    failure_class=FailureClass.FIX,
    params_fn=lambda c: [c.job_run_id],
)

# Sanity bound on revenue — > ₹10 lakh crore in a single quarter is
# implausible for any single Indian listed entity. RIL Q4 is currently
# ~₹2.4 lakh cr; flag anything > ~5x that.
REVENUE_IN_RANGE = CustomSQLRule(
    name="nse_financials.revenue_in_range",
    sql="""
        SELECT count(*) FROM nidp.nse_financials_quarterly
         WHERE source_run_id = $1
           AND revenue_from_ops_cr IS NOT NULL
           AND revenue_from_ops_cr > 1000000
    """,
    sample_sql="""
        SELECT symbol, period_end, revenue_from_ops_cr
          FROM nidp.nse_financials_quarterly
         WHERE source_run_id = $1
           AND revenue_from_ops_cr IS NOT NULL
           AND revenue_from_ops_cr > 1000000
         LIMIT 5
    """,
    message="revenue > ₹10 lakh cr in one period — likely scaling bug (raw vs crores)",
    severity=Severity.ERROR,
    failure_class=FailureClass.FIX,
    params_fn=lambda c: [c.job_run_id],
)

# Coverage check — at least 1 numeric field populated per row.
# Filings with no extracted facts mean the parser missed all tags
# (taxonomy drift). Tracked as WARN, not BLOCK, because partial
# parses are still useful (we can backfill later).
ROW_HAS_SOME_FACTS = CustomSQLRule(
    name="nse_financials.row_has_some_facts",
    sql="""
        SELECT count(*) FROM nidp.nse_financials_quarterly
         WHERE source_run_id = $1
           AND revenue_from_ops_cr IS NULL
           AND pat_cr            IS NULL
           AND eps_basic         IS NULL
           AND interest_earned_cr IS NULL
    """,
    sample_sql="""
        SELECT symbol, period_end, xbrl_url
          FROM nidp.nse_financials_quarterly
         WHERE source_run_id = $1
           AND revenue_from_ops_cr IS NULL
           AND pat_cr            IS NULL
           AND eps_basic         IS NULL
           AND interest_earned_cr IS NULL
         LIMIT 10
    """,
    message="rows landed with zero extracted facts — taxonomy mismatch likely",
    severity=Severity.WARN,
    failure_class=FailureClass.FIX,
    params_fn=lambda c: [c.job_run_id],
)


register("nse_financials", [
    REQUIRED_FIELDS,
    EPS_IN_RANGE,
    REVENUE_IN_RANGE,
    ROW_HAS_SOME_FACTS,
])
