"""Predicate-builder tests for the screener SQL builder.

This is the security boundary: every column reaching SQL must come from the
registry whitelist, and every caller value must be a bound parameter. It is also
where B2/B3/B4 are assertable without a database.

No DB, no network, no FastAPI — `screen_query` is deliberately pure so the
code that decides what reaches the database can be proven safe on its own.
"""
from __future__ import annotations

import pytest

from nidp.services.daas_api import metric_registry as reg
from nidp.services.daas_api.screen_query import (
    ScreenQueryError, predicate as _predicate, where as _where,
)


def _build(f):
    params: list = []
    sql = _predicate(f, params)
    return sql, params


# ── whitelist / injection ───────────────────────────────────────────────────

def test_unknown_metric_is_refused():
    with pytest.raises(ScreenQueryError, match="unknown metric"):
        _build({"key": "made_up_metric", "op": "gte", "value": 1})


@pytest.mark.parametrize("attack", [
    "roe_pct; DROP TABLE nidp.stock_features_daily",
    "roe_pct') OR 1=1 --",
    'roe_pct" FROM nidp.stock_features_daily; --',
])
def test_injection_via_key_is_refused(attack):
    """Keys are looked up in the registry, never interpolated."""
    with pytest.raises(ScreenQueryError, match="unknown metric"):
        _build({"key": attack, "op": "gte", "value": 1})


def test_caller_values_are_always_bound_parameters():
    sql, params = _build({"key": "roe_pct", "op": "gte", "value": 18})
    assert "18" not in sql, "value must not be inlined into SQL text"
    assert sql == 'f."roe_pct" >= $1::numeric'
    assert params == [18.0]


def test_text_injection_via_in_values_is_parameterised():
    sql, params = _build({"key": "sector", "op": "in",
                          "values": ["IT'; DROP TABLE x; --", "Pharma"]})
    assert "DROP" not in sql
    assert params == [["IT'; DROP TABLE X; --", "PHARMA"]]


# ── operators (B3) ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("op,sql_op", [
    ("gte", ">="), ("lte", "<="), ("gt", ">"), ("lt", "<"), ("eq", "="),
])
def test_numeric_operators(op, sql_op):
    sql, params = _build({"key": "roe_pct", "op": op, "value": 12.5})
    assert sql == f'f."roe_pct" {sql_op} $1::numeric'
    assert params == [12.5]


def test_between_is_inclusive_and_ordered():
    sql, params = _build({"key": "market_cap_cr", "op": "between", "min": 1000, "max": 10000})
    assert sql == 'f."market_cap_cr" BETWEEN $1::numeric AND $2::numeric'
    assert params == [1000.0, 10000.0]


def test_between_rejects_inverted_bounds():
    with pytest.raises(ScreenQueryError, match="min > max"):
        _build({"key": "market_cap_cr", "op": "between", "min": 10000, "max": 1000})


def test_in_on_text_is_exact_set_membership_not_contains():
    """The legacy endpoint matches sector with ILIKE '%..%', so "Pharma" also
    matches "Pharmaceuticals & Biotech" — a filter that quietly returns more
    than the user asked for."""
    sql, params = _build({"key": "sector", "op": "in", "values": ["Pharma", "IT"]})
    assert "ILIKE" not in sql and "%" not in sql
    assert sql == "UPPER(f.\"sector\") = ANY($1::text[])"
    assert params == [["PHARMA", "IT"]]


def test_in_requires_non_empty_values():
    with pytest.raises(ScreenQueryError, match="non-empty"):
        _build({"key": "sector", "op": "in", "values": []})


def test_unsupported_op_is_refused():
    with pytest.raises(ScreenQueryError, match="unsupported op"):
        _build({"key": "roe_pct", "op": "regex", "value": ".*"})


def test_missing_value_is_refused():
    with pytest.raises(ScreenQueryError, match="needs a `value`"):
        _build({"key": "roe_pct", "op": "gte"})


def test_text_metric_rejects_ordering_operators():
    with pytest.raises(ScreenQueryError, match="text metric"):
        _build({"key": "sector", "op": "gte", "value": 5})


# ── NULL semantics (B4) ─────────────────────────────────────────────────────

def test_null_rows_are_excluded_by_sql_comparison_semantics():
    """A `>` predicate in SQL is UNKNOWN for NULL, so those rows drop out — they
    are never coerced to 0 (which would wrongly match `< 5`) or to infinity."""
    sql, _ = _build({"key": "roe_pct", "op": "gte", "value": 18})
    assert "COALESCE" not in sql.upper(), "must not substitute a value for NULL"
    assert "IS NULL" not in sql.upper(), "must not explicitly admit NULL rows"


