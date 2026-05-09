"""Validation rules for amfi_nav.

NAVAll is the foundation of every MF analytics output. A short file or
stale dates corrupts everything downstream, so the bar is high.

Thresholds reflect what AMFI actually publishes (~10k schemes; some
holidays drop to ~9k as some AMCs skip declaring).
"""
from __future__ import annotations

from nidp.shared.validation import register
from nidp.shared.validation.rules import (
    CountAtLeastRule, CustomSQLRule, FailureClass, NoNullsRule, RangeRule, Severity,
)

# 1. Row count — fewer than 8000 NAV rows ≈ partial fetch.
# Production: NAVAll publishes ~14k schemes; ~8.5k have a NAV dated
# the current trading day, and we drop NAV=0 rows in the parser. So
# any healthy run lands well above 8000 inserts.
ROW_COUNT_MIN = CountAtLeastRule(
    name="amfi_nav.row_count_min",
    sql="""
        SELECT count(*) FROM nidp.mf_nav_daily
         WHERE source_run_id = $2
           AND $1::date IS NOT NULL
    """,
    min_count=8000,
    severity=Severity.CRITICAL,
    failure_class=FailureClass.BLOCK,
)

# 2. NAV must be present + numeric on every persisted row.
NAV_PRESENT = NoNullsRule(
    name="amfi_nav.nav_present",
    table="nidp.mf_nav_daily",
    columns=["nav"],
    severity=Severity.ERROR,
    failure_class=FailureClass.FIX,
)

# 3. NAV sanity — must be > 0 (parser already filters NAV=0) and <= 5M.
# IL&FS Infrastructure Debt Fund Series carry unit values up to ~₹2.5M
# from decade-long compounding without dividend payouts, so cap loose
# to flag truly broken parses (e.g. column shift) rather than legit highs.
NAV_RANGE = RangeRule(
    name="amfi_nav.nav_range",
    table="nidp.mf_nav_daily",
    column="nav",
    lo=0.0001,
    hi=5_000_000.0,
    severity=Severity.ERROR,
    failure_class=FailureClass.FIX,
)

# 4. nav_date freshness — NAVAll bundles every scheme ever, including
# ~5,500 stale rows from wound-up schemes that haven't declared NAV
# in years. A fraction-based check fires false positives every day.
# Instead: assert an absolute floor of *fresh* rows (within 3 days of
# the run target). Production lands ~8,500 fresh rows/day; 6,000 is
# a comfortable floor that catches real fetch breakage.
FRESH_ROW_FLOOR = CustomSQLRule(
    name="amfi_nav.fresh_row_floor",
    sql="""
        SELECT CASE WHEN fresh < 6000 THEN 1 ELSE 0 END
          FROM (
            SELECT count(*) AS fresh
              FROM nidp.mf_nav_daily
             WHERE source_run_id = $2
               AND nav_date >= $1::date - INTERVAL '3 days'
          ) t
    """,
    message="< 6000 NAV rows dated within 3 days of run target — likely stale or partial fetch",
    severity=Severity.ERROR,
    failure_class=FailureClass.FIX,
)

# 5. Scheme-master coverage — every NAV row should have a matching
# scheme_master entry produced by the same run.
SCHEME_MASTER_COVERAGE = CustomSQLRule(
    name="amfi_nav.scheme_master_coverage",
    sql="""
        SELECT count(*)
          FROM nidp.mf_nav_daily n
          LEFT JOIN nidp.mf_scheme_master m USING (scheme_code)
         WHERE n.source_run_id = $1
           AND m.scheme_code IS NULL
    """,
    sample_sql="""
        SELECT n.scheme_code
          FROM nidp.mf_nav_daily n
          LEFT JOIN nidp.mf_scheme_master m USING (scheme_code)
         WHERE n.source_run_id = $1
           AND m.scheme_code IS NULL
         LIMIT 5
    """,
    message="NAV rows present without matching scheme_master entry",
    severity=Severity.ERROR,
    failure_class=FailureClass.FIX,
    params_fn=lambda c: [c.job_run_id],
)

register("amfi_nav", [
    ROW_COUNT_MIN,
    NAV_PRESENT,
    NAV_RANGE,
    FRESH_ROW_FLOOR,
    SCHEME_MASTER_COVERAGE,
])
