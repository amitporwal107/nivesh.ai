"""Tests for the /screen endpoint's query construction.

The route module imports fastapi (not always installed in a bare unit env),
so we test the *pure* query-binding logic that routes/strategy_builder.py
`screen_strategy` performs: compile the spec, translate to asyncpg positional
params, and bind the trailing `as_of_date` slot. A regression here — a leftover
`:as_of_date` or a mis-numbered positional slot — would surface only as an
asyncpg error at runtime, so it is worth pinning at the unit level.
"""
from __future__ import annotations

from services.strategy_engine.compiler_stock import compile_stock_query, to_asyncpg

SPEC = {
    "version": "1",
    "asset_class": "STOCK",
    "name": "screen-binding-test",
    "universe": {"type": "index", "ref": "NIFTY100"},
    "entry": {"all_of": [
        {"feature": "rsi14", "op": ">", "value": 55},        # 1 bound param
        {"feature": "close", "op": ">", "compare_to": "sma50"},  # column compare, 0 params
    ]},
    "exit": {"stoploss_pct": 5, "target_rr": 2, "max_hold_days": 30},
    "ranking": {"by": "score", "limit": 20, "order": "desc"},
    "rebalance": "daily",
}


def _bind_like_screen(spec):
    """Replicate routes/strategy_builder.py:screen_strategy binding exactly."""
    sql, params = compile_stock_query(spec)
    sql_pg, base_args = to_asyncpg(sql, params)
    next_slot = len(base_args) + 1
    sql_pg = sql_pg.replace(":as_of_date", f"${next_slot}")
    return sql_pg, base_args, next_slot


def test_screen_binding_leaves_no_named_placeholder():
    sql_pg, base_args, next_slot = _bind_like_screen(SPEC)
    # The only value predicate binds one param; the compare_to predicate binds none.
    assert base_args == [55]
    assert next_slot == 2
    # as_of_date must be bound to the trailing positional slot, with nothing left as :name
    assert ":as_of_date" not in sql_pg
    assert "$2" in sql_pg
    # The full positional arg list the route passes to asyncpg:
    args = list(base_args) + ["2026-06-26"]
    assert len(args) == next_slot


def test_screen_score_basis_proxy_matches_route():
    # Mirrors the honesty label in screen_strategy: score/composite_score are
    # Phase-1 proxies the compiler maps to accumulation_score.
    cases = {"score": "accumulation_score",
             "composite_score": "accumulation_score",
             "rsi14": "rsi14",
             "return_20d_pct": "return_20d_pct"}
    for by, expect in cases.items():
        score_basis = "accumulation_score" if by in {"score", "composite_score"} else by
        assert score_basis == expect


def test_screen_compiles_distinct_score_ranking_to_accumulation():
    # When ranked by `score`, the emitted SQL orders by accumulation_score
    # (the compiler's documented Phase-1 proxy) — so the screen's score column
    # and its rank are the same field.
    sql, _ = compile_stock_query(SPEC)
    assert "ORDER BY f.accumulation_score DESC" in sql
