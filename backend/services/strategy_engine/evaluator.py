"""Pure-Python evaluator for STOCK DSL entry rules + ranking.

This mirrors the SQL semantics of `compiler_stock.py` so the strategy
engine can screen/rank in the app over feature rows fetched from the NIDP
DaaS API — instead of pushing the predicates into NIDP's Postgres (which
isn't reachable as direct SQL on staging/prod). The SQL path
(`SqlMarketDataProvider`) keeps using the compiler; this evaluator is the
portable equivalent used by `DaasMarketDataProvider`.

A row is a plain dict keyed by the feature column names in
`dsl.STOCK_FEATURE_COLS` (plus `symbol`, `as_of_date`). Semantics match the
compiler exactly:

  • numeric `feature op value` / `feature op compare_to`
  • `pivot_breakout_flag = value` boolean special-case
  • a NULL/missing operand never matches (SQL three-valued logic → exclude)
  • ranking by `composite_score`/`score` falls back to `accumulation_score`
    (the compiler's Phase-1 proxy); NULLs sort last either direction.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .dsl import STOCK_FEATURE_COLS, RANKING_FIELDS

_NUM_OPS = {
    "<":  lambda a, b: a < b,
    ">":  lambda a, b: a > b,
    "<=": lambda a, b: a <= b,
    ">=": lambda a, b: a >= b,
    "=":  lambda a, b: a == b,
    "!=": lambda a, b: a != b,
}


class EvalError(Exception):
    """Raised when a predicate references something the evaluator can't handle
    (kept symmetric with compiler_stock.CompileError)."""


def _num(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _match_predicate(p: Dict[str, Any], row: Dict[str, Any]) -> bool:
    ns = next((k for k in ("feature", "fundamental", "shareholding",
                           "institutional", "mf", "sector") if k in p), None)
    if ns != "feature":
        raise EvalError(f"namespace {ns!r} not supported (Phase-1 = feature.* only)")
    field = p["feature"]
    if field not in STOCK_FEATURE_COLS:
        raise EvalError(f"unknown feature {field!r}")
    op = p["op"]

    # pivot_breakout_flag: boolean stored as 0/1 — `op` is = or != vs value.
    if field == "pivot_breakout_flag":
        if "value" not in p:
            raise EvalError("pivot_breakout_flag requires `value`")
        if op not in ("=", "!="):
            raise EvalError("pivot_breakout_flag only supports = and !=")
        raw = row.get(field)
        if raw is None:
            return False
        truthy_target = bool(int(p["value"]))
        actual = bool(int(raw)) if not isinstance(raw, bool) else raw
        return (actual == truthy_target) if op == "=" else (actual != truthy_target)

    if op not in _NUM_OPS:
        raise EvalError(f"unsupported op {op!r}")
    left = _num(row.get(field))
    if left is None:
        return False  # NULL operand never matches (SQL semantics)

    if "value" in p:
        right = _num(p["value"])
    else:
        other = p["compare_to"]
        if other not in STOCK_FEATURE_COLS:
            raise EvalError(f"compare_to {other!r} not in feature whitelist")
        right = _num(row.get(other))
    if right is None:
        return False
    return _NUM_OPS[op](left, right)


def _matches_entry(entry: Dict[str, Any], row: Dict[str, Any]) -> bool:
    if "all_of" in entry:
        if not all(_match_predicate(p, row) for p in entry["all_of"]):
            return False
    if "any_of" in entry and entry["any_of"]:
        if not any(_match_predicate(p, row) for p in entry["any_of"]):
            return False
    return True


def ranking_field(by: str) -> str:
    """The actual row key used for ranking — mirrors compiler_stock: the
    `score`/`composite_score` aliases resolve to accumulation_score."""
    if by not in RANKING_FIELDS:
        raise EvalError(f"ranking.by {by!r} not in allowed fields")
    return "accumulation_score" if by in {"composite_score", "score"} else by


def screen_rows(spec: Dict[str, Any], rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Apply the spec's entry rules to `rows`, rank, and cap to ranking.limit.

    Returns the matched rows in ranked order (each row dict unchanged). Same
    result set + order the compiled SQL would return for one as_of_date.
    """
    matched = [r for r in rows if _matches_entry(spec["entry"], r)]

    ranking = spec["ranking"]
    by = ranking_field(ranking["by"])
    desc = ranking.get("order", "desc").lower() != "asc"
    limit = int(ranking["limit"])

    # NULLs last in both directions (SQL `NULLS LAST`).
    def sort_key(r):
        v = _num(r.get(by))
        return (v is None, -v if (v is not None and desc) else (v if v is not None else 0.0))

    matched.sort(key=sort_key)
    return matched[:limit]
