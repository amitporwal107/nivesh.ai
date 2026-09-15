"""SQL predicate builder for the screener — the security boundary, kept pure.

Deliberately free of FastAPI (and of any I/O) so it can be exercised on its own:
this is the code that decides what reaches the database, and it should not need a
web framework or a DB to prove it is safe. The router maps ``ScreenQueryError`` to
a 400.

Two invariants this module exists to hold:

  * **Column identifiers come from the metric registry, never from the caller.**
    A key is looked up in ``reg.BY_KEY``; an unknown key is refused before any SQL
    text is built. No caller string is ever interpolated into the statement.
  * **Every caller value is a bound parameter.** Including list values for ``in``,
    which become a single ``= ANY($n)`` array parameter.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from nidp.services.daas_api import metric_registry as reg

FEATURES_TABLE = "nidp.stock_features_daily"

NUMERIC_OPS = {"gte": ">=", "lte": "<=", "gt": ">", "lt": "<", "eq": "="}


class ScreenQueryError(ValueError):
    """A caller-supplied filter is malformed or references an unknown metric."""


def metric_or_raise(key: Any) -> reg.Metric:
    m = reg.BY_KEY.get(key) if isinstance(key, str) else None
    if m is None:
        raise ScreenQueryError(f"unknown metric {key!r}")
    return m


def predicate(f: Dict[str, Any], params: List[Any]) -> str:
    """Build ONE parameterised predicate, appending its values to ``params``."""
    key, op = f.get("key"), f.get("op")
    if not isinstance(key, str) or not isinstance(op, str):
        raise ScreenQueryError("each filter needs a string `key` and `op`")
    m = metric_or_raise(key)
    col = f'f."{m.column}"'   # identifier is registry-controlled, not caller input

    def add(v: Any) -> str:
        params.append(v)
        return f"${len(params)}"

    if op in NUMERIC_OPS:
        if m.is_text and op != "eq":
            raise ScreenQueryError(f"{key!r} is a text metric; use `eq` or `in`")
        value = f.get("value")
        if value is None:
            raise ScreenQueryError(f"{key!r} {op} needs a `value`")
        if m.is_text:
            return f"{col} = {add(str(value))}"
        return f"{col} {NUMERIC_OPS[op]} {add(float(value))}::numeric"

    if op == "between":
        lo, hi = f.get("min"), f.get("max")
        if lo is None or hi is None:
            raise ScreenQueryError(f"{key!r} between needs `min` and `max`")
        if float(lo) > float(hi):
            raise ScreenQueryError(f"{key!r} between: min > max")
        return f"{col} BETWEEN {add(float(lo))}::numeric AND {add(float(hi))}::numeric"

    if op == "in":
        values = f.get("values")
        if not isinstance(values, list) or not values:
            raise ScreenQueryError(f"{key!r} in needs a non-empty `values` list")
        # Exact set membership. The legacy endpoint matches sector with
        # ILIKE '%..%', so "Pharma" also matches "Pharmaceuticals & Biotech" —
        # a filter that quietly returns more than the user asked for.
        if m.is_text:
            return f"UPPER({col}) = ANY({add([str(v).upper() for v in values])}::text[])"
        return f"{col} = ANY({add([float(v) for v in values])}::numeric[])"

    raise ScreenQueryError(f"unsupported op {op!r}")


def where(filters: List[Dict[str, Any]], as_of: Any) -> Tuple[str, List[Any]]:
    """Conjunctive WHERE over the as-of date plus every filter.

    NULL handling is SQL's own: a comparison against NULL is UNKNOWN, so those
    rows drop out. This module must never COALESCE a missing value into 0 (which
    would wrongly satisfy `< 5`) nor admit NULLs explicitly — that is B4.
    """
    params: List[Any] = [as_of]
    clauses = ["f.as_of_date = $1"]
    for f in filters:
        clauses.append(predicate(f, params))
    return " AND ".join(clauses), params


def select_columns(keys: List[str]) -> str:
    """Projection for the requested metric keys, always including identity."""
    cols = ['f.symbol', 'f.as_of_date', 'f.sector']
    for k in keys:
        m = reg.BY_KEY.get(k)
        if m and m.column not in ("symbol", "as_of_date", "sector"):
            cols.append(f'f."{m.column}"')
    seen, out = set(), []
    for c in cols:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return ", ".join(out)
