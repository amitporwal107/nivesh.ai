"""Validation rules for the corporate-actions ingester."""
from __future__ import annotations

from nidp.shared.validation import register
from nidp.shared.validation.rules import (
    CustomSQLRule, FailureClass, NoNullsRule, Severity,
)

REQUIRED_FIELDS = NoNullsRule(
    name="corporate_actions.required_fields",
    table="nidp.corporate_actions",
    columns=["symbol", "action_type", "ex_date"],
    severity=Severity.ERROR,
    failure_class=FailureClass.FIX,
)

# Splits must have face_value_pre/post; bonuses must have ratio;
# dividends must have dividend_amount. Missing structured fields
# means the regex classifier missed something — surface for manual review.
SPLIT_HAS_FACE_VALUES = CustomSQLRule(
    name="corporate_actions.split_has_face_values",
    sql="""
        SELECT count(*) FROM nidp.corporate_actions
         WHERE source_run_id = $2
           AND action_type = 'SPLIT'
           AND (face_value_pre IS NULL OR face_value_post IS NULL)
    """,
    sample_sql="""
        SELECT symbol, action_type, purpose
          FROM nidp.corporate_actions
         WHERE source_run_id = $2
           AND action_type = 'SPLIT'
           AND (face_value_pre IS NULL OR face_value_post IS NULL)
         LIMIT 5
    """,
    message="SPLIT rows missing face_value_pre/post — classifier may need a regex update",
    severity=Severity.WARN,
    failure_class=FailureClass.FIX,
    params_fn=lambda c: [c.target_date, c.job_run_id],
)

BONUS_HAS_RATIO = CustomSQLRule(
    name="corporate_actions.bonus_has_ratio",
    sql="""
        SELECT count(*) FROM nidp.corporate_actions
         WHERE source_run_id = $2 AND action_type = 'BONUS' AND ratio IS NULL
    """,
    sample_sql="""
        SELECT symbol, purpose FROM nidp.corporate_actions
         WHERE source_run_id = $2 AND action_type = 'BONUS' AND ratio IS NULL
         LIMIT 5
    """,
    message="BONUS rows missing ratio — classifier may need a regex update",
    severity=Severity.WARN,
    failure_class=FailureClass.FIX,
    params_fn=lambda c: [c.target_date, c.job_run_id],
)

DIVIDEND_HAS_AMOUNT = CustomSQLRule(
    name="corporate_actions.dividend_has_amount",
    sql="""
        SELECT count(*) FROM nidp.corporate_actions
         WHERE source_run_id = $2
           AND action_type = 'DIVIDEND' AND dividend_amount IS NULL
    """,
    sample_sql="""
        SELECT symbol, purpose FROM nidp.corporate_actions
         WHERE source_run_id = $2
           AND action_type = 'DIVIDEND' AND dividend_amount IS NULL
         LIMIT 5
    """,
    message="DIVIDEND rows missing amount — classifier may need a regex update",
    severity=Severity.WARN,
    failure_class=FailureClass.FIX,
    params_fn=lambda c: [c.target_date, c.job_run_id],
)

# OTHER rows are allowed but should be a small minority. Track ratio.
OTHER_RATIO_NOT_DOMINANT = CustomSQLRule(
    name="corporate_actions.other_ratio_not_dominant",
    sql="""
        WITH counts AS (
            SELECT
                count(*) FILTER (WHERE action_type = 'OTHER') AS other_n,
                count(*) AS total_n
              FROM nidp.corporate_actions
             WHERE source_run_id = $2
        )
        SELECT (total_n > 0 AND other_n::float / total_n > 0.30)
          FROM counts
    """,
    message="more than 30% of CA rows landed as OTHER — classifier likely broken",
    severity=Severity.ERROR,
    failure_class=FailureClass.FIX,
    params_fn=lambda c: [c.target_date, c.job_run_id],
)

register("corporate_actions", [
    REQUIRED_FIELDS,
    SPLIT_HAS_FACE_VALUES,
    BONUS_HAS_RATIO,
    DIVIDEND_HAS_AMOUNT,
    OTHER_RATIO_NOT_DOMINANT,
])