# ── multi-filter composition ────────────────────────────────────────────────

def test_where_is_conjunctive_and_numbers_params_across_filters():
    where, params = _where(
        [{"key": "roe_pct", "op": "gte", "value": 18},
         {"key": "debt_to_equity", "op": "lte", "value": 0.5}],
        "2026-08-17")
    assert where == ('f.as_of_date = $1 AND f."roe_pct" >= $2::numeric '
                     'AND f."debt_to_equity" <= $3::numeric')
    assert params == ["2026-08-17", 18.0, 0.5]


def test_where_with_no_filters_is_just_the_as_of_date():
    where, params = _where([], "2026-08-17")
    assert where == "f.as_of_date = $1"
    assert params == ["2026-08-17"]


# ── registry invariants ─────────────────────────────────────────────────────

def test_every_registry_column_is_a_bare_identifier():
    """A column name with quoting or whitespace would break out of the quoted
    identifier the predicate builder emits."""
    for m in reg._METRICS:
        assert m.column.replace("_", "").isalnum(), m.column


def test_hard_blocked_metrics_are_never_offered_whatever_coverage_says():
    """pb reads as 7.5% covered; every value is 0.00. Coverage alone would offer it."""
    pb = reg.BY_KEY["pb"]
    assert reg.is_offered(pb, {"covered_pct": 99.0, "distinct_non_null": 500}) is False
    assert "0.00" in reg.hidden_reason(pb, {"covered_pct": 7.5, "distinct_non_null": 1})


def test_degenerate_metric_is_not_offered():
    m = reg.BY_KEY["roe_pct"]
    assert reg.is_offered(m, {"covered_pct": 80.0, "distinct_non_null": 1}) is False


def test_thin_but_real_metric_is_offered():
    m = reg.BY_KEY["roe_pct"]           # min_coverage_pct = 5.0; measured 7.2%
    assert reg.is_offered(m, {"covered_pct": 7.2, "distinct_non_null": 170}) is True


def test_unmeasured_coverage_fails_closed():
    """Offering a metric whose coverage we could not measure is exactly the
    silent-wrong-result the product exists to avoid."""
    assert reg.is_offered(reg.BY_KEY["roe_pct"], None) is False


def test_every_offered_metric_has_an_explainer():
    """C7 is a 100% count check in the UI; it can only pass if the data has it."""
    for m in reg._METRICS:
        assert m.explainer.strip(), m.key


def test_no_metric_is_labelled_one_or_three_year():
    """A3 — 0 of 4,737 symbols have >=252 bars (max 206) on 2026-08-17."""
    for m in reg._METRICS:
        assert not m.key.endswith(reg.BARRED_LABEL_SUFFIXES), m.key


def test_event_categories_match_the_implemented_classifier_set():
    assert len(reg.EVENT_CATEGORIES) == 12
    assert "auditor_resignation" not in reg.EVENT_CATEGORIES  # PRD asks; classifier lacks
    assert {"orders", "capex", "mna", "buyback"} <= set(reg.EVENT_CATEGORIES)


# ── placeholder ordering (regression) ───────────────────────────────────────

def test_where_placeholders_start_at_dollar_one_so_extra_params_must_append():
    """Regression for a live 500 on the zero-result path.

    `where()` numbers its own placeholders from $1 (as_of is $1). Any query that
    REUSES that WHERE and needs an extra parameter must APPEND it, never prepend.
    Prepending shifted every placeholder and handed the date comparison a float:

        asyncpg.exceptions.UndefinedFunctionError:
        operator does not exist: date = double precision

    Unit tests passed because they only ever built a WHERE in isolation; the
    defect only appears when the clause is embedded in a larger statement.
    """
    where_sql, params = _where([{"key": "roe_pct", "op": "gte", "value": 18}], "2026-08-17")
    assert "$1" in where_sql and params[0] == "2026-08-17"

    # correct composition: extra parameter appended, referenced as $N
    pct_params = list(params) + [0.85]
    assert len(pct_params) == 3
    sql = (f"SELECT percentile_cont(${len(pct_params)}) WITHIN GROUP (ORDER BY f.\"roe_pct\") "
           f"FROM nidp.stock_features_daily f WHERE {where_sql}")
    assert "percentile_cont($3)" in sql
    assert pct_params[0] == "2026-08-17", "as_of must remain $1"
    assert pct_params[-1] == 0.85, "the extra parameter must be last"
