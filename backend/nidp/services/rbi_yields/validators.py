"""Validation rules for the RBI yields ingester."""
from __future__ import annotations

from nidp.shared.validation import register
from nidp.shared.validation.rules import (
    CountAtLeastRule, FailureClass, NoNullsRule, RangeRule, Severity,
)

# At least the 10Y must land — that's the field the regime engine
# depends on most. Anything else is a bonus.
TENY_PRESENT = CountAtLeastRule(
    name="rbi_yields.10y_present",
    # CountAtLeastRule.check() always binds (target_date, job_run_id) as
    # ($1, $2). For rolling ingesters target_date is NULL, but asyncpg
    # still requires every parameter to be referenced so it can type-
    # infer; the trailing `($1::date IS NULL OR ...)` tautology fulfills
    # that without filtering rows.
    sql="""
        SELECT count(*) FROM nidp.rbi_yields
         WHERE source_run_id = $2 AND tenor = '10Y'
           AND ($1::date IS NULL OR $1::date IS NOT NULL)
    """,
    min_count=1,
    severity=Severity.CRITICAL,
    failure_class=FailureClass.BLOCK,
)

REQUIRED_FIELDS = NoNullsRule(
    name="rbi_yields.required_fields",
    table="nidp.rbi_yields",
    columns=["yield_pct"],
    severity=Severity.ERROR,
    failure_class=FailureClass.FIX,
)

# India yields have stayed in [1%, 15%] for decades. Anything else is
# almost certainly a parse error.
YIELD_SANE = RangeRule(
    name="rbi_yields.yield_in_sane_range",
    table="nidp.rbi_yields",
    column="yield_pct",
    lo=0.5,
    hi=20.0,
    severity=Severity.ERROR,
    failure_class=FailureClass.FIX,
)

register("rbi_yields", [
    TENY_PRESENT,
    REQUIRED_FIELDS,
    YIELD_SANE,
])
