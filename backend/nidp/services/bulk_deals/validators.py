"""Validation rules for the bulk-deals ingester."""
from __future__ import annotations

from nidp.shared.validation import register
from nidp.shared.validation.rules import (
    CustomSQLRule, FailureClass, NoNullsRule, RangeRule, Severity,
)

REQUIRED_FIELDS = NoNullsRule(
    name="bulk_deals.required_fields",
    table="nidp.bulk_deals",
    columns=["symbol", "client_name", "deal_type", "quantity", "avg_price"],
    severity=Severity.ERROR,
    failure_class=FailureClass.FIX,
)

QTY_POSITIVE = CustomSQLRule(
    name="bulk_deals.quantity_positive",
    sql="""
        SELECT count(*) FROM nidp.bulk_deals
         WHERE source_run_id = $1 AND quantity <= 0
    """,
    sample_sql="""
        SELECT symbol, client_name, deal_type, quantity FROM nidp.bulk_deals
         WHERE source_run_id = $1 AND quantity <= 0 LIMIT 5
    """,
    message="bulk-deal rows with non-positive quantity",
    severity=Severity.ERROR,
    failure_class=FailureClass.FIX,
    params_fn=lambda c: [c.job_run_id],
)

PRICE_RANGE = RangeRule(
    name="bulk_deals.price_range",
    table="nidp.bulk_deals",
    column="avg_price",
    lo=0.01,
    hi=200_000.0,
)

DEAL_TYPE_VALID = CustomSQLRule(
    name="bulk_deals.deal_type_valid",
    sql="""
        SELECT count(*) FROM nidp.bulk_deals
         WHERE source_run_id = $1 AND deal_type NOT IN ('BUY','SELL')
    """,
    message="bulk-deal rows with deal_type outside {BUY,SELL}",
    severity=Severity.ERROR,
    failure_class=FailureClass.FIX,
    params_fn=lambda c: [c.job_run_id],
)

register("bulk_deals", [
    REQUIRED_FIELDS,
    QTY_POSITIVE,
    PRICE_RANGE,
    DEAL_TYPE_VALID,
])
