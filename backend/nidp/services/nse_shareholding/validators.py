"""Validation rules for the nse_shareholding ingester."""
from __future__ import annotations

from nidp.shared.validation import register
from nidp.shared.validation.rules import (
    CustomSQLRule, FailureClass, NoNullsRule, Severity,
)

REQUIRED_FIELDS = NoNullsRule(
    name="nse_shareholding.required_fields",
    table="nidp.shareholding_pattern",
    columns=["symbol", "period_end"],
    severity=Severity.ERROR,
    failure_class=FailureClass.FIX,
)

# Promoter % must be in [0, 100]. Anything outside means the parser
# misread a non-percent fact as a percent.
PROMOTER_PCT_IN_RANGE = CustomSQLRule(
    name="nse_shareholding.promoter_pct_in_range",
    sql="""
        SELECT count(*) FROM nidp.shareholding_pattern
         WHERE source_run_id = $1
           AND promoter_pct IS NOT NULL
           AND (promoter_pct < 0 OR promoter_pct > 100)
    """,
    sample_sql="""
        SELECT symbol, period_end, promoter_pct
          FROM nidp.shareholding_pattern
         WHERE source_run_id = $1
           AND promoter_pct IS NOT NULL
           AND (promoter_pct < 0 OR promoter_pct > 100)
         LIMIT 5
    """,
    message="promoter_pct outside [0,100] — parser tag misread",
    severity=Severity.ERROR,
    failure_class=FailureClass.FIX,
    params_fn=lambda c: [c.job_run_id],
)

# Promoter + Public should sum to ~100 (within ±0.5 tolerance for rounding).
PROMOTER_PUBLIC_SUMS_TO_100 = CustomSQLRule(
    name="nse_shareholding.promoter_public_sums_to_100",
    sql="""
        SELECT count(*) FROM nidp.shareholding_pattern
         WHERE source_run_id = $1
           AND promoter_pct IS NOT NULL
           AND public_pct IS NOT NULL
           AND ABS((promoter_pct + public_pct) - 100) > 0.5
    """,
    sample_sql="""
        SELECT symbol, period_end, promoter_pct, public_pct,
               (promoter_pct + public_pct) AS sum_pct
          FROM nidp.shareholding_pattern
         WHERE source_run_id = $1
           AND promoter_pct IS NOT NULL
           AND public_pct IS NOT NULL
           AND ABS((promoter_pct + public_pct) - 100) > 0.5
         LIMIT 10
    """,
    message="promoter+public ≠ 100 (±0.5pp) — likely category-tag misread",
    severity=Severity.WARN,
    failure_class=FailureClass.FIX,
    params_fn=lambda c: [c.job_run_id],
)

# At least one institutional or promoter percentage must be present —
# otherwise the row is dimensionless and useless for downstream
# scoring. Tracked as WARN.
ROW_HAS_SOME_PCT = CustomSQLRule(
    name="nse_shareholding.row_has_some_pct",
    sql="""
        SELECT count(*) FROM nidp.shareholding_pattern
         WHERE source_run_id = $1
           AND promoter_pct IS NULL
           AND fii_pct      IS NULL
           AND mf_pct       IS NULL
           AND public_pct   IS NULL
    """,
    sample_sql="""
        SELECT symbol, period_end, xbrl_url
          FROM nidp.shareholding_pattern
         WHERE source_run_id = $1
           AND promoter_pct IS NULL
           AND fii_pct      IS NULL
           AND mf_pct       IS NULL
           AND public_pct   IS NULL
         LIMIT 10
    """,
    message="rows landed with no percent facts — taxonomy mismatch likely",
    severity=Severity.WARN,
    failure_class=FailureClass.FIX,
    params_fn=lambda c: [c.job_run_id],
)


register("nse_shareholding", [
    REQUIRED_FIELDS,
    PROMOTER_PCT_IN_RANGE,
    PROMOTER_PUBLIC_SUMS_TO_100,
    ROW_HAS_SOME_PCT,
])
